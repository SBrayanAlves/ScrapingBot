import requests
import logging
import time

# Envia Mensagem
def send_message(discord_message, canal):
    WebHook = canal
    TRY = 3
    for _ in range(TRY):
        try:
            discord_logging = requests.post(WebHook, json=discord_message)
            if discord_logging.status_code in (200, 204):
                return None
            logging.warning(f"Error sending message! Attempt: {_+1}")
            time.sleep(3)
        except Exception as e:
            logging.warning(f"Error sending message: {e}")