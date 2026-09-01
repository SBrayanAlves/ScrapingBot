"""Hierarquia de excecoes do dominio.  OBS-4

O ponto: um 503 do alvo e uma mudanca no formato do payload sao problemas
completamente diferentes. O primeiro voce espera e ignora; o segundo significa
que o bot esta cego e voce precisa saber AGORA. Antes, os dois chegavam ao log
como a mesma linha ("Validation Error/Logic").
"""

from __future__ import annotations


class ScrapingBotError(Exception):
    """Raiz de tudo que o projeto levanta de proposito."""


class ConfigError(ScrapingBotError):
    """Variavel de ambiente ausente ou invalida. Levantada no boot.  INF-5"""


class ScraperError(ScrapingBotError):
    """Falha ao obter o dado do alvo."""


class UpstreamUnavailable(ScraperError):
    """Rede, timeout, 5xx. Transitorio -- e esperado que aconteca."""


class UpstreamRejected(ScraperError):
    """403/429/401: o alvo nos recusou.

    Categoria propria porque a resposta operacional e o oposto da anterior:
    aqui insistir PIORA a situacao. Alimenta o backoff do scheduler.  BUG-17
    """

    def __init__(self, message: str, *, status: int, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class UnexpectedPayload(ScraperError):
    """O JSON veio, mas nao tem o formato esperado.

    Nao e falha de rede: e mudanca de contrato do alvo. Exige acao humana.
    """


class ImplausibleValue(ScrapingBotError):
    """Valor tecnicamente valido mas fora de qualquer faixa razoavel.  BUG-15"""

    def __init__(self, message: str, *, observed: int, previous: int | None) -> None:
        super().__init__(message)
        self.observed = observed
        self.previous = previous


class NotificationError(ScrapingBotError):
    """Nao foi possivel entregar a notificacao.  BUG-18"""


class StorageError(ScrapingBotError):
    """Falha de persistencia."""


class AlreadyRunningError(ScrapingBotError):
    """Ja existe outra instancia com o lock.  BUG-14"""
