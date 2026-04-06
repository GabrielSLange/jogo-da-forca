import socket
import threading
import random
import time
import uuid
import sys
import json
import select
import xmlrpc.client

DB_HOST = "127.0.0.1" 
DB_URL = f"http://{DB_HOST}:8000"

MAX_ERROS = 6
HEARTBEAT_INTERVAL = 3
HEARTBEAT_TIMEOUT = 5
MATCHMAKER_INTERVAL = 1
POLL_INTERVAL = 0.4
DISCONNECT_TIMEOUT = 30

PALAVRAS = ["SISTEMAS", "DISTRIBUIDO", "CONCORRENCIA", "REDUNDANCIA", "SOCKETS", "SERVIDOR", "PROTOCOLO", "REDE", "INTERNET", "FIREWALL", "THREADS"]

server_info = {"port": None, "peer_host": None, "peer_sync_port": None, "sync_port": None, "peer_alive": False, "clients_connected": 0, "games_active": 0, "lock": threading.Lock()}
waiting_clients = {}
waiting_clients_lock = threading.Lock()

def execute_db(query, params=()):
    try:
        proxy = xmlrpc.client.ServerProxy(DB_URL)
        res = proxy.run_query(query, list(params))
        if res["status"] == "ok": return res["data"]
    except Exception: pass
    return []

def fetchone_db(query, params=()):
    res = execute_db(query, params)
    return res[0] if res else None

def transaction_db(queries_and_params):
    try:
        proxy = xmlrpc.client.ServerProxy(DB_URL)
        q_p = [[q, list(p)] for q, p in queries_and_params]
        proxy.run_transaction(q_p)
    except Exception: pass

def notify_waiting_players(new_player_id, new_player_nome):
    with waiting_clients_lock:
        for pid, conn in list(waiting_clients.items()):
            if pid != new_player_id:
                try: safe_send(conn, f"📢 Novo jogador na fila: {new_player_nome}! Pareamento em breve...\n")
                except Exception: pass

def matchmaker():
    while True:
        try:
            waiting = execute_db("SELECT id FROM jogadores WHERE status='waiting' ORDER BY rowid LIMIT 2")
            if waiting and len(waiting) == 2:
                p1_id, p2_id = waiting[0][0], waiting[1][0]
                palavra = random.choice(PALAVRAS)
                oculta = "_" * len(palavra)

                transaction_db([
                    ("INSERT INTO jogos (p1, p2, palavra, oculta, erros, turno, status, tentativas) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (p1_id, p2_id, palavra, oculta, 0, p1_id, 'active', '')),
                    ("UPDATE jogadores SET status='playing' WHERE id IN (?, ?)", (p1_id, p2_id))
                ])
                print(f"[MATCH] Partida criada: {p1_id[:8]}... vs {p2_id[:8]}... | Palavra: {palavra}")
        except Exception as e: pass
        time.sleep(MATCHMAKER_INTERVAL)

def safe_send(conn, data):
    try:
        if isinstance(data, str): data = data.encode('utf-8')
        conn.sendall(data)
        return True
    except Exception: return False

def handle_client(client_conn, addr):
    client_conn.settimeout(5)
    try:
        buf = b""
        while b"\n" not in buf:
            chunk = client_conn.recv(1)
            if not chunk: raise Exception()
            buf += chunk
        data = buf.decode('utf-8').strip()
        if not data.startswith("CONNECT|"): return
        parts = data.split("|", 2)
        if len(parts) == 3: _, player_id, player_nome = parts
        else: return
    except Exception:
        client_conn.close()
        return

    client_conn.settimeout(None)

    with server_info["lock"]: server_info["clients_connected"] += 1
    print(f"[CONN] {addr} conectou — ID: {player_id[:8]}... Nome: {player_nome}")

    row = fetchone_db("SELECT status FROM jogadores WHERE id=?", (player_id,))
    game_id = None
    if row:
        execute_db("UPDATE jogadores SET disconnect_time=NULL WHERE id=?", (player_id,))
        if not safe_send(client_conn, f"Bem-vindo de volta, {player_nome}!\n"): return
            
        game_row = fetchone_db("SELECT id FROM jogos WHERE (p1=? OR p2=?) AND status='active'", (player_id, player_id))
        if game_row:
            game_id = game_row[0]
            execute_db("UPDATE jogadores SET status='playing' WHERE id=?", (player_id,))
            safe_send(client_conn, "Reconectado ao jogo em andamento!\n")
        else:
            execute_db("UPDATE jogadores SET status='waiting' WHERE id=?", (player_id,))
            safe_send(client_conn, "Sua partida anterior ja terminou. Aguardando novo adversario...\n")
            with waiting_clients_lock: waiting_clients[player_id] = client_conn
    else:
        execute_db("INSERT INTO jogadores (id, nome, status, server_port) VALUES (?, ?, ?, ?)", (player_id, player_nome, 'waiting', server_info["port"]))
        with waiting_clients_lock: waiting_clients[player_id] = client_conn
        if not safe_send(client_conn, f"Ola {player_nome}. Aguardando adversario...\n"): return
        notify_waiting_players(player_id, player_nome)

    last_oculta = ""
    last_erros = -1
    last_turno = ""
    last_ui_update = 0
    buffer_in = ""

    try:
        while True:
            if not game_id:
                r = fetchone_db("SELECT id FROM jogos WHERE (p1=? OR p2=?) AND status='active'", (player_id, player_id))
                if r:
                    game_id = r[0]
                    with waiting_clients_lock: waiting_clients.pop(player_id, None)
                    safe_send(client_conn, "Adversario encontrado! O jogo vai comecar.\n")
                    last_oculta = ""
                    last_erros = -1
                    last_turno = ""
                else:
                    now = time.time()
                    if now - last_ui_update > 2:
                        waiting = execute_db("SELECT id FROM jogadores WHERE status='waiting' ORDER BY rowid")
                        pos = 0
                        for i, w in enumerate(waiting):
                            if w[0] == player_id:
                                pos = i + 1
                                break
                        if pos > 0: safe_send(client_conn, f"Aguardando adversario... Voce e o {pos}o na fila.\n")
                        last_ui_update = now

            game = None
            if game_id:
                game = fetchone_db("SELECT p1, p2, palavra, oculta, erros, turno, status, tentativas FROM jogos WHERE id=?", (game_id,))

            if game:
                p1, p2, palavra, oculta, erros, turno, status, tentativas = game
                opponent_id = p2 if player_id == p1 else p1
                
                opp_row = fetchone_db("SELECT status, disconnect_time FROM jogadores WHERE id=?", (opponent_id,))
                opp_is_disconnected = False
                
                if opp_row:
                    opp_status, opp_disc_time = opp_row[0], opp_row[1]
                    if opp_status == 'disconnected':
                        opp_is_disconnected = True
                        if opp_disc_time and (time.time() - opp_disc_time) > DISCONNECT_TIMEOUT:
                            safe_send(client_conn, "O adversario desconectou por mais de 30s. Voce venceu por W.O.!\n")
                            execute_db("UPDATE jogos SET status='finished' WHERE id=?", (game_id,))
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
                        execute_db("UPDATE jogos SET status='finished' WHERE id=?", (game_id,))
                        break

                if status == 'finished':
                    is_last_player = (player_id != turno)
                    if "_" not in oculta:
                        if is_last_player: safe_send(client_conn, f"VITORIA! Voce acertou a ultima letra: {palavra}\n")
                        else: safe_send(client_conn, f"DERROTA! O adversario completou a palavra: {palavra}\n")
                    else:
                        if is_last_player: safe_send(client_conn, f"DERROTA! Voce esgotou as chances. A palavra era: {palavra}\n")
                        else: safe_send(client_conn, f"VITORIA! O adversario foi enforcado. A palavra era: {palavra}\n")
                    break

                if not opp_is_disconnected and status == 'active':
                    if oculta != last_oculta or erros != last_erros:
                        letras_lista = tentativas.split(',') if tentativas else []
                        letras_certas = [l for l in letras_lista if l in palavra]
                        letras_erradas = [l for l in letras_lista if l not in palavra]
                        certas_str = ' '.join(letras_certas) if letras_certas else ''
                        erradas_str = ' '.join(letras_erradas) if letras_erradas else ''

                        partes_corpo = ["cabeca", "tronco", "braco dir.", "braco esq.", "perna dir.", "perna esq."]
                        erros_partes = [partes_corpo[i] for i in range(min(erros, MAX_ERROS))]
                        partes_str = ', '.join(erros_partes) if erros_partes else 'nenhuma'

                        estado = (f"\nPalavra: {' '.join(oculta)} | Erros: {erros}/{MAX_ERROS} ({partes_str}) | Certas: {certas_str} | Erradas: {erradas_str}\n")
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
                                    if letra == chute: nova_oculta[i] = chute
                                nova_oculta_str = "".join(nova_oculta)
                                novo_status = 'finished' if "_" not in nova_oculta_str else 'active'
                                execute_db("UPDATE jogos SET oculta=?, turno=?, status=?, tentativas=? WHERE id=?", (nova_oculta_str, novo_turno, novo_status, novas_tentativas, game_id))
                                safe_send(client_conn, f"Acertou! A letra '{chute}' esta na palavra.\n")
                            else:
                                novos_erros = erros + 1
                                novo_status = 'finished' if novos_erros >= MAX_ERROS else 'active'
                                execute_db("UPDATE jogos SET erros=?, turno=?, status=?, tentativas=? WHERE id=?", (novos_erros, novo_turno, novo_status, novas_tentativas, game_id))
                                parte_perdida = ["cabeca", "tronco", "braco direito", "braco esquerdo", "perna direita", "perna esquerda"]
                                if novos_erros <= MAX_ERROS:
                                    safe_send(client_conn, f"Errou! Perdeu: {parte_perdida[novos_erros-1]}.\n")
    except Exception as e: print(f"[CONN] {addr} — conexao perdida: {e}")
    finally:
        with waiting_clients_lock: waiting_clients.pop(player_id, None)
        execute_db("UPDATE jogadores SET status='disconnected', disconnect_time=? WHERE id=?", (time.time(), player_id))
        try: client_conn.close()
        except: pass
        with server_info["lock"]: server_info["clients_connected"] -= 1
        print(f"[CONN] {addr} desconectou.")

def disconnection_monitor():
    while True:
        try:
            now = time.time()
            deleted = execute_db("SELECT id FROM jogadores WHERE status='disconnected' AND disconnect_time IS NOT NULL AND (? - disconnect_time) > ?", (now, DISCONNECT_TIMEOUT))
            for pid in deleted:
                execute_db("DELETE FROM jogadores WHERE id=?", (pid[0],))
                print(f"[CLEAN] Jogador {pid[0][:8]}... expirou. Removido.")
        except Exception: pass
        time.sleep(2)

def monitor():
    while True:
        time.sleep(15)
        try:
            w_row = fetchone_db("SELECT COUNT(*) FROM jogadores WHERE status='waiting'")
            w = w_row[0] if w_row else 0
            p_row = fetchone_db("SELECT COUNT(*) FROM jogadores WHERE status='playing'")
            p = p_row[0] if p_row else 0
            g_row = fetchone_db("SELECT COUNT(*) FROM jogos WHERE status='active'")
            g = g_row[0] if g_row else 0

            with server_info["lock"]: peer_s = "ONLINE" if server_info["peer_alive"] else "OFFLINE"
            print(f"[MONITOR] Aguardando: {w} | Jogando: {p} | Jogos ativos: {g} | Peer: {peer_s}")
        except Exception: pass

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
            except socket.timeout: continue
            except OSError: break
    except Exception as e: print(f"[SYNC] Erro ao iniciar health check: {e}")

def handle_heartbeat_connection(peer_conn):
    peer_conn.settimeout(HEARTBEAT_TIMEOUT)
    try:
        while True:
            data = peer_conn.recv(1024).decode()
            if not data: break
            if data.strip() == "HEARTBEAT":
                players_row = fetchone_db("SELECT COUNT(*) FROM jogadores")
                players = players_row[0] if players_row else 0
                games_row = fetchone_db("SELECT COUNT(*) FROM jogos WHERE status='active'")
                games = games_row[0] if games_row else 0

                resp = json.dumps({"status": "alive", "port": server_info["port"], "players": players, "active_games": games})
                peer_conn.sendall(f"{resp}\n".encode())
    except Exception: pass
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
                        if not server_info["peer_alive"]: print(f"[SYNC] Peer na porta {peer_data.get('port','?')} esta ONLINE")
                        server_info["peer_alive"] = True
                time.sleep(HEARTBEAT_INTERVAL)
        except Exception as e:
            with server_info["lock"]:
                if server_info["peer_alive"]: print(f"[SYNC] Peer em {peer_host}:{peer_sync_port} esta OFFLINE")
                server_info["peer_alive"] = False
            try: sock.close()
            except: pass
            time.sleep(HEARTBEAT_INTERVAL)

def start_server(port, sync_port=None, peer_host=None, peer_sync_port=None):
    server_info["port"] = port
    server_info["sync_port"] = sync_port
    server_info["peer_host"] = peer_host
    server_info["peer_sync_port"] = peer_sync_port

    threading.Thread(target=matchmaker, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=disconnection_monitor, daemon=True).start()

    if sync_port: threading.Thread(target=health_check_server, args=(sync_port,), daemon=True).start()
    if peer_host and peer_sync_port: threading.Thread(target=heartbeat_client, args=(peer_host, peer_sync_port), daemon=True).start()

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
    except KeyboardInterrupt: print("\n[SERVER] Encerrando...")
    finally: server_sock.close()

if __name__ == "__main__":
    if len(sys.argv) > 5:
        DB_HOST = sys.argv[5]
        DB_URL = f"http://{DB_HOST}:8000"

    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    sync_port_arg = int(sys.argv[2]) if len(sys.argv) > 2 else None
    peer_host_arg = sys.argv[3] if len(sys.argv) > 3 else None
    peer_sync_arg = int(sys.argv[4]) if len(sys.argv) > 4 else None
    start_server(port_arg, sync_port_arg, peer_host_arg, peer_sync_arg)