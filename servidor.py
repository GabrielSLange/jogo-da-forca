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
DB_TIMEOUT = 10
HEARTBEAT_INTERVAL = 3  # segundos
HEARTBEAT_TIMEOUT = 5  # segundos
MATCHMAKER_INTERVAL = 1  # segundos
POLL_INTERVAL = 0.4  # segundos — polling do estado do jogo
DISCONNECT_TIMEOUT = 30 # segundos para perder por W.O.

PALAVRAS = [
    "SISTEMAS", "DISTRIBUIDO", "CONCORRENCIA", "REDUNDANCIA", "SOCKETS",
    "SERVIDOR", "PROTOCOLO", "REDE", "INTERNET", "FIREWALL",
    "CRIPTOGRAFIA", "ALGORITMO", "PROCESSADOR", "MEMORIA", "BINARIO",
    "COMPILADOR", "TERMINAL", "VARIAVEL", "FUNCAO", "PROGRAMA",
    "HARDWARE", "SOFTWARE", "TECLADO", "MONITOR", "ROTEADOR",
    "PACOTE", "LATENCIA", "CLUSTER", "GATEWAY", "THREADS"
]

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

# Registro de conexões ativas de jogadores aguardando — para notificações push
waiting_clients = {}  # player_id -> socket connection
waiting_clients_lock = threading.Lock()

def notify_waiting_players(new_player_id, new_player_nome):
    """Notifica jogadores na fila que um novo jogador se conectou."""
    with waiting_clients_lock:
        for pid, conn in list(waiting_clients.items()):
            if pid != new_player_id:
                try:
                    safe_send(conn, f"📢 Novo jogador na fila: {new_player_nome}! Pareamento em breve...\n")
                except Exception:
                    pass

def get_db_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'forca.db')

def get_db():
    db_conn = sqlite3.connect(get_db_path(), timeout=DB_TIMEOUT)
    db_conn.execute("PRAGMA journal_mode=WAL")
    db_conn.execute("PRAGMA busy_timeout=5000")
    return db_conn

def init_db():
    db_conn = get_db()
    cursor = db_conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS jogadores 
                      (id TEXT PRIMARY KEY, nome TEXT, status TEXT, server_port INTEGER, disconnect_time REAL)''')
    try: cursor.execute("ALTER TABLE jogadores ADD COLUMN nome TEXT")
    except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE jogadores ADD COLUMN disconnect_time REAL")
    except sqlite3.OperationalError: pass

    cursor.execute('''CREATE TABLE IF NOT EXISTS jogos 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                       p1 TEXT, p2 TEXT, palavra TEXT, oculta TEXT, 
                       erros INTEGER, turno TEXT, status TEXT, tentativas TEXT)''')
    # Remoção das linhas que apagavam os dados, 
    # pois se o Servidor 2 iniciar depois do Servidor 1, ele apagava os jogadores do Servidor 1!
    # cursor.execute("DELETE FROM jogadores")
    # cursor.execute("UPDATE jogos SET status='finished' WHERE status='active'")
    db_conn.commit()
    db_conn.close()
    print("[DB] Banco de dados inicializado e atualizado.")

def matchmaker():
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
                p1_id, p2_id = waiting[0][0], waiting[1][0]
                palavra = random.choice(PALAVRAS)
                oculta = "_" * len(palavra)

                cursor.execute(
                    "INSERT INTO jogos (p1, p2, palavra, oculta, erros, turno, status, tentativas) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (p1_id, p2_id, palavra, oculta, 0, p1_id, 'active', '')
                )
                cursor.execute("UPDATE jogadores SET status='playing' WHERE id IN (?, ?)", (p1_id, p2_id))
                db_conn.commit()
                print(f"[MATCH] Partida criada: {p1_id[:8]}... vs {p2_id[:8]}... | Palavra: {palavra}")
            else:
                db_conn.commit()
        except Exception as e:
            print(f"[MATCHMAKER ERRO] {e}")
        finally:
            if db_conn:
                try: db_conn.close()
                except: pass
        time.sleep(MATCHMAKER_INTERVAL)

def safe_send(conn, data):
    try:
        if isinstance(data, str): data = data.encode('utf-8')
        conn.sendall(data)
        return True
    except Exception:
        return False

def handle_client(client_conn, addr):
    client_conn.settimeout(5)
    try:
        buf = b""
        while b"\n" not in buf:
            chunk = client_conn.recv(1)
            if not chunk: raise Exception("Closed")
            buf += chunk
        data = buf.decode('utf-8').strip()
        if not data.startswith("CONNECT|"):
            client_conn.close()
            return
        parts = data.split("|", 2)
        if len(parts) == 3:
            _, player_id, player_nome = parts
        else:
            client_conn.close()
            return
    except Exception:
        client_conn.close()
        return

    client_conn.settimeout(None)

    with server_info["lock"]:
        server_info["clients_connected"] += 1

    print(f"[CONN] {addr} conectou — ID: {player_id[:8]}... Nome: {player_nome}")

    db_conn = get_db()
    cursor = db_conn.cursor()
    cursor.execute("SELECT status FROM jogadores WHERE id=?", (player_id,))
    row = cursor.fetchone()

    game_id = None
    if row:
        cursor.execute("UPDATE jogadores SET disconnect_time=NULL WHERE id=?", (player_id,))
        if not safe_send(client_conn, f"Bem-vindo de volta, {player_nome}!\n"):
            return
            
        cursor.execute("SELECT id FROM jogos WHERE (p1=? OR p2=?) AND status='active'", (player_id, player_id))
        game_row = cursor.fetchone()
        if game_row:
            game_id = game_row[0]
            cursor.execute("UPDATE jogadores SET status='playing' WHERE id=?", (player_id,))
            safe_send(client_conn, "Reconectado ao jogo em andamento!\n")
        else:
            cursor.execute("UPDATE jogadores SET status='waiting' WHERE id=?", (player_id,))
            safe_send(client_conn, "Sua partida anterior ja terminou. Aguardando novo adversario...\n")
            with waiting_clients_lock:
                waiting_clients[player_id] = client_conn
        db_conn.commit()
    else:
        cursor.execute(
            "INSERT INTO jogadores (id, nome, status, server_port) VALUES (?, ?, ?, ?)",
            (player_id, player_nome, 'waiting', server_info["port"])
        )
        db_conn.commit()
        with waiting_clients_lock:
            waiting_clients[player_id] = client_conn
        if not safe_send(client_conn, f"Ola {player_nome}. Aguardando adversario...\n"):
            return
        # Notificar outros jogadores na fila que alguém novo entrou
        notify_waiting_players(player_id, player_nome)

    last_oculta = ""
    last_erros = -1
    last_turno = ""
    last_ui_update = 0
    buffer_in = ""

    try:
        while True:
            if not game_id:
                cursor.execute("SELECT id FROM jogos WHERE (p1=? OR p2=?) AND status='active'", (player_id, player_id))
                r = cursor.fetchone()
                if r:
                    game_id = r[0]
                    # Remover da lista de espera
                    with waiting_clients_lock:
                        waiting_clients.pop(player_id, None)
                    safe_send(client_conn, "Adversario encontrado! O jogo vai comecar.\n")
                    last_oculta = ""
                    last_erros = -1
                    last_turno = ""
                else:
                    now = time.time()
                    if now - last_ui_update > 2:
                        cursor.execute("SELECT id FROM jogadores WHERE status='waiting' ORDER BY rowid")
                        waiting = cursor.fetchall()
                        pos = 0
                        for i, (w_id,) in enumerate(waiting):
                            if w_id == player_id:
                                pos = i + 1
                                break
                        if pos > 0:
                            safe_send(client_conn, f"Aguardando adversario... Voce e o {pos}o na fila.\n")
                        last_ui_update = now

            game = None
            if game_id:
                cursor.execute(
                    "SELECT p1, p2, palavra, oculta, erros, turno, status, tentativas "
                    "FROM jogos WHERE id=?", (game_id,)
                )
                game = cursor.fetchone()

            if game:
                p1, p2, palavra, oculta, erros, turno, status, tentativas = game
                opponent_id = p2 if player_id == p1 else p1
                
                cursor.execute("SELECT status, disconnect_time FROM jogadores WHERE id=?", (opponent_id,))
                opp_row = cursor.fetchone()
                
                opp_is_disconnected = False
                
                if opp_row:
                    opp_status, opp_disc_time = opp_row
                    if opp_status == 'disconnected':
                        opp_is_disconnected = True
                        if opp_disc_time and (time.time() - opp_disc_time) > DISCONNECT_TIMEOUT:
                            safe_send(client_conn, "O adversario desconectou por mais de 30s. Voce venceu por W.O.!\n")
                            cursor.execute("UPDATE jogos SET status='finished' WHERE id=?", (game_id,))
                            db_conn.commit()
                            break
                        else:
                            now = time.time()
                            if now - last_ui_update > 3:
                                rem = DISCONNECT_TIMEOUT - int(now - opp_disc_time)
                                safe_send(client_conn, f"Adversario perdeu conexao! Aguardando retorno (restam {rem}s)...\n")
                                last_ui_update = now
                else:
                    if status == 'active':
                        safe_send(client_conn, "O adversario abandonou a partida. Voce venceu!\n")
                        cursor.execute("UPDATE jogos SET status='finished' WHERE id=?", (game_id,))
                        db_conn.commit()
                        break

                if status == 'finished':
                    # Como o 'turno' no banco foi invertido após a última jogada, 
                    # se player_id != turno, então player_id foi quem fez a última jogada.
                    is_last_player = (player_id != turno)
                    
                    if "_" not in oculta:
                        if is_last_player:
                            safe_send(client_conn, f"VITORIA! Voce acertou a ultima letra: {palavra}\n")
                        else:
                            safe_send(client_conn, f"DERROTA! O adversario completou a palavra: {palavra}\n")
                    else:
                        if is_last_player:
                            safe_send(client_conn, f"DERROTA! Voce esgotou as chances. A palavra era: {palavra}\n")
                        else:
                            safe_send(client_conn, f"VITORIA! O adversario foi enforcado. A palavra era: {palavra}\n")
                    break

                if not opp_is_disconnected and status == 'active':
                    if oculta != last_oculta or erros != last_erros:
                        # Separar letras certas e erradas
                        letras_lista = tentativas.split(',') if tentativas else []
                        letras_certas = [l for l in letras_lista if l in palavra]
                        letras_erradas = [l for l in letras_lista if l not in palavra]
                        certas_str = ' '.join(letras_certas) if letras_certas else ''
                        erradas_str = ' '.join(letras_erradas) if letras_erradas else ''

                        partes_corpo = ["cabeca", "tronco", "braco dir.", "braco esq.", "perna dir.", "perna esq."]
                        erros_partes = [partes_corpo[i] for i in range(min(erros, MAX_ERROS))]
                        partes_str = ', '.join(erros_partes) if erros_partes else 'nenhuma'

                        estado = (f"\nPalavra: {' '.join(oculta)} | "
                                  f"Erros: {erros}/{MAX_ERROS} ({partes_str}) | "
                                  f"Certas: {certas_str} | "
                                  f"Erradas: {erradas_str}\n")
                        safe_send(client_conn, estado)
                        last_oculta = oculta
                        last_erros = erros
                        last_turno = ""

                    if turno == player_id and last_turno != player_id:
                        safe_send(client_conn, "Sua vez! Digite uma letra: \n")
                        last_turno = player_id
                    elif turno != player_id and last_turno != turno:
                        safe_send(client_conn, "Aguardando o turno do adversario...\n")
                        last_turno = turno

            db_conn.commit()  # IMPORTANTE: Força o SQLite a renovar o snapshot para que este loop veja alterações feitas pelo outro servidor!
            ready, _, _ = select.select([client_conn], [], [], POLL_INTERVAL)
            if ready:
                data = client_conn.recv(1024).decode('utf-8')
                if not data: break
                buffer_in += data
                while "\n" in buffer_in:
                    linha, buffer_in = buffer_in.split("\n", 1)
                    linha = linha.strip().upper()
                    if not linha: continue

                    if linha == "PING":
                        safe_send(client_conn, "PONG\n")
                    elif linha.startswith("LETRA|"):
                        if game and not opp_is_disconnected and turno == player_id:
                            chute = linha.split("|", 1)[1]
                            if not chute or not chute.isalpha() or len(chute) != 1:
                                safe_send(client_conn, "Entrada invalida! Digite apenas uma letra.\n")
                                last_turno = ""
                                continue

                            letras_ja_tentadas = tentativas.split(',') if tentativas else []
                            if chute in letras_ja_tentadas:
                                safe_send(client_conn, f"Letra '{chute}' ja foi tentada! Tente outra.\n")
                                last_turno = ""
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
                                cursor.execute("UPDATE jogos SET oculta=?, turno=?, status=?, tentativas=? WHERE id=?",
                                               (nova_oculta_str, novo_turno, novo_status, novas_tentativas, game_id))
                                safe_send(client_conn, f"Acertou! A letra '{chute}' esta na palavra.\n")
                            else:
                                novos_erros = erros + 1
                                novo_status = 'finished' if novos_erros >= MAX_ERROS else 'active'
                                cursor.execute("UPDATE jogos SET erros=?, turno=?, status=?, tentativas=? WHERE id=?",
                                               (novos_erros, novo_turno, novo_status, novas_tentativas, game_id))
                                parte_perdida = ["cabeca", "tronco", "braco direito", "braco esquerdo", "perna direita", "perna esquerda"]
                                if novos_erros <= MAX_ERROS:
                                    safe_send(client_conn, f"Errou! Perdeu: {parte_perdida[novos_erros-1]}.\n")
                            db_conn.commit()

    except Exception as e:
        print(f"[CONN] {addr} — conexao perdida: {e}")
    finally:
        # Remover da lista de espera ao desconectar
        with waiting_clients_lock:
            waiting_clients.pop(player_id, None)

        try:
            cleanup_db = get_db()
            cleanup_cursor = cleanup_db.cursor()
            cleanup_cursor.execute(
                "UPDATE jogadores SET status='disconnected', disconnect_time=? WHERE id=?",
                (time.time(), player_id)
            )
            cleanup_db.commit()
            cleanup_db.close()
        except Exception:
            pass

        if db_conn:
            try: db_conn.close()
            except: pass
        try: client_conn.close()
        except: pass

        with server_info["lock"]:
            server_info["clients_connected"] -= 1

        print(f"[CONN] {addr} desconectou.")

def disconnection_monitor():
    while True:
        try:
            db_conn = get_db()
            cursor = db_conn.cursor()
            now = time.time()
            cursor.execute("SELECT id FROM jogadores WHERE status='disconnected' AND disconnect_time IS NOT NULL AND (? - disconnect_time) > ?", (now, DISCONNECT_TIMEOUT))
            deleted = cursor.fetchall()
            for (pid,) in deleted:
                cursor.execute("DELETE FROM jogadores WHERE id=?", (pid,))
                print(f"[CLEAN] Jogador {pid[:8]}... expirou. Removido.")
            db_conn.commit()
            db_conn.close()
        except Exception:
            pass
        time.sleep(2)

def monitor():
    while True:
        time.sleep(15)
        try:
            db_conn = get_db()
            cursor = db_conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM jogadores WHERE status='waiting'")
            w = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM jogadores WHERE status='playing'")
            p = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM jogos WHERE status='active'")
            g = cursor.fetchone()[0]
            db_conn.close()

            with server_info["lock"]:
                peer_s = "ONLINE" if server_info["peer_alive"] else "OFFLINE"

            print(f"[MONITOR] Aguardando: {w} | Jogando: {p} | Jogos ativos: {g} | Peer: {peer_s}")
        except Exception:
            pass

def health_check_server(sync_port):
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind(('0.0.0.0', sync_port))
        server_sock.listen(2)
        server_sock.settimeout(2)
        while True:
            try:
                peer_conn, _ = server_sock.accept()
                threading.Thread(target=handle_heartbeat_connection, args=(peer_conn,), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break
    except Exception as e:
        print(f"[SYNC] Erro ao iniciar health check: {e}")

def handle_heartbeat_connection(peer_conn):
    peer_conn.settimeout(HEARTBEAT_TIMEOUT)
    try:
        while True:
            data = peer_conn.recv(1024).decode()
            if not data: break
            if data.strip() == "HEARTBEAT":
                db_conn = get_db()
                cursor = db_conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM jogadores")
                players = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM jogos WHERE status='active'")
                games = cursor.fetchone()[0]
                db_conn.close()

                resp = json.dumps({"status": "alive", "port": server_info["port"], "players": players, "active_games": games})
                peer_conn.sendall(f"{resp}\n".encode())
    except Exception:
        pass
    finally:
        try: peer_conn.close()
        except: pass

def heartbeat_client(peer_host, peer_sync_port):
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(HEARTBEAT_TIMEOUT)
            sock.connect((peer_host, peer_sync_port))
            while True:
                sock.sendall(b"HEARTBEAT\n")
                resp = sock.recv(1024).decode()
                if resp:
                    peer_data = json.loads(resp.strip())
                    with server_info["lock"]:
                        if not server_info["peer_alive"]:
                            print(f"[SYNC] Peer na porta {peer_data.get('port','?')} esta ONLINE")
                        server_info["peer_alive"] = True
                time.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            with server_info["lock"]:
                if server_info["peer_alive"]:
                    print(f"[SYNC] Peer em {peer_host}:{peer_sync_port} esta OFFLINE")
                server_info["peer_alive"] = False
            try: sock.close()
            except: pass
            time.sleep(HEARTBEAT_INTERVAL)

def start_server(port, sync_port=None, peer_host=None, peer_sync_port=None):
    server_info["port"] = port
    server_info["sync_port"] = sync_port
    server_info["peer_host"] = peer_host
    server_info["peer_sync_port"] = peer_sync_port

    init_db()

    threading.Thread(target=matchmaker, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=disconnection_monitor, daemon=True).start()

    if sync_port:
        threading.Thread(target=health_check_server, args=(sync_port,), daemon=True).start()

    if peer_host and peer_sync_port:
        threading.Thread(target=heartbeat_client, args=(peer_host, peer_sync_port), daemon=True).start()

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(('0.0.0.0', port))
    server_sock.listen()

    print("══════════════════════════════════════════════════")
    print(f"JOGO DA FORCA DISTRIBUIDO - Porta {port}")
    if sync_port: print(f"Sync: {sync_port}")
    print("══════════════════════════════════════════════════")

    try:
        while True:
            client_conn, addr = server_sock.accept()
            threading.Thread(target=handle_client, args=(client_conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[SERVER] Encerrando...")
    finally:
        server_sock.close()

if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    sync_port_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None
    peer_host_arg = sys.argv[3] if len(sys.argv) > 3 else None
    peer_sync_arg = int(sys.argv[4]) if len(sys.argv) > 4 else None
    start_server(port_arg, sync_port_arg, peer_host_arg, peer_sync_arg)