import os
import requests
import time
import random
import logging
from fake_useragent import UserAgent
from .webhook import LoggingsBot
from .notifier import send_message
from typing import Optional
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
load_dotenv(os.path.join(root_dir, ".env"))

class ScraperClient:
    def __init__(self):
        self.base_url = os.getenv("URL")
        self.ua_factory = UserAgent()
        self.session = self.create_session()
        self._pass = 0
        self._WARNING = 15

    def create_session(self) -> requests.Session:
        session = requests.Session()

        retry = Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(self._get_headers())
        return session
    
    def _get_headers(self) -> dict:
        return {
            "User-Agent": self.ua_factory.random,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Connection": "keep-alive",
            "Referer": os.getenv('REFERER'), 
            "content-type": "application/json",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    def catch_data(self) -> Optional[int]:
        try:
            self.session.headers.update({"User-Agent": self.ua_factory.random})

            timestamp = int(time.time())
            dynamic_url = f"{self.base_url}&_={timestamp}"

            time.sleep(random.uniform(1.5, 3.5))
            
            response = self.session.get(dynamic_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            amount = data.get("data", {}).get("productSearch", {}).get("recordsFiltered")
            
            if amount is None:
                message = {
                    "username": "LoggingsBot",
                    "content": "Data not found in JSON!"
                }
                send_message(discord_message=message, canal=LoggingsBot)
                logging.warning("Data not found in JSON!")
                raise ValueError("Data not found!")
            
            self._pass += 1
            if self._pass >= self._WARNING:
                message = {
                    "username": "LoggingsBot",
                    "content": f"Quantidade de produtos atual: {amount}"
                }
                send_message(discord_message=message, canal=LoggingsBot)
                self._pass = 0
                
            return int(amount)
        
        except requests.exceptions.RequestException as error:
            message = {
                "username": "LoggingsBot",
                "content": f"[FINAL NETWORK ERROR] - {error}"
            }
            send_message(discord_message=message, canal=LoggingsBot)
            logging.warning(f"[FINAL NETWORK ERROR] - {error}")
            return None