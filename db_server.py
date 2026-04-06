from xmlrpc.server import SimpleXMLRPCServer
import sqlite3

def init_db():
    conn = sqlite3.connect('forca_central.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jogadores (id TEXT PRIMARY KEY, nome TEXT, status TEXT, server_port INTEGER, disconnect_time REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS jogos (id INTEGER PRIMARY KEY AUTOINCREMENT, p1 TEXT, p2 TEXT, palavra TEXT, oculta TEXT, erros INTEGER, turno TEXT, status TEXT, tentativas TEXT)''')
    conn.commit()
    conn.close()

def run_query(query, params=[]):
    conn = sqlite3.connect('forca_central.db', timeout=5)
    c = conn.cursor()
    try:
        c.execute(query, tuple(params))
        if query.strip().upper().startswith("SELECT"):
            result = c.fetchall()
        else:
            conn.commit()
            result = []
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "data": []}
    finally:
        conn.close()

def run_transaction(queries_and_params):
    conn = sqlite3.connect('forca_central.db', timeout=5)
    c = conn.cursor()
    try:
        for q, p in queries_and_params:
            c.execute(q, tuple(p))
        conn.commit()
        return {"status": "ok"}
    except Exception as e:
        conn.rollback()
        return {"status": "error"}
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    server = SimpleXMLRPCServer(("0.0.0.0", 8000), allow_none=True)
    server.register_function(run_query, "run_query")
    server.register_function(run_transaction, "run_transaction")
    print("Servidor de Banco de Dados RPC rodando na porta 8000...")
    server.serve_forever()