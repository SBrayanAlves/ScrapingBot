import os
import requests
import time
import random
from dotenv import load_dotenv

# Carrega as Variaveis de Ambiente
load_dotenv()

# Pega os dados
def CatchData():

    user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) Firefox/118.0",
    ]
    header = {
    "User-Agent": random.choice(user_agents),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
    }

    TRY = 3
    for _ in range(TRY):
        try:
            session = requests.session()
            session.headers.update({'User-Agent': header})
            time.sleep(random.uniform(1, 3))
            response = session.get(os.getenv("URL"), headers=header)
            if response.status_code in (200, 204):
                final_response = response.json()
                return final_response["data"]["productSearch"]["recordsFiltered"]
            print(f"[ERRO]! Status {response.status_code}!")
            time.sleep(2)
        except Exception as error:
            print(f"Error: {error}")
        time.sleep(2)
    return None
