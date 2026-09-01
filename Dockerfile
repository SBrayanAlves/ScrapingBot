# ScrapingBot -- imagem de producao.
#
# INF-1  o banco vive em volume; nao morre com o container
# INF-4  `EXPOSE $PORT` removido: isto nao e servidor, e as notas de estudo
#        sobre mapeamento de portas foram para docs/decisoes.md
# INF-6  usuario criado ANTES do COPY (sem camada duplicada por chown) e um
#        HEALTHCHECK que testa vida real, nao "o processo existe"
# REL-4  base fixada -- ver a nota sobre digest abaixo

# ---------------------------------------------------------------- estagio 1
# Build separado: as ferramentas de compilacao (brotli/zstandard tem extensao C)
# ficam fora da imagem final.
#
# REL-4: a tag abaixo ainda e movel. Para tornar o build reproduzivel, troque
# por digest e deixe o Renovate/Dependabot abrir o PR de atualizacao:
#   docker pull python:3.13-slim && \
#   docker inspect --format='{{index .RepoDigests 0}}' python:3.13-slim
#   FROM python:3.13-slim@sha256:<cole aqui> AS builder
FROM python:3.13-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# requirements.txt agora e UTF-8. Em UTF-16 (BUG-1) esta linha falhava e a
# imagem simplesmente nao subia numa maquina limpa.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY src ./src
RUN /opt/venv/bin/pip install --no-cache-dir --no-deps .

# ---------------------------------------------------------------- estagio 2
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DB_PATH=/app/data/scrapingbot.db \
    BACKUP_DIR=/app/data/backups \
    LOCK_PATH=/app/data/scrapingbot.lock

# Usuario criado antes de qualquer COPY: `chown -R` depois duplicaria o
# tamanho de tudo que foi copiado, em uma camada nova.  INF-6
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv

# O banco e o unico estado do sistema. Sem isto, todo `docker rm` zera o
# historico e o bot volta ao estado "primeira execucao".  INF-1 / DAT-6
VOLUME ["/app/data"]

USER appuser

# Testa se o bot COLETOU nos ultimos 10 minutos -- nao se o processo existe.
# So e possivel porque a tabela `runs` grava todo ciclo, com ou sem novidade.
# INF-6 depende de DAT-1.
HEALTHCHECK --interval=5m --timeout=10s --start-period=2m --retries=3 \
    CMD ["python", "-m", "scrapingbot", "healthcheck", "--max-age-s", "600"]

# Forma exec: o processo recebe SIGTERM diretamente e o desligamento gracioso
# do ARQ-6 funciona de verdade.
ENTRYPOINT ["python", "-m", "scrapingbot"]
CMD ["run"]
