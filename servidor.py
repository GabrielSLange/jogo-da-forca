import socket
import threading
import sqlite3
import random
import time
import uuid
import sys

PALAVRAS = ["SISTEMAS", "DISTRIBUIDO", "CONCORRENCIA", "REDUNDANCIA", "SOCKETS"]

def init_db():
    conn = sqlite3.connect('forca.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jogadores (id TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS jogos 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, p1 TEXT, p2 TEXT, 
                 palavra TEXT, oculta TEXT, erros INTEGER, turno TEXT, status TEXT)''')
    conn.commit()
    conn.close()

def matchmaker():
    while True:
        try:
            conn = sqlite3.connect('forca.db', timeout=5)
            c = conn.cursor()
            c.execute("SELECT id FROM jogadores WHERE status='waiting' ORDER BY rowid LIMIT 2")
            waiting = c.fetchall()
            
            if len(waiting) == 2:
                p1 = waiting[0][0]
                p2 = waiting[1][0]
                palavra = random.choice(PALAVRAS)
                oculta = "_" * len(palavra)
                
                c.execute("INSERT INTO jogos (p1, p2, palavra, oculta, erros, turno, status) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                          (p1, p2, palavra, oculta, 0, p1, 'active'))
                c.execute("UPDATE jogadores SET status='playing' WHERE id IN (?, ?)", (p1, p2))
                conn.commit()
        except sqlite3.Error:
            pass
        finally:
            conn.close()
            
        time.sleep(1)

def handle_client(conn, addr):
    player_id = str(uuid.uuid4())
    db = sqlite3.connect('forca.db', timeout=5)
    c = db.cursor()
    c.execute("INSERT INTO jogadores (id, status) VALUES (?, ?)", (player_id, 'waiting'))
    db.commit()
    
    conn.sendall(b"Aguardando adversario...\n")
    
    game_id = None
    while not game_id:
        c.execute("SELECT id FROM jogos WHERE (p1=? OR p2=?) AND status='active'", (player_id, player_id))
        row = c.fetchone()
        if row:
            game_id = row[0]
            break
        time.sleep(1)
        
    conn.sendall(b"Adversario encontrado! O jogo vai comecar.\n")
    
    last_oculta = ""
    last_erros = -1
    last_turno = ""
    
    while True:
        try:
            c.execute("SELECT p1, p2, palavra, oculta, erros, turno, status FROM jogos WHERE id=?", (game_id,))
            game = c.fetchone()
            
            if not game:
                break
                
            p1, p2, palavra, oculta, erros, turno, status = game
            
            if oculta != last_oculta or erros != last_erros:
                estado = f"\nPalavra: {' '.join(oculta)} | Erros: {erros}/6\n"
                conn.sendall(estado.encode())
                last_oculta = oculta
                last_erros = erros
                last_turno = "" 
                
            if status == 'finished':
                if "_" not in oculta:
                    conn.sendall(f"Vitoria! A palavra era {palavra}\n".encode())
                else:
                    conn.sendall(f"Derrota! A palavra era {palavra}\n".encode())
                break
                
            if turno == player_id and last_turno != player_id:
                conn.sendall(b"Sua vez! Digite uma letra: \n")
                last_turno = player_id 
                
                chute = conn.recv(1024).decode().strip().upper()
                if not chute: 
                    break
                
                if len(chute) == 1 and chute.isalpha():
                    nova_oculta = list(oculta)
                    if chute in palavra:
                        for i, letra in enumerate(palavra):
                            if letra == chute:
                                nova_oculta[i] = chute
                        nova_oculta_str = "".join(nova_oculta)
                        novo_turno = p2 if player_id == p1 else p1
                        novo_status = 'finished' if "_" not in nova_oculta_str else 'active'
                        c.execute("UPDATE jogos SET oculta=?, turno=?, status=? WHERE id=?", 
                                  (nova_oculta_str, novo_turno, novo_status, game_id))
                    else:
                        erros += 1
                        novo_turno = p2 if player_id == p1 else p1
                        novo_status = 'finished' if erros >= 6 else 'active'
                        c.execute("UPDATE jogos SET erros=?, turno=?, status=? WHERE id=?", 
                                  (erros, novo_turno, novo_status, game_id))
                    db.commit()
            elif turno != player_id and last_turno != turno:
                conn.sendall(b"Aguardando o turno do adversario...\n")
                last_turno = turno
                
        except (sqlite3.Error, ConnectionResetError, BrokenPipeError):
            break
            
        time.sleep(0.5)
            
    db.close()
    conn.close()

def start_server(port):
    init_db()
    threading.Thread(target=matchmaker, daemon=True).start()
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('0.0.0.0', port))
    server.listen()
    
    print(f"Servidor rodando na porta {port}")
    
    while True:
        try:
            conn, addr = server.accept()
            print(f"Nova conexao: {addr}")
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            break

if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    start_server(port_arg)