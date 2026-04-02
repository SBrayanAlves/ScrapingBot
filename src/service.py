import logging
from datetime import datetime
from .scraper import CatchData
from .database import StartSetup
from .notifier import SendMessage

# Regra de Negocio 

def ScrapingBot():

    query, connect = StartSetup()
    data = CatchData()

    current_date = datetime.now().strftime("%Y-%m-%d")

    query.execute(
        '''
        SELECT * FROM products ORDER BY id DESC LIMIT 1;
        '''
    )
    db_reponse = query.fetchone()

    if db_reponse is None:
        # Sistema iniciando pela primeira vez
        query.execute("INSERT INTO products (amount, date) VALUES (?, ?)", (data, current_date,))
        connect.commit()
    else:
        db_data = db_reponse[1]
        # 4.1 -> Se o numero for maior
        difference = int(data) - db_data
        if difference > 1:
            #   4.1.1 -> Notificar no Discord + Salvar novo numero no banco de dados
            query.execute("INSERT INTO products (amount, date) VALUES (?, ?)", (data, current_date,))
            connect.commit()
            logging.info("Novos Produtos Encontrados e Salvos com Sucesso!")
            discord_message = {
                "username": "ScrapingBot",
                "content": f"@everyone 🚨 **NOVOS PRODUTOS!**\n\nAcabou de cair: **{data - db_data} PRODUTO(S)**!"
            }
            SendMessage(discord_message)

        # 4.2 -> Se o numero for menor
        elif int(data) < db_data:
            #   4.2.1 -> Apenas salve o numero no banco de dados
            query.execute("INSERT INTO products (amount, date) VALUES (?, ?)", (data, current_date))
            connect.commit()