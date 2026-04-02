import socket
import threading
import time
import customtkinter as ctk
import uuid

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

BG_DARK = "#1a1a2e"
BG_CANVAS = "#16213e"
COLOR_ACCENT = "#0f3460"
COLOR_WIN = "#00b894"
COLOR_LOSE = "#d63031"
COLOR_WAIT = "#fdcb6e"
COLOR_WHITE = "#e8e8e8"
COLOR_GRAY = "#636e72"
HANGMAN_COLOR = "#dfe6e9"
ROPE_COLOR = "#fab1a0"

PING_INTERVAL = 1

class ForcaClient(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Jogo da Forca Distribuído")
        self.geometry("650x800")
        self.resizable(True, True)
        self.configure(fg_color=BG_DARK)
        self.sock = None
        self.connected = False
        self.game_over = False
        self.my_turn = False
        self.in_game = False
        self.reconnecting = False
        self.latency_ms = -1
        self._send_time = None
        self.user_id = str(uuid.uuid4())
        
        self.servers = []

        self.header = ctk.CTkLabel(self, text="🎮 Jogo da Forca Distribuído", font=("Segoe UI", 22, "bold"), text_color=COLOR_WHITE)
        self.header.pack(pady=(15, 5))

        self.conn_frame = ctk.CTkFrame(self, fg_color=COLOR_ACCENT, corner_radius=12)
        self.conn_frame.pack(pady=8, padx=20, fill="x")

        row0 = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        row0.pack(pady=(10, 5), padx=15, fill="x")
        ctk.CTkLabel(row0, text="Seu Nome:", font=("Segoe UI", 12), text_color=COLOR_GRAY).pack(side="left", padx=(0, 5))
        self.name_entry = ctk.CTkEntry(row0, placeholder_text="Nome do Jogador", width=180)
        self.name_entry.pack(side="left", padx=3)
        self.name_entry.insert(0, f"Jogador_{self.user_id[:4]}")

        row1 = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        row1.pack(pady=(5, 5), padx=15, fill="x")
        ctk.CTkLabel(row1, text="Servidor 1:", font=("Segoe UI", 12), text_color=COLOR_GRAY).pack(side="left", padx=(0, 5))
        self.ip_entry = ctk.CTkEntry(row1, placeholder_text="IP", width=120)
        self.ip_entry.insert(0, "127.0.0.1")
        self.ip_entry.pack(side="left", padx=3)
        self.port_entry = ctk.CTkEntry(row1, placeholder_text="Porta", width=60)
        self.port_entry.insert(0, "5000")
        self.port_entry.pack(side="left", padx=3)

        row2 = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        row2.pack(pady=(0, 5), padx=15, fill="x")
        ctk.CTkLabel(row2, text="Servidor 2:", font=("Segoe UI", 12), text_color=COLOR_GRAY).pack(side="left", padx=(0, 5))
        self.ip2_entry = ctk.CTkEntry(row2, placeholder_text="IP sec.", width=120)
        self.ip2_entry.pack(side="left", padx=3)
        self.port2_entry = ctk.CTkEntry(row2, placeholder_text="Porta", width=60)
        self.port2_entry.pack(side="left", padx=3)

        row3 = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        row3.pack(pady=(0, 10), padx=15, fill="x")
        self.connect_btn = ctk.CTkButton(row3, text="🔌 Conectar", command=self.connect_server, width=140, height=36, corner_radius=8, font=("Segoe UI", 13, "bold"))
        self.connect_btn.pack(side="left", padx=3)

        self.latency_label = ctk.CTkLabel(row3, text="PING: -- ms", font=("Segoe UI", 14, "bold"), text_color=COLOR_GRAY)
        self.latency_label.pack(side="right", padx=10)

        self.canvas = ctk.CTkCanvas(self, width=220, height=260, bg=BG_CANVAS, highlightthickness=0)
        self.canvas.pack(pady=10)
        self.draw_hangman(0)

        self.word_label = ctk.CTkLabel(self, text="_ _ _ _ _", font=("Courier New", 34, "bold"), text_color=COLOR_WHITE)
        self.word_label.pack(pady=8)

        self.status_label = ctk.CTkLabel(self, text="Desconectado", font=("Segoe UI", 15), text_color=COLOR_WAIT, wraplength=550)
        self.status_label.pack(pady=5)

        self.body_label = ctk.CTkLabel(self, text="", font=("Segoe UI", 12), text_color=COLOR_LOSE, wraplength=500)
        self.body_label.pack(pady=2)

        self.tried_label = ctk.CTkLabel(self, text="", font=("Segoe UI", 13), text_color=COLOR_GRAY)
        self.tried_label.pack(pady=3)

        self.input_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.input_frame.pack(pady=12)

        self.letter_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Letra", width=80, height=40, font=("Courier New", 18, "bold"), justify="center")
        self.letter_entry.pack(side="left", padx=5)
        self.letter_entry.configure(state="disabled")
        self.letter_entry.bind("<Return>", lambda e: self.send_letter())

        self.send_btn = ctk.CTkButton(self.input_frame, text="📨 Enviar", command=self.send_letter, width=120, height=40, corner_radius=8, font=("Segoe UI", 13, "bold"))
        self.send_btn.pack(side="left", padx=5)
        self.send_btn.configure(state="disabled")

        self.new_game_btn = ctk.CTkButton(self, text="🔄 Novo Jogo", command=self.new_game, width=160, height=40, corner_radius=8, font=("Segoe UI", 14, "bold"), fg_color=COLOR_WIN, hover_color="#00cec9")

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def draw_hangman(self, errors):
        self.canvas.delete("all")
        self.canvas.create_line(10, 250, 210, 250, fill=HANGMAN_COLOR, width=3)
        self.canvas.create_line(50, 250, 50, 20, fill=HANGMAN_COLOR, width=3)
        self.canvas.create_line(50, 20, 140, 20, fill=HANGMAN_COLOR, width=3)
        self.canvas.create_line(140, 20, 140, 50, fill=ROPE_COLOR, width=2)
        if errors >= 1:
            self.canvas.create_oval(120, 50, 160, 90, outline=HANGMAN_COLOR, width=3)
            if errors >= 6:
                self.canvas.create_line(130, 62, 136, 68, fill=COLOR_LOSE, width=2)
                self.canvas.create_line(136, 62, 130, 68, fill=COLOR_LOSE, width=2)
                self.canvas.create_line(144, 62, 150, 68, fill=COLOR_LOSE, width=2)
                self.canvas.create_line(150, 62, 144, 68, fill=COLOR_LOSE, width=2)
            else:
                self.canvas.create_oval(131, 63, 137, 69, fill=HANGMAN_COLOR, outline=HANGMAN_COLOR)
                self.canvas.create_oval(143, 63, 149, 69, fill=HANGMAN_COLOR, outline=HANGMAN_COLOR)
        if errors >= 2: self.canvas.create_line(140, 90, 140, 170, fill=HANGMAN_COLOR, width=3)
        if errors >= 3: self.canvas.create_line(140, 110, 170, 145, fill=HANGMAN_COLOR, width=3)
        if errors >= 4: self.canvas.create_line(140, 110, 110, 145, fill=HANGMAN_COLOR, width=3)
        if errors >= 5: self.canvas.create_line(140, 170, 170, 215, fill=HANGMAN_COLOR, width=3)
        if errors >= 6: self.canvas.create_line(140, 170, 110, 215, fill=HANGMAN_COLOR, width=3)

    def connect_server(self):
        ip1 = self.ip_entry.get().strip() or "127.0.0.1"
        port1 = self.port_entry.get().strip() or "5000"
        ip2 = self.ip2_entry.get().strip()
        port2 = self.port2_entry.get().strip()

        self.servers = [(ip1, int(port1))]
        if ip2 and port2: self.servers.append((ip2, int(port2)))
        
        self.connect_btn.configure(state="disabled")
        self.name_entry.configure(state="disabled")
        self.try_connect(0)

    def try_connect(self, server_index):
        if server_index >= len(self.servers):
            if self.reconnecting and not self.game_over:
                self.after(2000, lambda: self.try_connect(0)) # Loop ate 30s
            else:
                self.status_label.configure(text="Falha ao conectar aos servidores.", text_color=COLOR_LOSE)
                self.connect_btn.configure(state="normal")
                self.name_entry.configure(state="normal")
            return

        ip, port = self.servers[server_index]
        texto_status = "Reconectando a..." if self.reconnecting else "Conectando a..."
        self.status_label.configure(text=f"{texto_status} {ip}:{port}...", text_color=COLOR_WAIT)

        def attempt():
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(5)
                self.sock.connect((ip, port))
                self.sock.settimeout(None)
                self.connected = True
                self.reconnecting = False
                
                # Identificacao de reconexao:
                nome = self.name_entry.get().strip() or "Jogador"
                self.sock.sendall(f"CONNECT|{self.user_id}|{nome}\n".encode())

                self.after(0, lambda: self.on_connected(ip, port))
                self.receive_messages()
            except Exception:
                self.after(0, lambda: self.try_connect(server_index + 1))

        threading.Thread(target=attempt, daemon=True).start()

    def on_connected(self, ip, port):
        self.status_label.configure(text=f"Conectado a {ip}:{port}!", text_color=COLOR_WIN)
        threading.Thread(target=self.ping_loop, daemon=True).start()

    def receive_messages(self):
        buffer = ""
        while self.connected:
            try:
                data = self.sock.recv(4096).decode('utf-8')
                if not data: break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        self.after(0, self.process_message, line.strip())
            except Exception:
                self.connected = False
                self.after(0, self.on_disconnect)
                break
        
        # fallback se loop fechar graciosamente mas sem avisar a GUI
        if not self.game_over and not self.reconnecting:
            self.after(0, self.on_disconnect)

    def on_disconnect(self):
        self.connected = False
        if self.game_over: return
        self.status_label.configure(text="Conexao perdida! Tentando reconectar (ate 30s)...", text_color=COLOR_LOSE)
        self.letter_entry.configure(state="disabled")
        self.send_btn.configure(state="disabled")
        self.reconnecting = True
        self.try_connect(0)

    def process_message(self, message):
        if message == "PONG":
            if hasattr(self, '_ping_time'):
                rtt = (time.time() - self._ping_time) * 1000
                self.latency_ms = rtt
                color = COLOR_WIN if rtt < 50 else (COLOR_WAIT if rtt < 150 else COLOR_LOSE)
                self.latency_label.configure(text=f"PING: {rtt:.0f} ms", text_color=color)
            return

        if "Palavra:" in message and "Erros:" in message:
            self.parse_game_state(message)
            return

        if message.startswith("VITORIA"):
            self.game_over = True
            self.status_label.configure(text=message, text_color=COLOR_WIN)
            self.letter_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.show_new_game_btn()
            return

        if message.startswith("DERROTA"):
            self.game_over = True
            self.status_label.configure(text=message, text_color=COLOR_LOSE)
            self.draw_hangman(6)
            self.letter_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.show_new_game_btn()
            return

        if "abandonou" in message.lower() or "venceu por w.o" in message.lower() or "desconectou por mais" in message.lower():
            if "Aguardando retorno" not in message:
                self.game_over = True
                self.status_label.configure(text=message, text_color=COLOR_WIN)
                self.letter_entry.configure(state="disabled")
                self.send_btn.configure(state="disabled")
                self.show_new_game_btn()
                return
        elif "Aguardando retorno" in message:
             self.status_label.configure(text="⚠️ " + message, text_color=COLOR_WAIT)
             return

        if "Sua vez" in message:
            self.status_label.configure(text="🎯 E a sua vez!", text_color=COLOR_WIN)
            self.letter_entry.configure(state="normal")
            self.send_btn.configure(state="normal")
            self.letter_entry.focus()
            self.my_turn = True
            self.in_game = True
            return

        if "Aguardando" in message:
            self.status_label.configure(text="⏳ " + message, text_color=COLOR_WAIT)
            self.letter_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.my_turn = False
            return

        if "Acertou" in message:
            self.status_label.configure(text="✅ " + message, text_color=COLOR_WIN)
            return
        if "Errou" in message:
            self.status_label.configure(text="❌ " + message, text_color=COLOR_LOSE)
            return
        if "ja foi tentada" in message or "invalida" in message.lower():
            self.status_label.configure(text="⚠️ " + message, text_color=COLOR_WAIT)
            self.letter_entry.configure(state="normal")
            self.send_btn.configure(state="normal")
            return

        self.status_label.configure(text=message, text_color=COLOR_WHITE)

    def parse_game_state(self, message):
        try:
            partes = message.split("|")
            if len(partes) < 2: return
            self.word_label.configure(text=partes[0].replace("Palavra:", "").strip())
            erros_str = partes[1].replace("Erros:", "").strip()
            erros_num = int(erros_str.split("/")[0].strip())
            self.draw_hangman(erros_num)
            if "(" in erros_str and ")" in erros_str:
                body_parts = erros_str[erros_str.index("(")+1:erros_str.index(")")].strip()
                self.body_label.configure(text=f"💀 Partes perdidas: {body_parts}" if body_parts != "nenhuma" else "")
            
            if len(partes) >= 3:
                letras = partes[2].replace("Tentativas:", "").strip()
                self.tried_label.configure(text=f"Letras tentadas: {'  '.join(letras.split())}" if letras else "")
        except Exception:
            pass

    def send_letter(self):
        letter = self.letter_entry.get().strip().upper()
        if letter and self.sock and self.connected:
            try:
                self.sock.sendall(f"LETRA|{letter}\n".encode('utf-8'))
                self.letter_entry.delete(0, 'end')
                self.letter_entry.configure(state="disabled")
                self.send_btn.configure(state="disabled")
                self.my_turn = False
            except Exception as e:
                self.status_label.configure(text=f"Erro ao enviar: {e}", text_color=COLOR_LOSE)

    def ping_loop(self):
        while self.connected:
            try:
                self._ping_time = time.time()
                self.sock.sendall(b"PING\n")
            except Exception:
                break
            time.sleep(PING_INTERVAL)

    def show_new_game_btn(self):
        self.new_game_btn.pack(pady=10)

    def new_game(self):
        if self.sock:
            try: self.sock.close()
            except: pass
        self.sock = None
        self.connected = False
        self.game_over = False
        self.my_turn = False
        self.in_game = False
        self.reconnecting = False
        self.latency_ms = -1
        self.user_id = str(uuid.uuid4())
        self.name_entry.configure(state="normal")
        self.name_entry.delete(0, 'end')
        self.name_entry.insert(0, f"Jogador_{self.user_id[:4]}")

        self.new_game_btn.pack_forget()
        self.word_label.configure(text="_ _ _ _ _")
        self.draw_hangman(0)
        self.status_label.configure(text="Desconectado", text_color=COLOR_WAIT)
        self.tried_label.configure(text="")
        self.body_label.configure(text="")
        self.latency_label.configure(text="PING: -- ms", text_color=COLOR_GRAY)
        self.letter_entry.configure(state="disabled")
        self.send_btn.configure(state="disabled")
        self.connect_btn.configure(state="normal")

    def on_closing(self):
        self.connected = False
        if self.sock:
            try: self.sock.close()
            except: pass
        self.destroy()

if __name__ == "__main__":
    app = ForcaClient()
    app.mainloop()