import os
import requests
from dotenv import load_dotenv

# Carrega as Variaveis de Ambiente
load_dotenv()

# Conexao com WebHook
WebHook = os.getenv("WEBHOOK")

# Envia Mensagem
def SendMessage(discord_message):
    TRY = 3 
    for _ in range(TRY):
        try:
            discord_response = requests.post(WebHook, json=discord_message)
            if discord_response.status_code in (200, 204):
                print("Notificacao enviada")
                break
            print("Erro ao enviar!")
        except Exception as e:
            print(f"Error: {e}")
