import socket
import threading
import customtkinter as ctk

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ForcaClient(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Jogo da Forca Distribuído")
        self.geometry("600x650")
        self.sock = None

        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.pack(pady=10, padx=10, fill="x")

        self.ip_entry = ctk.CTkEntry(self.top_frame, placeholder_text="IP (ex: 127.0.0.1)", width=150)
        self.ip_entry.pack(side="left", padx=5)
        
        self.port_entry = ctk.CTkEntry(self.top_frame, placeholder_text="Porta (ex: 5000)", width=100)
        self.port_entry.pack(side="left", padx=5)

        self.connect_btn = ctk.CTkButton(self.top_frame, text="Conectar", command=self.connect_server, width=100)
        self.connect_btn.pack(side="left", padx=5)

        self.canvas = ctk.CTkCanvas(self, width=200, height=250, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(pady=15)
        self.draw_hangman(0)

        self.word_label = ctk.CTkLabel(self, text="", font=("Courier", 32, "bold"))
        self.word_label.pack(pady=10)

        self.status_label = ctk.CTkLabel(self, text="Desconectado", font=("Arial", 16), wraplength=500)
        self.status_label.pack(pady=10)

        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.pack(pady=15)

        self.letter_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Letra", width=80)
        self.letter_entry.pack(side="left", padx=5)
        self.letter_entry.configure(state="disabled")

        self.send_btn = ctk.CTkButton(self.input_frame, text="Enviar Letra", command=self.send_letter, width=120)
        self.send_btn.pack(side="left", padx=5)
        self.send_btn.configure(state="disabled")

    def draw_hangman(self, errors):
        self.canvas.delete("all")
        self.canvas.create_line(10, 240, 190, 240, fill="white", width=3)
        self.canvas.create_line(50, 240, 50, 20, fill="white", width=3)
        self.canvas.create_line(50, 20, 120, 20, fill="white", width=3)
        self.canvas.create_line(120, 20, 120, 50, fill="white", width=3)

        if errors >= 1:
            self.canvas.create_oval(100, 50, 140, 90, outline="white", width=3)
        if errors >= 2:
            self.canvas.create_line(120, 90, 120, 170, fill="white", width=3)
        if errors >= 3:
            self.canvas.create_line(120, 110, 90, 140, fill="white", width=3)
        if errors >= 4:
            self.canvas.create_line(120, 110, 150, 140, fill="white", width=3)
        if errors >= 5:
            self.canvas.create_line(120, 170, 90, 210, fill="white", width=3)
        if errors >= 6:
            self.canvas.create_line(120, 170, 150, 210, fill="white", width=3)

    def connect_server(self):
        ip = self.ip_entry.get() or "127.0.0.1"
        port_str = self.port_entry.get() or "5000"
        
        try:
            port = int(port_str)
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((ip, port))
            
            self.status_label.configure(text="Conectado! Aguardando...")
            self.connect_btn.configure(state="disabled")
            self.ip_entry.configure(state="disabled")
            self.port_entry.configure(state="disabled")
            
            threading.Thread(target=self.receive_messages, daemon=True).start()
        except Exception as e:
            self.status_label.configure(text=f"Erro de conexão: {e}")

    def receive_messages(self):
        while True:
            try:
                data = self.sock.recv(1024).decode()
                if not data:
                    break
                self.after(0, self.update_status, data)
            except:
                self.after(0, self.update_status, "Conexão perdida com o servidor.")
                break

    def update_status(self, message):
        if "Palavra:" in message and "Erros:" in message:
            partes = message.split("|")
            palavra_str = partes[0].replace("Palavra:", "").strip()
            erros_str = partes[1].replace("Erros:", "").split("/")[0].strip()
            
            self.word_label.configure(text=palavra_str)
            try:
                erros = int(erros_str)
                self.draw_hangman(erros)
            except ValueError:
                pass
            
            self.status_label.configure(text="")
        else:
            current_text = self.status_label.cget("text")
            if not current_text or "Palavra:" in current_text:
                self.status_label.configure(text=message.strip())
            else:
                self.status_label.configure(text=f"{current_text}\n{message.strip()}")

        if "Sua vez!" in message:
            self.letter_entry.configure(state="normal")
            self.send_btn.configure(state="normal")
        elif "Aguardando" in message or "Fim" in message or "Vitoria" in message or "Derrota" in message:
            self.letter_entry.configure(state="disabled")
            self.send_btn.configure(state="disabled")

    def send_letter(self):
        letter = self.letter_entry.get().strip()
        if letter and self.sock:
            try:
                self.sock.sendall(letter.encode())
                self.letter_entry.delete(0, 'end')
                self.letter_entry.configure(state="disabled")
                self.send_btn.configure(state="disabled")
            except Exception as e:
                self.status_label.configure(text=f"Erro ao enviar: {e}")

if __name__ == "__main__":
    app = ForcaClient()
    app.mainloop()