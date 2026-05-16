import os
import time
import random
import logging
from src.webhook import LoggingsBot
from src.service import ScrapingBot
from src.notifier import send_message

root_dir = os.path.dirname(os.path.abspath(__file__))

logging.basicConfig(
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO,
    filename=os.path.join(root_dir, "loggings.log"),
    filemode="w"
    )

bot = ScrapingBot()
_pass = 0
_WARNING = 15

if __name__ == "__main__":
    while True:
        delay = random.uniform(45, 75)
        
        bot.rn_service()
        _pass += 1

        if _pass >= _WARNING:
            message = {
            "username": "LoggingsBot",
            "content": f"[HEALTHBEAT] Iniciando Scraping - Proxima em: {delay:.2f}s"
            }
            send_message(discord_message=message, canal=LoggingsBot)
            _pass = 0
        time.sleep(delay)