"""Interface de notificacao.  ARQ-1 / PRD-4

A regra de negocio monta uma `Notification` -- titulo, corpo, severidade,
canal. Ela nao sabe o que e um embed do Discord, nem que existe webhook. Trocar
para Telegram ou e-mail e escrever outra classe que implemente `send`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class Channel(StrEnum):
    """Para quem a mensagem interessa."""

    PUBLIC = "public"  # o canal que o cliente le -- so o que exige acao dele
    LOG = "log"  # operacao: heartbeat, falhas, anomalias, manutencao


class Severity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Notification:
    title: str
    body: str
    channel: Channel = Channel.LOG
    severity: Severity = Severity.INFO
    fields: tuple[tuple[str, str], ...] = ()
    mention: bool = False  # so o alerta de negocio menciona  SCR-5
    url: str | None = None  # link direto para a pagina  PRD-2
    timestamp: datetime | None = None
    footer: str = ""
    extra: dict[str, str] = field(default_factory=dict)


class Notifier(Protocol):
    def send(self, notification: Notification) -> None:
        """Entrega a notificacao.

        Contrato: retorna normalmente SE E SOMENTE SE a mensagem foi aceita.
        Qualquer outra coisa levanta `NotificationError`.

        O `send_message` antigo devolvia `None` no sucesso, `None` ao esgotar
        as tentativas e `None` na excecao -- o chamador nao tinha como saber.
        Era a raiz mecanica dos alertas que sumiam em silencio.  BUG-18 / BUG-13
        """
        ...
