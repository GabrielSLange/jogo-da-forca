import socket
import threading
import time
import customtkinter as ctk

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ─────────────────────────────────────────────────────────────
# Cores do tema
# ─────────────────────────────────────────────────────────────
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

PING_INTERVAL = 5  # segundos entre pings de latência


class ForcaClient(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Jogo da Forca Distribuído")
        self.geometry("650x750")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)
        self.sock = None
        self.connected = False
        self.game_over = False
        self.my_turn = False
        self.in_game = False
        self.latency_ms = -1
        self._send_time = None

        # Servidores (primário + secundário)
        self.servers = []

        # ─── Header ───
        self.header = ctk.CTkLabel(
            self, text="🎮 Jogo da Forca Distribuído",
            font=("Segoe UI", 22, "bold"), text_color=COLOR_WHITE
        )
        self.header.pack(pady=(15, 5))

        # ─── Frame de conexão ───
        self.conn_frame = ctk.CTkFrame(self, fg_color=COLOR_ACCENT, corner_radius=12)
        self.conn_frame.pack(pady=8, padx=20, fill="x")

        row1 = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        row1.pack(pady=(10, 5), padx=15, fill="x")

        ctk.CTkLabel(row1, text="Servidor 1:", font=("Segoe UI", 12),
                     text_color=COLOR_GRAY).pack(side="left", padx=(0, 5))
        self.ip_entry = ctk.CTkEntry(row1, placeholder_text="IP (ex: 127.0.0.1)", width=140)
        self.ip_entry.pack(side="left", padx=3)
        self.port_entry = ctk.CTkEntry(row1, placeholder_text="Porta", width=80)
        self.port_entry.pack(side="left", padx=3)

        row2 = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        row2.pack(pady=(0, 5), padx=15, fill="x")

        ctk.CTkLabel(row2, text="Servidor 2:", font=("Segoe UI", 12),
                     text_color=COLOR_GRAY).pack(side="left", padx=(0, 5))
        self.ip2_entry = ctk.CTkEntry(row2, placeholder_text="IP backup", width=140)
        self.ip2_entry.pack(side="left", padx=3)
        self.port2_entry = ctk.CTkEntry(row2, placeholder_text="Porta", width=80)
        self.port2_entry.pack(side="left", padx=3)

        row3 = ctk.CTkFrame(self.conn_frame, fg_color="transparent")
        row3.pack(pady=(0, 10), padx=15, fill="x")

        self.connect_btn = ctk.CTkButton(
            row3, text="🔌 Conectar", command=self.connect_server,
            width=140, height=36, corner_radius=8,
            font=("Segoe UI", 13, "bold")
        )
        self.connect_btn.pack(side="left", padx=3)

        self.latency_label = ctk.CTkLabel(
            row3, text="", font=("Segoe UI", 11), text_color=COLOR_GRAY
        )
        self.latency_label.pack(side="right", padx=10)

        # ─── Canvas da forca ───
        self.canvas = ctk.CTkCanvas(
            self, width=220, height=260,
            bg=BG_CANVAS, highlightthickness=0
        )
        self.canvas.pack(pady=10)
        self.draw_hangman(0)

        # ─── Palavra ───
        self.word_label = ctk.CTkLabel(
            self, text="_ _ _ _ _",
            font=("Courier New", 34, "bold"), text_color=COLOR_WHITE
        )
        self.word_label.pack(pady=8)

        # ─── Status ───
        self.status_label = ctk.CTkLabel(
            self, text="Desconectado",
            font=("Segoe UI", 15), text_color=COLOR_WAIT,
            wraplength=550
        )
        self.status_label.pack(pady=5)

        # ─── Partes do corpo ───
        self.body_label = ctk.CTkLabel(
            self, text="", font=("Segoe UI", 12),
            text_color=COLOR_LOSE, wraplength=500
        )
        self.body_label.pack(pady=2)

        # ─── Letras tentadas ───
        self.tried_label = ctk.CTkLabel(
            self, text="", font=("Segoe UI", 13),
            text_color=COLOR_GRAY
        )
        self.tried_label.pack(pady=3)

        # ─── Frame de entrada ───
        self.input_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.input_frame.pack(pady=12)

        self.letter_entry = ctk.CTkEntry(
            self.input_frame, placeholder_text="Letra",
            width=80, height=40, font=("Courier New", 18, "bold"),
            justify="center"
        )
        self.letter_entry.pack(side="left", padx=5)
        self.letter_entry.configure(state="disabled")
        self.letter_entry.bind("<Return>", lambda e: self.send_letter())

        self.send_btn = ctk.CTkButton(
            self.input_frame, text="📨 Enviar",
            command=self.send_letter, width=120, height=40,
            corner_radius=8, font=("Segoe UI", 13, "bold")
        )
        self.send_btn.pack(side="left", padx=5)
        self.send_btn.configure(state="disabled")

        # ─── Botão Novo Jogo (oculto inicialmente) ───
        self.new_game_btn = ctk.CTkButton(
            self, text="🔄 Novo Jogo", command=self.new_game,
            width=160, height=40, corner_radius=8,
            font=("Segoe UI", 14, "bold"),
            fg_color=COLOR_WIN, hover_color="#00cec9"
        )
        # Não faz pack até fim do jogo

        # Handler para fechar janela
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ─────────────────────────────────────────────────────────
    # Desenho da forca
    # ─────────────────────────────────────────────────────────

    def draw_hangman(self, errors):
        self.canvas.delete("all")
        # Base
        self.canvas.create_line(10, 250, 210, 250, fill=HANGMAN_COLOR, width=3)
        # Poste vertical
        self.canvas.create_line(50, 250, 50, 20, fill=HANGMAN_COLOR, width=3)
        # Poste horizontal
        self.canvas.create_line(50, 20, 140, 20, fill=HANGMAN_COLOR, width=3)
        # Corda
        self.canvas.create_line(140, 20, 140, 50, fill=ROPE_COLOR, width=2)

        # Cabeça
        if errors >= 1:
            self.canvas.create_oval(120, 50, 160, 90, outline=HANGMAN_COLOR, width=3)
            # Olhos
            if errors >= 6:
                # X eyes quando morre
                self.canvas.create_line(130, 62, 136, 68, fill=COLOR_LOSE, width=2)
                self.canvas.create_line(136, 62, 130, 68, fill=COLOR_LOSE, width=2)
                self.canvas.create_line(144, 62, 150, 68, fill=COLOR_LOSE, width=2)
                self.canvas.create_line(150, 62, 144, 68, fill=COLOR_LOSE, width=2)
            else:
                self.canvas.create_oval(131, 63, 137, 69, fill=HANGMAN_COLOR, outline=HANGMAN_COLOR)
                self.canvas.create_oval(143, 63, 149, 69, fill=HANGMAN_COLOR, outline=HANGMAN_COLOR)
        # Tronco
        if errors >= 2:
            self.canvas.create_line(140, 90, 140, 170, fill=HANGMAN_COLOR, width=3)
        # Braço direito
        if errors >= 3:
            self.canvas.create_line(140, 110, 170, 145, fill=HANGMAN_COLOR, width=3)
        # Braço esquerdo
        if errors >= 4:
            self.canvas.create_line(140, 110, 110, 145, fill=HANGMAN_COLOR, width=3)
        # Perna direita
        if errors >= 5:
            self.canvas.create_line(140, 170, 170, 215, fill=HANGMAN_COLOR, width=3)
        # Perna esquerda
        if errors >= 6:
            self.canvas.create_line(140, 170, 110, 215, fill=HANGMAN_COLOR, width=3)

    # ─────────────────────────────────────────────────────────
    # Conexão
    # ─────────────────────────────────────────────────────────

    def connect_server(self):
        """Tenta conectar ao servidor primário, depois ao secundário."""
        ip1 = self.ip_entry.get().strip() or "127.0.0.1"
        port1 = self.port_entry.get().strip() or "5000"
        ip2 = self.ip2_entry.get().strip()
        port2 = self.port2_entry.get().strip()

        self.servers = [(ip1, int(port1))]
        if ip2 and port2:
            self.servers.append((ip2, int(port2)))

        self.try_connect(0)

    def try_connect(self, server_index):
        """Tenta conectar ao servidor do índice dado."""
        if server_index >= len(self.servers):
            self.status_label.configure(
                text="Falha ao conectar em todos os servidores.",
                text_color=COLOR_LOSE
            )
            self.connect_btn.configure(state="normal")
            return

        ip, port = self.servers[server_index]
        self.status_label.configure(
            text=f"Conectando a {ip}:{port}...",
            text_color=COLOR_WAIT
        )

        def attempt():
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(5)
                self.sock.connect((ip, port))
                self.sock.settimeout(None)
                self.connected = True
                self.game_over = False

                self.after(0, lambda: self.on_connected(ip, port))
                self.receive_messages()
            except (ConnectionRefusedError, socket.timeout, OSError) as e:
                self.after(0, lambda: self.status_label.configure(
                    text=f"Servidor {ip}:{port} indisponivel. Tentando proximo...",
                    text_color=COLOR_WAIT
                ))
                time.sleep(1)
                self.after(0, lambda: self.try_connect(server_index + 1))

        threading.Thread(target=attempt, daemon=True).start()
        self.connect_btn.configure(state="disabled")
        self.ip_entry.configure(state="disabled")
        self.port_entry.configure(state="disabled")
        self.ip2_entry.configure(state="disabled")
        self.port2_entry.configure(state="disabled")

    def on_connected(self, ip, port):
        self.status_label.configure(
            text=f"Conectado a {ip}:{port}! Aguardando adversário...",
            text_color=COLOR_WIN
        )
        # Iniciar medição de latência
        threading.Thread(target=self.ping_loop, daemon=True).start()

    # ─────────────────────────────────────────────────────────
    # Receber mensagens
    # ─────────────────────────────────────────────────────────

    def receive_messages(self):
        buffer = ""
        while self.connected:
            try:
                data = self.sock.recv(4096).decode('utf-8')
                if not data:
                    break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self.after(0, self.process_message, line)
            except (ConnectionError, OSError):
                self.connected = False
                self.after(0, self.on_disconnect)
                break

    def on_disconnect(self):
        """Chamado quando a conexão é perdida."""
        if self.game_over:
            return
        self.status_label.configure(
            text="Conexao perdida com o servidor.",
            text_color=COLOR_LOSE
        )
        self.letter_entry.configure(state="disabled")
        self.send_btn.configure(state="disabled")
        self.show_new_game_btn()

    # ─────────────────────────────────────────────────────────
    # Processar mensagens
    # ─────────────────────────────────────────────────────────

    def process_message(self, message):
        """Processa uma mensagem recebida do servidor."""

        # PONG da latência
        if message == "PONG":
            if hasattr(self, '_ping_time'):
                rtt = (time.time() - self._ping_time) * 1000
                self.latency_ms = rtt
                color = COLOR_WIN if rtt < 50 else (COLOR_WAIT if rtt < 150 else COLOR_LOSE)
                self.latency_label.configure(
                    text=f"📶 {rtt:.0f}ms",
                    text_color=color
                )
            return

        # Estado do jogo: Palavra: ... | Erros: .../6 | Tentativas: ...
        if "Palavra:" in message and "Erros:" in message:
            self.parse_game_state(message)
            return

        # Vitória
        if message.startswith("VITORIA"):
            self.game_over = True
            self.status_label.configure(text=message, text_color=COLOR_WIN)
            self.letter_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.show_new_game_btn()
            return

        # Derrota
        if message.startswith("DERROTA"):
            self.game_over = True
            self.status_label.configure(text=message, text_color=COLOR_LOSE)
            self.draw_hangman(6)
            self.letter_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.show_new_game_btn()
            return

        # Adversário desconectou
        if "adversario desconectou" in message.lower():
            self.game_over = True
            self.status_label.configure(text=message, text_color=COLOR_WIN)
            self.letter_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.show_new_game_btn()
            return

        # Sua vez
        if "Sua vez" in message:
            self.status_label.configure(text="🎯 É a sua vez!", text_color=COLOR_WIN)
            self.letter_entry.configure(state="normal")
            self.send_btn.configure(state="normal")
            self.letter_entry.focus()
            self.my_turn = True
            self.in_game = True
            # Medir latência do tempo de resposta
            if self._send_time:
                rtt = (time.time() - self._send_time) * 1000
                self._send_time = None
                self.latency_ms = rtt
                color = COLOR_WIN if rtt < 100 else (COLOR_WAIT if rtt < 300 else COLOR_LOSE)
                self.latency_label.configure(text=f"📡 {rtt:.0f}ms", text_color=color)
            return

        # Aguardando adversário
        if "Aguardando" in message:
            self.status_label.configure(text="⏳ " + message, text_color=COLOR_WAIT)
            self.letter_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self.my_turn = False
            if "adversario" in message.lower() and "turno" in message.lower():
                self.in_game = True
            return

        # Acertou/Errou
        if "Acertou" in message:
            self.status_label.configure(text="✅ " + message, text_color=COLOR_WIN)
            return
        if "Errou" in message:
            self.status_label.configure(text="❌ " + message, text_color=COLOR_LOSE)
            return

        # Letra já tentada
        if "ja foi tentada" in message:
            self.status_label.configure(text="⚠️ " + message, text_color=COLOR_WAIT)
            self.letter_entry.configure(state="normal")
            self.send_btn.configure(state="normal")
            return

        # Entrada inválida
        if "invalida" in message.lower():
            self.status_label.configure(text="⚠️ " + message, text_color=COLOR_WAIT)
            self.letter_entry.configure(state="normal")
            self.send_btn.configure(state="normal")
            return

        # Outras mensagens
        self.status_label.configure(text=message, text_color=COLOR_WHITE)

    def parse_game_state(self, message):
        """Parseia a string de estado do jogo."""
        try:
            partes = message.split("|")
            if len(partes) < 2:
                return

            # Palavra
            palavra_str = partes[0].replace("Palavra:", "").strip()
            self.word_label.configure(text=palavra_str)

            # Erros
            erros_parte = partes[1].strip()
            # Formato: "Erros: 2/6 (cabeca, tronco)"
            erros_num_str = erros_parte.replace("Erros:", "").strip()
            erros_num = int(erros_num_str.split("/")[0].strip())
            self.draw_hangman(erros_num)

            # Partes do corpo perdidas
            if "(" in erros_parte and ")" in erros_parte:
                body_parts = erros_parte[erros_parte.index("(") + 1:erros_parte.index(")")]
                if body_parts != "nenhuma":
                    self.body_label.configure(text=f"💀 Partes perdidas: {body_parts}")
                else:
                    self.body_label.configure(text="")
            else:
                self.body_label.configure(text="")

            # Tentativas
            if len(partes) >= 3:
                tentativas_str = partes[2].replace("Tentativas:", "").strip()
                if tentativas_str:
                    letras = tentativas_str.split()
                    display = "  ".join(letras)
                    self.tried_label.configure(text=f"Letras tentadas: {display}")
                else:
                    self.tried_label.configure(text="")

        except (ValueError, IndexError):
            pass

    # ─────────────────────────────────────────────────────────
    # Enviar letra
    # ─────────────────────────────────────────────────────────

    def send_letter(self):
        letter = self.letter_entry.get().strip()
        if letter and self.sock and self.connected:
            try:
                self._send_time = time.time()
                self.sock.sendall(letter.encode('utf-8'))
                self.letter_entry.delete(0, 'end')
                self.letter_entry.configure(state="disabled")
                self.send_btn.configure(state="disabled")
                self.my_turn = False
            except (ConnectionError, OSError) as e:
                self.status_label.configure(
                    text=f"Erro ao enviar: {e}",
                    text_color=COLOR_LOSE
                )

    # ─────────────────────────────────────────────────────────
    # Latência (PING/PONG)
    # ─────────────────────────────────────────────────────────

    def ping_loop(self):
        """Envia PINGs periódicos para medir latência (apenas quando não é a vez do jogador)."""
        while self.connected and not self.game_over:
            if not self.my_turn and not self.in_game:
                # Só envia PING durante a fase de espera por matchmaking
                try:
                    self._ping_time = time.time()
                    self.sock.sendall(b"PING")
                except (ConnectionError, OSError):
                    break
            elif not self.my_turn and self.in_game:
                # Durante o turno do oponente, também podemos medir
                try:
                    self._ping_time = time.time()
                    self.sock.sendall(b"PING")
                except (ConnectionError, OSError):
                    break
            time.sleep(PING_INTERVAL)

    # ─────────────────────────────────────────────────────────
    # Novo Jogo
    # ─────────────────────────────────────────────────────────

    def show_new_game_btn(self):
        self.new_game_btn.pack(pady=10)

    def new_game(self):
        """Reseta tudo e reconecta."""
        # Fechar socket antigo
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

        self.connected = False
        self.game_over = False
        self.my_turn = False
        self.in_game = False
        self.latency_ms = -1
        self._send_time = None

        # Resetar GUI
        self.new_game_btn.pack_forget()
        self.word_label.configure(text="_ _ _ _ _")
        self.draw_hangman(0)
        self.status_label.configure(text="Desconectado", text_color=COLOR_WAIT)
        self.tried_label.configure(text="")
        self.body_label.configure(text="")
        self.latency_label.configure(text="")
        self.letter_entry.configure(state="disabled")
        self.send_btn.configure(state="disabled")

        # Reabilitar campos de conexão
        self.connect_btn.configure(state="normal")
        self.ip_entry.configure(state="normal")
        self.port_entry.configure(state="normal")
        self.ip2_entry.configure(state="normal")
        self.port2_entry.configure(state="normal")

    # ─────────────────────────────────────────────────────────
    # Fechar janela
    # ─────────────────────────────────────────────────────────

    def on_closing(self):
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.destroy()


if __name__ == "__main__":
    app = ForcaClient()
    app.mainloop()