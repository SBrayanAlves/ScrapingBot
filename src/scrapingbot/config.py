"""Configuracao unica, validada no boot.  INF-5 / ARQ-3 / ENG-9

Duas regras:
  1. `load_dotenv` acontece AQUI e em nenhum outro lugar. Os modulos recebem
     valores prontos no construtor -- eles nao leem o ambiente.
  2. Nenhum numero magico no codigo. As dez decisoes de comportamento que
     estavam espalhadas por seis arquivos (`> 2`, `15`, `45-75`, `1.5-3.5`,
     `6 days`, `timeout=10`, `timeout=7`, `TRY=3`, `total=3`, `backoff=2`)
     viraram campos com default no codigo e override por variavel de ambiente.
     Ajustar o limiar de alerta deixou de ser um deploy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import find_dotenv, load_dotenv

from .errors import ConfigError

_SENTINEL: Any = object()

# Nomes antigos aceitos por compatibilidade com o .env que ja esta no servidor.
# Some quando o deploy for atualizado -- documentado em docs/operacao.md.
_LEGACY_ALIASES = {
    "DISCORD_ALERT_WEBHOOK": "SCRAPINGBOT",
    "DISCORD_LOG_WEBHOOK": "LOGGINGSBOT",
}


def _project_root() -> Path:
    """Raiz do repo quando se roda a partir do codigo-fonte.

    So vale para instalacao editavel (`pip install -e .`) ou execucao direta de
    dentro de src/. Com `pip install .` o pacote vive em site-packages e este
    caminho aponta para dentro da venv -- por isso NAO se pode depender so dele.
    Ver `_resolve_env_file`.
    """
    return Path(__file__).resolve().parent.parent.parent


def _resolve_env_file(explicito: str | Path | None) -> Path | None:
    """Descobre qual .env usar, na ordem de prioridade que nao surpreende.

    1. o que foi pedido explicitamente (`--env-file`);
    2. o primeiro `.env` encontrado subindo a partir do DIRETORIO ATUAL --
       e o que faz `cd /caminho/do/projeto && python -m scrapingbot run`
       funcionar no cron/systemd, inclusive com `pip install .`;
    3. a raiz do codigo-fonte, para quando se roda de dentro do repo.

    Sem o passo 2, uma instalacao nao-editavel procurava o .env dentro de
    `.venv/lib/pythonX.Y/` e o bot morria no boot dizendo que faltava `URL`.
    """
    if explicito is not None:
        caminho = Path(explicito)
        return caminho if caminho.is_file() else None

    do_cwd = find_dotenv(usecwd=True)
    if do_cwd:
        return Path(do_cwd)

    da_fonte = _project_root() / ".env"
    return da_fonte if da_fonte.is_file() else None


def _raw(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        legacy = _LEGACY_ALIASES.get(name)
        if legacy:
            value = os.environ.get(legacy)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _get(name: str, default: Any = _SENTINEL) -> str:
    value = _raw(name)
    if value is None:
        if default is _SENTINEL:
            alias = _LEGACY_ALIASES.get(name)
            extra = f" (ou o nome antigo {alias})" if alias else ""
            raise ConfigError(
                f"Variavel de ambiente obrigatoria ausente: {name}{extra}. "
                "Copie .env.example para .env e preencha."
            )
        return str(default)
    return value


def _get_int(name: str, default: int) -> int:
    value = _get(name, default)
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} precisa ser inteiro, veio {value!r}") from exc


def _get_float(name: str, default: float) -> float:
    value = _get(name, default)
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} precisa ser numerico, veio {value!r}") from exc


def _get_bool(name: str, default: bool) -> bool:
    value = _get(name, "1" if default else "0").lower()
    if value in {"1", "true", "yes", "y", "on", "sim"}:
        return True
    if value in {"0", "false", "no", "n", "off", "nao"}:
        return False
    raise ConfigError(f"{name} precisa ser booleano (1/0), veio {value!r}")


@dataclass(frozen=True, slots=True)
class Settings:
    """Todo comportamento configuravel do sistema, em um objeto imutavel."""

    # ------------------------------------------------------------------ alvo
    target_url: str  # endpoint JSON consultado
    page_url: str  # pagina HTML equivalente, usada no aquecimento  SCR-8
    referer: str

    # --------------------------------------------------------------- discord
    alert_webhook: str  # canal publico   (ex-SCRAPINGBOT)   ARQ-4
    log_webhook: str  # canal de operacao (ex-LOGGINGSBOT)
    alert_mention: str  # "<@&123>": cargo opt-in no lugar de @everyone  SCR-5

    # ----------------------------------------------------------------- banco
    db_path: Path
    retention_days: int  # detalhe de `runs` descartado depois disto   DAT-5
    events_retention_days: int  # eventos ficam muito mais tempo: sao o historico
    backup_dir: Path
    backup_keep: int  # DAT-6

    # --------------------------------------------------------------- cadencia
    interval_min_s: float
    interval_max_s: float
    cycle_deadline_s: float  # orcamento de tempo do ciclo   BUG-16
    backoff_base_s: float  # BUG-17
    backoff_max_s: float
    active_days: frozenset[int] | None  # 0=segunda .. 6=domingo; None = todos  ARQ-8
    active_hour_start: int
    active_hour_end: int
    timezone: ZoneInfo

    # ------------------------------------------------------------------ regra
    alert_threshold: int  # delta minimo para alertar   BUG-8
    max_plausible_delta: int  # acima disto e anomalia, nao alerta   BUG-15
    max_plausible_amount: int

    # ------------------------------------------------------------------- http
    http_timeout_s: float
    http_retries: int
    http_backoff_factor: float
    warmup_enabled: bool  # SCR-8
    session_max_cycles: int  # recria a sessao inteira a cada N ciclos   SCR-1
    prefetch_delay_min_s: float
    prefetch_delay_max_s: float
    fetch_backend: str  # "auto" | "requests" | "curl_cffi"   SCR-6
    cache_buster_param: str  # nome do parametro anti-cache ("" desliga)
    no_cache_headers: bool  # Chrome so manda isso em reload forcado -- default off

    # --------------------------------------------------------------- operacao
    heartbeat_every: int  # ARQ-5
    failure_alert_threshold: int  # falhas consecutivas ate alertar   OBS-5
    stale_alert_threshold: int  # payloads identicos seguidos ate suspeitar  SCR-7
    deadman_url: str | None  # healthchecks.io e afins   REL-1
    lock_path: Path  # BUG-14
    notify_timeout_s: float  # BUG-4
    notify_retries: int
    log_level: str
    log_file: Path | None  # None = so stdout   OBS-1
    log_max_bytes: int
    log_backups: int
    env_file: Path | None  # de onde a config veio; None = so o ambiente

    # ------------------------------------------------------------------- util
    def local(self, moment: datetime) -> datetime:
        """Converte um datetime UTC para o fuso de exibicao.  DAT-2"""
        return moment.astimezone(self.timezone)

    def describe(self) -> str:
        """Dump da config para o log de boot, sem vazar segredo nem alvo."""
        secret = {
            "alert_webhook",
            "log_webhook",
            "deadman_url",
            "target_url",
            "page_url",
            "referer",
        }
        parts = [
            f"{f.name}=<oculto>" if f.name in secret else f"{f.name}={getattr(self, f.name)}"
            for f in fields(self)
        ]
        return " ".join(parts)


def _parse_days(raw: str) -> frozenset[int] | None:
    """Vazio/`all` = todos os dias. `1,3,6` = terca, quinta, domingo."""
    cleaned = raw.strip().lower()
    if cleaned in {"", "all", "todos", "*"}:
        return None
    try:
        days = frozenset(int(part) for part in cleaned.split(",") if part.strip())
    except ValueError as exc:
        raise ConfigError(f"ACTIVE_DAYS invalido: {raw!r} (use 0-6 separados por virgula)") from exc
    if not days or any(day < 0 or day > 6 for day in days):
        raise ConfigError(f"ACTIVE_DAYS fora da faixa 0-6: {raw!r}")
    return days


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Le o ambiente, valida e congela. Se algo falta, falha aqui e com nome."""
    arquivo = _resolve_env_file(env_file)
    if arquivo is not None:
        load_dotenv(arquivo, override=False)

    # O banco fica ao lado do .env quando ha um; senao, ao lado do codigo.
    # Em nenhum dos casos depende do cwd por acidente, como acontecia no BUG-5.
    base = arquivo.parent if arquivo is not None else _project_root()
    db_path = Path(_get("DB_PATH", base / "data" / "scrapingbot.db"))

    interval_min = _get_float("INTERVAL_MIN_S", 45.0)
    interval_max = _get_float("INTERVAL_MAX_S", 75.0)
    if interval_min <= 0 or interval_max < interval_min:
        raise ConfigError(
            f"Intervalo invalido: INTERVAL_MIN_S={interval_min} INTERVAL_MAX_S={interval_max}"
        )

    hour_start = _get_int("ACTIVE_HOUR_START", 0)
    hour_end = _get_int("ACTIVE_HOUR_END", 24)
    if not 0 <= hour_start < hour_end <= 24:
        raise ConfigError(
            f"Janela horaria invalida: ACTIVE_HOUR_START={hour_start} ACTIVE_HOUR_END={hour_end}"
        )

    backend = _get("FETCH_BACKEND", "auto").lower()
    if backend not in {"auto", "requests", "curl_cffi"}:
        raise ConfigError(f"FETCH_BACKEND invalido: {backend!r}")

    tz_name = _get("TIMEZONE", "America/Sao_Paulo")
    try:
        timezone = ZoneInfo(tz_name)
    except Exception as exc:
        raise ConfigError(f"TIMEZONE invalido: {tz_name!r}") from exc

    threshold = _get_int("ALERT_THRESHOLD", 1)
    if threshold < 1:
        raise ConfigError(f"ALERT_THRESHOLD precisa ser >= 1, veio {threshold}")

    log_file_raw = _get("LOG_FILE", "")

    return Settings(
        target_url=_get("URL"),
        page_url=_get("P_URL"),
        referer=_get("REFERER"),
        alert_webhook=_get("DISCORD_ALERT_WEBHOOK"),
        log_webhook=_get("DISCORD_LOG_WEBHOOK"),
        alert_mention=_get("ALERT_MENTION", ""),
        db_path=db_path,
        retention_days=_get_int("RETENTION_DAYS", 30),
        events_retention_days=_get_int("EVENTS_RETENTION_DAYS", 730),
        backup_dir=Path(_get("BACKUP_DIR", db_path.parent / "backups")),
        backup_keep=_get_int("BACKUP_KEEP", 7),
        interval_min_s=interval_min,
        interval_max_s=interval_max,
        cycle_deadline_s=_get_float("CYCLE_DEADLINE_S", 40.0),
        backoff_base_s=_get_float("BACKOFF_BASE_S", 60.0),
        backoff_max_s=_get_float("BACKOFF_MAX_S", 1800.0),
        active_days=_parse_days(_get("ACTIVE_DAYS", "")),
        active_hour_start=hour_start,
        active_hour_end=hour_end,
        timezone=timezone,
        alert_threshold=threshold,
        max_plausible_delta=_get_int("MAX_PLAUSIBLE_DELTA", 200),
        max_plausible_amount=_get_int("MAX_PLAUSIBLE_AMOUNT", 100_000),
        http_timeout_s=_get_float("HTTP_TIMEOUT_S", 10.0),
        http_retries=_get_int("HTTP_RETRIES", 3),
        http_backoff_factor=_get_float("HTTP_BACKOFF_FACTOR", 2.0),
        warmup_enabled=_get_bool("WARMUP_ENABLED", True),
        session_max_cycles=_get_int("SESSION_MAX_CYCLES", 40),
        prefetch_delay_min_s=_get_float("PREFETCH_DELAY_MIN_S", 1.5),
        prefetch_delay_max_s=_get_float("PREFETCH_DELAY_MAX_S", 3.5),
        fetch_backend=backend,
        cache_buster_param=_get("CACHE_BUSTER_PARAM", "_"),
        no_cache_headers=_get_bool("NO_CACHE_HEADERS", False),
        heartbeat_every=_get_int("HEARTBEAT_EVERY", 15),
        failure_alert_threshold=_get_int("FAILURE_ALERT_THRESHOLD", 5),
        stale_alert_threshold=_get_int("STALE_ALERT_THRESHOLD", 30),
        deadman_url=_get("DEADMAN_URL", "") or None,
        lock_path=Path(_get("LOCK_PATH", db_path.parent / "scrapingbot.lock")),
        notify_timeout_s=_get_float("NOTIFY_TIMEOUT_S", 10.0),
        notify_retries=_get_int("NOTIFY_RETRIES", 3),
        log_level=_get("LOG_LEVEL", "INFO").upper(),
        log_file=Path(log_file_raw) if log_file_raw else None,
        log_max_bytes=_get_int("LOG_MAX_BYTES", 5_000_000),
        log_backups=_get_int("LOG_BACKUPS", 3),
        env_file=arquivo,
    )
