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
    )

if __name__ == "__main__":
    while True:
        delay = random.uniform(45, 75)
        message = {
            "username": "LoggingsBot",
            "content": f"Iniciando Raspagem - Proxima em: {delay:.2f}s"
            }
        bot = ScrapingBot()
        ScrapingBot.rn_service(bot)
        send_message(discord_message=message, canal=LoggingsBot)
        time.sleep(delay)