import os
import requests
import time
import random
import logging
from dotenv import load_dotenv

load_dotenv()

def CatchData():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
    ]
    
    ua_escolhido = random.choice(user_agents)
    headers_furtivos = {
        "User-Agent": ua_escolhido,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin" 
    }

    TRY = 3
    session = requests.Session()
    session.headers.update(headers_furtivos)
    for tentativa in range(TRY):
        try:
            time.sleep(random.uniform(1.5, 3.5)) 
            response = session.get(os.getenv("URL"), timeout=10)
            if response.status_code in (200, 204):
                logging.info("Dado Recolhido Com Sucesso!")
                final_response = response.json()
                return final_response["data"]["productSearch"]["recordsFiltered"]
            print(f"[AVISO] Tentativa {tentativa + 1}: Status {response.status_code} recebido.")
        except requests.exceptions.RequestException as error:
            print(f"[ERRO DE REDE] Tentativa {tentativa + 1}: {error}")
        time.sleep(random.uniform(3, 5))
    return None