# Jogo da Forca Distribuído

Este projeto implementa o clássico **Jogo da Forca** utilizando conceitos de **Sistemas Distribuídos**, resolvendo o problema de escalabilidade, comunicação via rede (sockets) e redundância (múltiplos servidores). 

---

## 🛠️ Como o problema de Sistemas Distribuídos foi resolvido

O desafio exigia a criação de um jogo multiplayer, escalável, que acomodasse os usuários em instâncias isoladas de duas pessoas (pares), mantendo a capacidade de receber dezenas de conexões concorrentes. Além disso, pedia-se o uso de ao menos duas máquinas como servidor para prover redundância e disponibilidade. 

Neste projeto, a arquitetura distribuída foi implementada com as seguintes estratégias:

1. **Redundância e Disponibilidade (Múltiplos Servidores):**
   - O sistema permite iniciar múltiplos servidores (Servidor 1 e Servidor 2) rodando em portas distintas que monitoram a saúde (Health Check e Heartbeat) uns dos outros através de portas de sincronização exclusivas.
   - O cliente foi desenvolvido para tentar se conectar a uma lista de servidores. Caso o servidor principal caia ou esteja inalcançável, o cliente automaticamente faz o *fallback* tentando reconectar no servidor secundário configurado.

2. **Gerenciamento de Estado Compartilhado:**
   - A consistência de dados entre os nós servidores é obtida utilizando um banco de dados SQLite com controle de concorrência avançado operando no modo **WAL** (*Write-Ahead Logging*). 
   - Ambos os nós servidores acessam de forma concorrente a base de dados (`forca.db`) na infraestrutura, garantindo que se o Cliente A bater no Servidor 1 e o Cliente B bater no Servidor 2, ambos acessarão a mesma fila e o mesmo estado da partida.

3. **Arquitetura de Comunicação (Client-Server / Sockets):**
   - A comunicação estrita entre cliente e servidor se dá toda por Sockets TCP, sem o uso de middlewares pesados. Essa abordagem exige um protocolo simples de mensagens por texto (ex: `CONNECT|...`, `LETRA|...`) manipulado pelos sockets de forma nativa e assíncrona.
   
4. **Resiliência de Conexão e Latência:**
   - Foi implementado um sistema de *Ping/Pong* entre os clientes e o servidor. Isso não só monitora a latência exibida em tempo real na tela, mas ajuda a detectar interrupções.
   - Se um dos jogadores perder a conexão, o estado no servidor pausa o jogo do outro adversário. O jogador desconectado tem um prazo (até 30 segundos) para reconectar-se, e devido ao estado centralizado do jogo, a partida continua exatamente no ponto em que parou. Passados 30 segundos estritos sem reconexão, o jogador que ficou ganha por W.O.

---

## 🎮 Como Funciona o Jogo

O jogo atende estritamente a todos os requisitos do projeto focando em escalabilidade e UX:
- **Matchmaking e Filas:** Jogadores solicitam conexão e caem em uma fila de "espera" (`waiting`). O servidor monitora constantemente a fila e agrupa os jogadores que entram de 2 em 2 (`playing`), gerando automaticamente partidas separadas (instâncias de jogos). O terceiro usuário aguardará pacientemente até que seja verificado um quarto, e assim sucessivamente.
- **Interface Gráfica Amigável:** O cliente interage com uma UI fluida (CustomTkinter) que demonstra: 
  - Aviso sobre sua posição na fila ("Voce e o 1o na fila"). 
  - Aviso na interface em caso de ping alto.
  - O desenho da forca se formando a cada erro (cabeça, tronco, membro superior direito, esquerdo, membro inferior direito, esquerdo — perdas de 6 partes totais).
  - Letras erradas listadas abaixo da forca.
- **Regras:** Cada jogador alterna os turnos digitando via client suas letras-chute. Quem fechar a palavra primeiro ou o adversário errar 6 vezes definirá o fim de jogo. Todo o sincronismo de turnos e atualização de interface gráfica é guiado pelas mensagens do servidor.

---

## 🚀 Como Executar o Jogo

Para rodar este repositório em um computador novo (ou em dois computadores com acesso de rede), basta seguir as instruções abaixo:

### 1. Clonar e Preparar o Ambiente

Em seu terminal (Linux, Mac ou Prompt/PowerShell no Windows):

```bash
# 1. Clone o repositório
git clone https://github.com/SEU_USUARIO/jogo-da-forca.git
cd jogo-da-forca

# 2. Crie e ative um ambiente virtual(Recomendado)
# No Windows:
python -m venv venv
venv\Scripts\activate
# No Linux/Mac:
python3 -m venv venv
source venv/bin/activate

# 3. Instale a biblioteca da interface gráfica das dependências cliente
pip install customtkinter
```

### 2. Iniciando os Servidores 

Como o sistema é preparado para redundância, instancie dois servidores. Eles podem estar em TTY's diferentes, na mesma máquina (alterando portas) ou máquinas interligadas que consigam compartilhar o drive para o SQLite.

**Em um terminal, inicie o Servidor Principal (Porta Game: 5000 | Porta Sync: 6000):**
```bash
python servidor.py 5000 6000
```

**Em outro terminal, inicie o Servidor Secundário (Porta Game: 5001 | Porta Sync: 6001 | Observando Sync Secundária 6000 do nó 1):**
```bash
python servidor.py 5001 6001 127.0.0.1 6000
```
> Os nós logo trocarão mensagens de `HEARTBEAT`, indicando em seus terminais estarem cientes da redundância "*Peer na porta 5000 esta ONLINE*".

### 3. Iniciando os Clientes (Jogadores)

Você precisará de pelo menos dois clientes para efetivar uma partida (pode abrir no mesmo computador para testes, em instâncias diferentes ou em computadores diferentes na rede setando o IP das máquinas servidor).

```bash
python cliente_gui.py
```

Na interface que abrir:
- Digite seu nome.
- Preencha o IP e a porta de **ambos** os servidores (Por exemplo: IP Sec. `127.0.0.1` e porta `5001`). Assim, caso um dos dois caia, seu cliente assumirá o secundário automaticamente.
- Clique em **Conectar**. O primeiro a entrar avisará estar alocando vaga. Ao conectar o segundo player nos mesmos passos, a tela de jogo será imediatamente apresentada em sincronia.
