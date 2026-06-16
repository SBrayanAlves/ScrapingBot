import os
import sqlite3
from contextlib import contextmanager
from dotenv import load_dotenv

# Carrega as Variaveis de Ambiente
load_dotenv()

# Acessa o Banco

current_dir = os.path.dirname(os.path.abspath(__file__))
# resultado: __file__ = databse.py
root_dir = os.path.dirname(current_dir)
# resultado: C:\Users\sbray\OneDrive\Documentos\ScrapingBot/src
db_folder = "/app/data" if os.environ.get("DOCKER_ENV") else os.path.join(os.getcwd(), "data")

load_dotenv(os.path.join(root_dir, ".env"))

os.makedirs(db_folder, exist_ok=True)
class DataBaseManager:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(db_folder, "DataBase.db")
 
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=7)
        conn.execute("PRAGMA journal_mode=WAL")
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