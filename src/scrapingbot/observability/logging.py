"""Logging: stdout, run_id correlacionado e redacao de segredos.

OBS-1  log vai para stdout -- em container, quem coleta e o runtime
OBS-2  logger por modulo, formatacao preguicosa, `exception()` com traceback
OBS-3  rotacao quando ha arquivo
REL-5  todo ciclo carrega um run_id curto, entao o log fica pesquisavel
SEC-2  o token do webhook nunca chega ao log
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

_run_id: ContextVar[str] = ContextVar("run_id", default="-")

# Cada padrao remove a PARTE SECRETA e preserva o suficiente para depurar.
# Um segredo em log e um segredo vazado: logs sao copiados para lugares onde
# ninguem pensa em segredos.  SEC-2
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # https://discord.com/api/webhooks/<id>/<token>  -> o token e a credencial
    (
        re.compile(r"(https?://[^\s/]*discord(?:app)?\.com/api/webhooks/\d+/)[\w.\-]+"),
        r"\1[REDACTED]",
    ),
    # Qualquer query string: `RequestException` embute a URL inteira, e os
    # parametros do alvo sao informacao de negocio.
    (re.compile(r"(\?)[^\s\"']{8,}"), r"\1[QUERY-REDACTED]"),
    # Bearer / api keys que venham a existir
    (re.compile(r"(?i)(bearer\s+)[\w.\-]{8,}"), r"\1[REDACTED]"),
    (
        re.compile(r"(?i)((?:api[_-]?key|token|secret)[\"']?\s*[:=]\s*[\"']?)[\w.\-]{8,}"),
        r"\1[REDACTED]",
    ),
)


def redact(text: str) -> str:
    """Aplica todas as regras de redacao a um texto qualquer."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    """Reescreve a mensagem ANTES dela ser emitida por qualquer handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_value(v) for k, v in record.args.items()}
            else:
                record.args = tuple(_redact_value(a) for a in record.args)
        return True


def _redact_value(value: object) -> object:
    return redact(str(value)) if isinstance(value, str | Exception) else value


class RunIdFilter(logging.Filter):
    """Injeta o run_id do ciclo corrente em toda linha.  REL-5"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        return True


def new_run_id() -> str:
    """Gera e instala um run_id curto para o ciclo que esta comecando."""
    value = uuid.uuid4().hex[:8]
    _run_id.set(value)
    return value


def current_run_id() -> str:
    return _run_id.get()


def setup_logging(
    level: str = "INFO",
    *,
    log_file: Path | None = None,
    max_bytes: int = 5_000_000,
    backups: int = 3,
) -> None:
    """Configura o logger raiz uma unica vez.

    stdout sempre. Arquivo so quando pedido explicitamente -- em container o
    certo e nao ter arquivo nenhum, porque `docker logs` ja coleta o stdout.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):  # idempotente: reconfigurar nao duplica linha
        root.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)-7s [%(run_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    stream = logging.StreamHandler(sys.stdout)  # OBS-1
    stream.setFormatter(formatter)
    stream.addFilter(RunIdFilter())
    stream.addFilter(RedactingFilter())
    root.addHandler(stream)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        # `filemode="w"` apagava o log a cada restart -- justo quando ele importa.
        # RotatingFileHandler faz append e limita o tamanho.  BUG-9 / OBS-3
        rotating = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        rotating.setFormatter(formatter)
        rotating.addFilter(RunIdFilter())
        rotating.addFilter(RedactingFilter())
        root.addHandler(rotating)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
