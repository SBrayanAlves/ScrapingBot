import os
from dotenv import load_dotenv

# Carrega as Variaveis de Ambiente
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

load_dotenv(os.path.join(root_dir, ".env"))

# Conexao com WebHook
ScrapingBot = os.getenv("SCRAPINGBOT")
LoggingsBot = os.getenv("LOGGINGSBOT")