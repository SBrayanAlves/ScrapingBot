import logging
from datetime import datetime
from .webhook import LoggingsBot, ScrapingBot as DScraping
from .scraper import ScraperClient
from .database import DataBaseManager
from .notifier import send_message

# Regra de Negocio

def validate_data(data: any) -> int:
    if data is None:
        raise ValueError("Scraper returned None")

    try:
        amount = int(data)
        if amount < 0:
            raise ValueError("Negative value")
        return amount
    except (ValueError, TypeError) as e:
        logging.error(f"Validation Failed: {e}")
        raise

class ScrapingBot:

    def __init__(self):
        self.db = DataBaseManager()
        self.scraper = ScraperClient()
        self.db.start_setup()

    def rn_service(self):
        try:
            data = self.scraper.catch_data()
            data_valid = validate_data(data)
            current_date = datetime.now().strftime("%Y-%m-%d")

            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                '''
                SELECT amount FROM products ORDER BY id DESC LIMIT 1;
                '''
                )
                db_response = cursor.fetchone()

                if db_response is None:
                    # Sistema iniciando pela primeira vez
                    cursor.execute("INSERT INTO products (amount, date) VALUES (?, ?)", (data_valid, current_date,))
                    conn.commit()
                    message = {
                        "username": "LoggingsBot",
                        "content": f"[DATABASE] - Iniciando DataBase"
                        }   
                    send_message(discord_message=message, canal=LoggingsBot)
                    logging.info(f"[DATABASE] - Iniciando DataBase")
                    return None
                
                db_data = db_response[0]
                # 4.1 -> Se o numero for maior
                difference = data_valid - db_data
                if difference > 2:
                    #   4.1.1 -> Notificar no Discord + Salvar novo numero no banco de dados
                    cursor.execute("INSERT INTO products (amount, date) VALUES (?, ?)", (data_valid, current_date,))
                    conn.commit()
                    logging.info("Novos Produtos Encontrados e Salvos com Sucesso!")
                    discord_message = {
                        "username": "ScrapingBot",
                        "content": f"@everyone 🚨 **NOVOS PRODUTOS!**\n\nAcabou de cair: **{data_valid - db_data} PRODUTO(S)**!"
                    }
                    send_message(discord_message, canal=DScraping)

                # 4.2 -> Se o numero for menor
                elif data_valid < db_data:
                    #   4.2.1 -> Apenas salve o numero no banco de dados
                    cursor.execute("INSERT INTO products (amount, date) VALUES (?, ?)", (data_valid,  current_date))
                    conn.commit()
        except ValueError as e:
            logging.error(f"Validation Error/Logic: {e}")
        except Exception as e:
            logging.error(f"Unexpected service error: {e}")