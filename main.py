import time
import random
from src.service import ScrapingBot

if __name__ == "__main__":
    delay = random.uniform(17, 277)
    time.sleep(delay)

    ScrapingBot()
