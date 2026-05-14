import os
from dotenv import load_dotenv

# Carrega as Variaveis de Ambiente
load_dotenv()

# Conexao com WebHook
ScrapingBot = os.getenv("SCRAPINGBOT")
LoggingsBot = os.getenv("LOGGINGSBOT")