import time
import random
import logging
from src.service import ScrapingBot

logging.basicConfig(level=logging.INFO, filename="loggings.log", filemode="w")

if __name__ == "__main__":
    while True:
        logging.info("Iniciando Raspagem!")
        ScrapingBot()
        delay = random.uniform(45, 75)
        logging.info(f"Aguardando {delay:.2f} segundos até a próxima verificação...")
        time.sleep(delay)