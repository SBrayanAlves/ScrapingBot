import os
import requests
import time
import random
import logging
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
        self.url = os.getenv("URL")
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
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Linux; Android 14; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        ]
        return {
            "User-Agent": random.choice(user_agents),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }

    def catch_data(self) -> Optional[int]:
        try:
            time.sleep(random.uniform(1.5, 3.5))
            response = self.session.get(self.url, timeout=10)
            response.raise_for_status()

            data = response.json()
            amount = data.get("data", {}).get("productSearch", {}).get("recordsFiltered", {})
            
            if amount is None:
                message = {
                    "username": "LoggingsBot",
                    "content": f"Data not found in JSON!"
                }
                send_message(discord_message=message, canal=LoggingsBot)
                logging.warning(f"Data not found in JSON!")
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