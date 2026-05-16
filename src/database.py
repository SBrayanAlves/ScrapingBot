import os
import sqlite3
from contextlib import contextmanager
from dotenv import load_dotenv

# Carrega as Variaveis de Ambiente
load_dotenv()

# Acessa o Banco

class DataBaseManager:
    def __init__(self, db_path: str = None):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(current_dir)
        self.db_path = db_path or os.path.join(root_dir, "DataBase.db")
 
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=7)
        conn.execute("PRAGMA journal_model=WAL")
        try:
            yield conn
        finally:
            conn.close()

    def start_setup(self):
        with self.get_connection() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS products(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount INTEGER,
                    date TEXT
                )
                '''
            )
            conn.commit()