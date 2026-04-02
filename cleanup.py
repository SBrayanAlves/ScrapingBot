from src.database import StartSetup

def Clear():
    query, connect = StartSetup()

    query.execute(
        '''
        DELETE FROM products WHERE date < date("now", "-6 days")
        '''
    )

    rows = query.rowcount
    connect.commit()

    if rows > 0:
        query.execute("VACUUM")
        print("Limpeza + VACUUM efetuados com sucesso!")
    else:
        print("Banco de dados ja esta limpo!")

Clear()