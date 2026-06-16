# Define a imagem principal
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Caminho de execucao
WORKDIR /app

# Copia o arquivo de dependencias/bibliotecas necessarias para rodar a aplicacao
COPY requirements.txt .

# Executa o comando que instala as bibliotecas necessarias
RUN pip install --no-cache-dir -r requirements.txt

# Copia todos os arquivos (menos .dockerignore) para a imagem
# Como rodar o container sendo que o .env esta fora: docker run --env-file .env minha-imagem
COPY . .

# ARG -> ARG permite parametrizar o build.
# ARG PYTHON_VERSION=3.13
# FROM python:${PYTHON_VERSION}
# Comando: docker build --build-arg PYTHON_VERSION=3.12

# Usamos para documentar qual porta esta sendo usada
# Exemplo:
# Um sistema em Docker roda diretamente na porta 7777, entao basta acessarmos http://localhost:7777 -> Sucesso
# Porem dentro do Docker, ele roda na porta 7777 mas preso la dentro, entao teriamos q acessar pra acessar novamente -> 7777:7777
# Pra realmente abrir preciamos executar: docker run -p 7777:7777 imagem
# Usuario acessa http://localhost:7777 e a aplicacao roda 7777 dentro do container
EXPOSE $PORT

RUN useradd -m appuser

RUN chown -R appuser:appuser /app

# Define um usuario admin para poder modificar a imagem garantindo maior seguranca ao sistema. Usuario predefinido: root
USER appuser

# Comando/arquivo que vai executar apos iniciar o container
CMD ["python", "main.py"]