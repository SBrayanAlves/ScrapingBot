import time
import random
import logging
from src.webhook import LoggingsBot
from src.service import ScrapingBot
from src.notifier import send_message

logging.basicConfig(
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO,
    filename="loggings.log",
    filemode="w"
    )

bot = ScrapingBot()
rep = 0

if __name__ == "__main__":
    while True:
        delay = random.uniform(45, 75)
        message = {
            "username": "LoggingsBot",
            "content": f"[HEALTHBEAT] Iniciando Scraping - Proxima em: {delay:.2f}s"
            }
        ScrapingBot.rn_service(bot)
        if rep >= 10:
            send_message(discord_message=message, canal=LoggingsBot)
            rep = 0
        rep += 1
        time.sleep(delay)