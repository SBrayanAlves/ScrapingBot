"""Objetos de dominio. Sem I/O, sem dependencias -- so dados e nomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RunStatus(StrEnum):
    """Desfecho de um ciclo. Vira coluna em `runs`.  DAT-1"""

    OK = "ok"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    UPSTREAM_REJECTED = "upstream_rejected"
    UNEXPECTED_PAYLOAD = "unexpected_payload"
    IMPLAUSIBLE = "implausible"
    ERROR = "error"


class EventKind(StrEnum):
    """Tipo de mudanca detectada."""

    INCREASE = "increase"  # entrou produto -> e o alerta que justifica o projeto
    ANOMALY = "anomaly"  # variacao fora da faixa plausivel  BUG-15
    FIRST_RUN = "first_run"  # linha de base inicial


@dataclass(frozen=True, slots=True)
class FetchResult:
    """O que a coleta devolve -- muito mais que um int.

    Os campos de cache existem para responder a pergunta do cliente
    ("a notificacao esta atrasando"): se `cache_age` cresce e `payload_hash`
    nao muda, o atraso e do CDN do alvo, nao do bot.  SCR-7 / PRD-6
    """

    amount: int
    payload_hash: str
    latency_ms: int
    http_status: int
    cache_age: int | None = None  # header `Age` -- segundos que a resposta passou no CDN
    cache_status: str | None = None  # `x-cache` / `cf-cache-status` / `x-vtex-cache`
    server_date: datetime | None = None  # header `Date` do alvo
    profile: str | None = None  # perfil de navegador usado nesta coleta


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Uma observacao gravada. Substitui a tabela `products`.  DAT-3"""

    observed_at: datetime
    amount: int
    payload_hash: str | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Event:
    """Uma mudanca digna de nota. Persistida antes de notificar.  BUG-13"""

    observed_at: datetime
    kind: EventKind
    previous: int | None
    current: int
    delta: int
    notified: bool = False
    id: int | None = None

    @property
    def is_alertable(self) -> bool:
        """ANOMALY vai para o canal de log, nao para o canal publico.  BUG-15"""
        return self.kind is EventKind.INCREASE


@dataclass(frozen=True, slots=True)
class RunResult:
    """Registro de um ciclo, com ou sem novidade.

    Existe porque `products` so gravava mudancas -- e por isso "nada aconteceu"
    e "o bot morreu" eram indistinguiveis no banco.  DAT-1
    """

    run_id: str
    started_at: datetime
    status: RunStatus
    duration_ms: int
    observed_amount: int | None = None
    error: str | None = None
    cache_age: int | None = None
    payload_hash: str | None = None  # alimenta a deteccao de resposta congelada  SCR-7
    events: list[Event] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.OK
