import os
import sqlite3
from dotenv import load_dotenv

# Carrega as Variaveis de Ambiente
load_dotenv()

# Acessa o Banco

def StartSetup():
    db_path = os.path.join(os.getcwd(), "DataBase.db")
    connect = sqlite3.connect(db_path)
    query = connect.cursor()

    query.execute(
        '''
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount INTEGER,
            date TEXT
        )
        '''
    )

    connect.commit()
    return query, connect