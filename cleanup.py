import logging
from src.database import DataBaseManager
from src.webhook import LoggingsBot, ScrapingBot as DScraping
from src.notifier import send_message


class Clear:
    
    def __init__(self):
        self.db = DataBaseManager()
        self.db.start_setup()

    def main(self): 
        rows = self.db_clear()

        if rows > 0:
            self.vacuum()
            message = {
                "username": "LoggingsBot",
                "content": f"[DATABASE] - Limpeza + VACUUM realizados"
                }
            send_message(discord_message=message, canal=LoggingsBot)
            logging.info(f"[DATABASE] - Limpeza + VACUUM realizados")
            
    def db_clear(self):
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                DELETE FROM products WHERE date < date("now", "-6 days")
                '''
            )
            rows = cursor.rowcount
            conn.commit()
            return rows
        
    def vacuum(self):
        with self.db.get_connection() as conn:
            conn.execute('VACUUM')
        

limpeza = Clear()
limpeza.main()