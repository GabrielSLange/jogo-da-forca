import socket
import threading
import sqlite3
import random
import time
import uuid
import sys
import json
import os
import select

# ─────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────
MAX_ERROS = 6
RECV_TIMEOUT = 120  # segundos
DB_TIMEOUT = 10
HEARTBEAT_INTERVAL = 3  # segundos
HEARTBEAT_TIMEOUT = 5  # segundos
MATCHMAKER_INTERVAL = 1  # segundos
POLL_INTERVAL = 0.4  # segundos — polling do estado do jogo

PALAVRAS = [
    "SISTEMAS", "DISTRIBUIDO", "CONCORRENCIA", "REDUNDANCIA", "SOCKETS",
    "SERVIDOR", "PROTOCOLO", "REDE", "INTERNET", "FIREWALL",
    "CRIPTOGRAFIA", "ALGORITMO", "PROCESSADOR", "MEMORIA", "BINARIO",
    "COMPILADOR", "TERMINAL", "VARIAVEL", "FUNCAO", "PROGRAMA",
    "HARDWARE", "SOFTWARE", "TECLADO", "MONITOR", "ROTEADOR",
    "PACOTE", "LATENCIA", "CLUSTER", "GATEWAY", "THREADS"
]

# Estado global do servidor
server_info = {
    "port": None,
    "peer_host": None,
    "peer_sync_port": None,
    "sync_port": None,
    "peer_alive": False,
    "clients_connected": 0,
    "games_active": 0,
    "lock": threading.Lock(),
}

# ─────────────────────────────────────────────────────────────
# Banco de Dados
# ─────────────────────────────────────────────────────────────

def get_db_path():
    """Retorna o caminho do banco de dados compartilhado."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'forca.db')

def get_db():
    """Cria uma nova conexão SQLite com WAL mode e timeout adequado."""
    db_conn = sqlite3.connect(get_db_path(), timeout=DB_TIMEOUT)
    db_conn.execute("PRAGMA journal_mode=WAL")
    db_conn.execute("PRAGMA busy_timeout=5000")
    return db_conn

def init_db():
    """Inicializa as tabelas e limpa dados stale de sessões anteriores."""
    db_conn = get_db()
    cursor = db_conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS jogadores 
                      (id TEXT PRIMARY KEY, status TEXT, server_port INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS jogos 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                       p1 TEXT, p2 TEXT, palavra TEXT, oculta TEXT, 
                       erros INTEGER, turno TEXT, status TEXT, tentativas TEXT)''')
    # Limpar dados de sessões anteriores
    cursor.execute("DELETE FROM jogadores")
    cursor.execute("UPDATE jogos SET status='finished' WHERE status='active'")
    db_conn.commit()
    db_conn.close()
    print("[DB] Banco de dados inicializado e limpo.")

# ─────────────────────────────────────────────────────────────
# Matchmaker — Emparelha jogadores com lock exclusivo
# ─────────────────────────────────────────────────────────────

def matchmaker():
    """Thread que emparelha jogadores aguardando em pares."""
    while True:
        db_conn = None
        try:
            db_conn = get_db()
            db_conn.isolation_level = 'EXCLUSIVE'
            cursor = db_conn.cursor()
            cursor.execute("BEGIN EXCLUSIVE")
            cursor.execute("SELECT id FROM jogadores WHERE status='waiting' ORDER BY rowid LIMIT 2")
            waiting = cursor.fetchall()

            if len(waiting) == 2:
                player1_id = waiting[0][0]
                player2_id = waiting[1][0]
                palavra = random.choice(PALAVRAS)
                oculta = "_" * len(palavra)

                cursor.execute(
                    "INSERT INTO jogos (p1, p2, palavra, oculta, erros, turno, status, tentativas) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (player1_id, player2_id, palavra, oculta, 0, player1_id, 'active', '')
                )
                cursor.execute(
                    "UPDATE jogadores SET status='playing' WHERE id IN (?, ?)",
                    (player1_id, player2_id)
                )
                db_conn.commit()
                print(f"[MATCH] Partida criada: {player1_id[:8]}... vs {player2_id[:8]}... | Palavra: {palavra}")
            else:
                db_conn.commit()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                print("[MATCH] Banco travado, tentando novamente...")
            else:
                print(f"[MATCH] Erro SQLite: {e}")
        except sqlite3.Error as e:
            print(f"[MATCH] Erro SQLite: {e}")
        finally:
            if db_conn:
                try:
                    db_conn.close()
                except Exception:
                    pass

        time.sleep(MATCHMAKER_INTERVAL)

# ─────────────────────────────────────────────────────────────
# Utilitário seguro para enviar dados ao cliente
# ─────────────────────────────────────────────────────────────

def safe_send(conn, data):
    """Envia dados ao socket tratando exceções. Retorna False se falhou."""
    try:
        if isinstance(data, str):
            data = data.encode('utf-8')
        conn.sendall(data)
        return True
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
        return False

def drain_pings(client_conn):
    """Drena e responde PINGs pendentes no buffer do socket usando select (não-bloqueante)."""
    while True:
        ready, _, _ = select.select([client_conn], [], [], 0)
        if not ready:
            break
        try:
            peek_data = client_conn.recv(1024, socket.MSG_PEEK)
            if not peek_data:
                break
            if peek_data.strip().upper() == b"PING":
                client_conn.recv(1024)  # consumir
                safe_send(client_conn, "PONG\n")
            else:
                break  # dado real (não PING), não consumir
        except (ConnectionError, OSError):
            break

# ─────────────────────────────────────────────────────────────
# Handler de cliente — Lógica principal do jogo
# ─────────────────────────────────────────────────────────────

def handle_client(client_conn, addr):
    """Lida com a conexão de um cliente do início ao fim."""
    player_id = str(uuid.uuid4())
    game_id = None
    db_conn = None

    with server_info["lock"]:
        server_info["clients_connected"] += 1

    print(f"[CONN] {addr} conectou — ID: {player_id[:8]}...")

    try:
        # Registrar jogador no banco
        db_conn = get_db()
        cursor = db_conn.cursor()
        cursor.execute(
            "INSERT INTO jogadores (id, status, server_port) VALUES (?, ?, ?)",
            (player_id, 'waiting', server_info["port"])
        )
        db_conn.commit()

        if not safe_send(client_conn, "Aguardando adversario...\n"):
            return

        # Aguardar matchmaking
        while True:
            cursor.execute(
                "SELECT id FROM jogos WHERE (p1=? OR p2=?) AND status='active'",
                (player_id, player_id)
            )
            row = cursor.fetchone()
            if row:
                game_id = row[0]
                break
            time.sleep(POLL_INTERVAL)

        if not safe_send(client_conn, "Adversario encontrado! O jogo vai comecar.\n"):
            return

        # Configurar timeout para recv
        client_conn.settimeout(RECV_TIMEOUT)

        # ─── Game Loop ───
        last_oculta = ""
        last_erros = -1
        last_turno = ""

        while True:
            cursor.execute(
                "SELECT p1, p2, palavra, oculta, erros, turno, status, tentativas "
                "FROM jogos WHERE id=?", (game_id,)
            )
            game = cursor.fetchone()

            if not game:
                safe_send(client_conn, "Erro: jogo nao encontrado.\n")
                break

            p1, p2, palavra, oculta, erros, turno, status, tentativas = game

            # Verificar se adversário desconectou
            opponent_id = p2 if player_id == p1 else p1
            cursor.execute("SELECT id FROM jogadores WHERE id=?", (opponent_id,))
            if not cursor.fetchone() and status == 'active':
                safe_send(client_conn, "O adversario desconectou. Voce venceu!\n")
                cursor.execute(
                    "UPDATE jogos SET status='finished' WHERE id=?", (game_id,)
                )
                db_conn.commit()
                break

            # Enviar estado atualizado
            if oculta != last_oculta or erros != last_erros:
                letras_tentadas = ' '.join(tentativas.split(',')) if tentativas else ''
                erros_partes = []
                partes_corpo = ["cabeca", "tronco", "braco dir.", "braco esq.", "perna dir.", "perna esq."]
                for i in range(min(erros, MAX_ERROS)):
                    erros_partes.append(partes_corpo[i])
                partes_str = ', '.join(erros_partes) if erros_partes else 'nenhuma'

                estado = (
                    f"\nPalavra: {' '.join(oculta)} | "
                    f"Erros: {erros}/{MAX_ERROS} ({partes_str}) | "
                    f"Tentativas: {letras_tentadas}\n"
                )
                if not safe_send(client_conn, estado):
                    break
                last_oculta = oculta
                last_erros = erros
                last_turno = ""

            # Jogo terminou?
            if status == 'finished':
                if "_" not in oculta:
                    safe_send(client_conn, f"VITORIA! A palavra era: {palavra}\n")
                else:
                    safe_send(client_conn, f"DERROTA! A palavra era: {palavra}\n")
                break

            # Turno do jogador
            if turno == player_id and last_turno != player_id:
                if not safe_send(client_conn, "Sua vez! Digite uma letra: \n"):
                    break
                last_turno = player_id

                try:
                    chute = client_conn.recv(1024).decode('utf-8').strip().upper()
                except socket.timeout:
                    safe_send(client_conn, "Timeout! Voce demorou demais.\n")
                    break
                except UnicodeDecodeError:
                    continue

                if not chute:
                    break

                # Tratar PING de latência
                if chute == "PING":
                    safe_send(client_conn, "PONG\n")
                    last_turno = ""  # Não consume o turno
                    continue

                if len(chute) == 1 and chute.isalpha():
                    # Verificar se letra já foi tentada
                    letras_ja_tentadas = tentativas.split(',') if tentativas else []
                    if chute in letras_ja_tentadas:
                        safe_send(client_conn, f"Letra '{chute}' ja foi tentada! Tente outra.\n")
                        last_turno = ""  # Permite tentar novamente
                        continue

                    novas_tentativas = f"{tentativas},{chute}" if tentativas else chute
                    novo_turno = p2 if player_id == p1 else p1

                    if chute in palavra:
                        nova_oculta = list(oculta)
                        for i, letra in enumerate(palavra):
                            if letra == chute:
                                nova_oculta[i] = chute
                        nova_oculta_str = "".join(nova_oculta)
                        novo_status = 'finished' if "_" not in nova_oculta_str else 'active'
                        cursor.execute(
                            "UPDATE jogos SET oculta=?, turno=?, status=?, tentativas=? WHERE id=?",
                            (nova_oculta_str, novo_turno, novo_status, novas_tentativas, game_id)
                        )
                        if not safe_send(client_conn, f"Acertou! A letra '{chute}' esta na palavra.\n"):
                            break
                    else:
                        novos_erros = erros + 1
                        novo_status = 'finished' if novos_erros >= MAX_ERROS else 'active'
                        cursor.execute(
                            "UPDATE jogos SET erros=?, turno=?, status=?, tentativas=? WHERE id=?",
                            (novos_erros, novo_turno, novo_status, novas_tentativas, game_id)
                        )
                        parte_perdida = ["cabeca", "tronco", "braco direito",
                                         "braco esquerdo", "perna direita", "perna esquerda"]
                        if novos_erros <= MAX_ERROS:
                            if not safe_send(client_conn,
                                f"Errou! Perdeu: {parte_perdida[novos_erros-1]}.\n"):
                                break
                    db_conn.commit()
                else:
                    safe_send(client_conn, "Entrada invalida! Digite apenas uma letra.\n")
                    last_turno = ""  # Permite tentar novamente
                    continue

            elif turno != player_id and last_turno != turno:
                if not safe_send(client_conn, "Aguardando o turno do adversario...\n"):
                    break
                last_turno = turno

            # Responder PINGs pendentes durante qualquer fase
            drain_pings(client_conn)

            time.sleep(POLL_INTERVAL)

    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError) as e:
        print(f"[CONN] {addr} — conexao perdida: {e}")
    except Exception as e:
        print(f"[CONN] {addr} — erro inesperado: {e}")
    finally:
        # Limpeza — remover jogador e finalizar jogo
        try:
            cleanup_db = get_db()
            cleanup_cursor = cleanup_db.cursor()
            cleanup_cursor.execute("DELETE FROM jogadores WHERE id=?", (player_id,))
            if game_id:
                cleanup_cursor.execute(
                    "UPDATE jogos SET status='finished' WHERE id=? AND status='active'",
                    (game_id,)
                )
            cleanup_db.commit()
            cleanup_db.close()
            print(f"[CLEAN] Jogador {player_id[:8]}... removido do banco.")
        except sqlite3.Error as e:
            print(f"[CLEAN] Erro ao limpar jogador: {e}")

        if db_conn:
            try:
                db_conn.close()
            except Exception:
                pass
        try:
            client_conn.close()
        except Exception:
            pass

        with server_info["lock"]:
            server_info["clients_connected"] -= 1

        print(f"[CONN] {addr} desconectou.")

# ─────────────────────────────────────────────────────────────
# Health Check — Heartbeat entre servidores
# ─────────────────────────────────────────────────────────────

def health_check_server(sync_port):
    """Servidor de health check que responde HEARTBEATs do peer."""
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind(('0.0.0.0', sync_port))
        server_sock.listen(2)
        server_sock.settimeout(2)
        print(f"[SYNC] Health check listening na porta {sync_port}")

        while True:
            try:
                peer_conn, peer_addr = server_sock.accept()
                threading.Thread(
                    target=handle_heartbeat_connection,
                    args=(peer_conn, peer_addr),
                    daemon=True
                ).start()
            except socket.timeout:
                continue
            except OSError:
                break
    except OSError as e:
        print(f"[SYNC] Erro ao iniciar health check: {e}")

def handle_heartbeat_connection(peer_conn, peer_addr):
    """Responde pings do servidor peer."""
    peer_conn.settimeout(HEARTBEAT_TIMEOUT)
    try:
        while True:
            data = peer_conn.recv(1024).decode()
            if not data:
                break
            if data.strip() == "HEARTBEAT":
                # Enviar resposta com status do servidor
                db_conn = get_db()
                cursor = db_conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM jogadores")
                players = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM jogos WHERE status='active'")
                games = cursor.fetchone()[0]
                db_conn.close()

                response = json.dumps({
                    "status": "alive",
                    "port": server_info["port"],
                    "players": players,
                    "active_games": games
                })
                peer_conn.sendall(f"{response}\n".encode())
    except (socket.timeout, ConnectionError, OSError):
        pass
    finally:
        try:
            peer_conn.close()
        except Exception:
            pass

def heartbeat_client(peer_host, peer_sync_port):
    """Thread que envia heartbeats periódicos ao servidor peer."""
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(HEARTBEAT_TIMEOUT)
            sock.connect((peer_host, peer_sync_port))

            while True:
                sock.sendall(b"HEARTBEAT\n")
                response = sock.recv(1024).decode()
                if response:
                    peer_data = json.loads(response.strip())
                    with server_info["lock"]:
                        if not server_info["peer_alive"]:
                            print(f"[SYNC] Peer na porta {peer_data.get('port', '?')} esta ONLINE "
                                  f"({peer_data.get('players', 0)} jogadores, "
                                  f"{peer_data.get('active_games', 0)} jogos ativos)")
                        server_info["peer_alive"] = True
                time.sleep(HEARTBEAT_INTERVAL)

        except (ConnectionRefusedError, socket.timeout, ConnectionError, OSError, json.JSONDecodeError):
            with server_info["lock"]:
                if server_info["peer_alive"]:
                    print(f"[SYNC] Peer em {peer_host}:{peer_sync_port} esta OFFLINE")
                server_info["peer_alive"] = False
            try:
                sock.close()
            except Exception:
                pass
            time.sleep(HEARTBEAT_INTERVAL)

# ─────────────────────────────────────────────────────────────
# Monitor — Exibe status periódico no console
# ─────────────────────────────────────────────────────────────

def monitor():
    """Thread que imprime status do servidor periodicamente."""
    while True:
        time.sleep(15)
        try:
            db_conn = get_db()
            cursor = db_conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jogadores WHERE status='waiting'")
            waiting = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM jogadores WHERE status='playing'")
            playing = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM jogos WHERE status='active'")
            active_games = cursor.fetchone()[0]
            db_conn.close()

            with server_info["lock"]:
                peer_status = "ONLINE" if server_info["peer_alive"] else "OFFLINE"

            print(f"[MONITOR] Aguardando: {waiting} | Jogando: {playing} | "
                  f"Jogos ativos: {active_games} | Peer: {peer_status}")
        except sqlite3.Error:
            pass

# ─────────────────────────────────────────────────────────────
# Servidor Principal
# ─────────────────────────────────────────────────────────────

def start_server(port, sync_port=None, peer_host=None, peer_sync_port=None):
    """Inicia o servidor de jogo com suporte a redundância."""
    server_info["port"] = port
    server_info["sync_port"] = sync_port
    server_info["peer_host"] = peer_host
    server_info["peer_sync_port"] = peer_sync_port

    init_db()

    # Thread do matchmaker
    threading.Thread(target=matchmaker, daemon=True).start()

    # Thread de monitoramento
    threading.Thread(target=monitor, daemon=True).start()

    # Health check — servidor de sync
    if sync_port:
        threading.Thread(target=health_check_server, args=(sync_port,), daemon=True).start()

    # Health check — cliente para o peer
    if peer_host and peer_sync_port:
        threading.Thread(
            target=heartbeat_client,
            args=(peer_host, peer_sync_port),
            daemon=True
        ).start()

    # Socket principal do jogo
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(('0.0.0.0', port))
    server_sock.listen()

    print(f"══════════════════════════════════════════════════")
    print(f"  Jogo da Forca — Servidor na porta {port}")
    if sync_port:
        print(f"  Sync/Health Check na porta {sync_port}")
    if peer_host and peer_sync_port:
        print(f"  Peer: {peer_host}:{peer_sync_port}")
    print(f"══════════════════════════════════════════════════")

    try:
        while True:
            client_conn, addr = server_sock.accept()
            print(f"[CONN] Nova conexao: {addr}")
            threading.Thread(
                target=handle_client,
                args=(client_conn, addr),
                daemon=True
            ).start()
    except KeyboardInterrupt:
        print("\n[SERVER] Encerrando servidor...")
    finally:
        server_sock.close()

# ─────────────────────────────────────────────────────────────
# Ponto de entrada
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Uso:
    #   Servidor 1: python servidor.py 5000 5010 localhost 5011
    #   Servidor 2: python servidor.py 5001 5011 localhost 5010
    #
    # Argumentos:
    #   porta_jogo   — porta para clientes (obrigatório)
    #   porta_sync   — porta do health check deste servidor (opcional)
    #   peer_host    — host do servidor peer (opcional)
    #   peer_sync    — porta de sync do peer (opcional)

    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    sync_port_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None
    peer_host_arg = sys.argv[3] if len(sys.argv) > 3 else None
    peer_sync_arg = int(sys.argv[4]) if len(sys.argv) > 4 else None

    start_server(port_arg, sync_port_arg, peer_host_arg, peer_sync_arg)