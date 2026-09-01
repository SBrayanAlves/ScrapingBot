"""Entrega no Discord via webhook.

BUG-4   toda requisicao tem timeout -- era o unico `requests` sem ele, e um
        Discord que aceitasse o TCP sem responder congelava o laco para sempre
SCR-4   429 e respeitado com `Retry-After`; o resto usa backoff exponencial;
        o `except` tambem dorme (antes as 3 tentativas saiam quase juntas)
BUG-18  `send` levanta em vez de devolver None em todos os desfechos
SCR-5   mencao configuravel: cargo opt-in no lugar de `@everyone`
PRD-2   embeds com cor por severidade, valor anterior -> novo e link
SEC-2   a URL do webhook nunca entra em mensagem de erro
"""

from __future__ import annotations

import logging
import random

import requests

from ..clock import Clock
from ..errors import NotificationError
from .protocol import Channel, Notification, Severity

log = logging.getLogger(__name__)

_COLORS: dict[Severity, int] = {
    Severity.INFO: 0x5865F2,  # blurple
    Severity.SUCCESS: 0x57F287,  # verde
    Severity.WARNING: 0xFEE75C,  # amarelo
    Severity.ERROR: 0xED4245,  # vermelho
}


class DiscordNotifier:
    """Cliente de webhook. Uma instancia serve aos dois canais."""

    def __init__(
        self,
        *,
        alert_webhook: str,
        log_webhook: str,
        clock: Clock,
        username: str = "ScrapingBot",
        mention: str = "",
        timeout_s: float = 10.0,
        retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self._webhooks = {Channel.PUBLIC: alert_webhook, Channel.LOG: log_webhook}
        self.clock = clock
        self.username = username
        self.mention = mention.strip()
        self.timeout_s = timeout_s
        self.retries = max(1, retries)
        self._session = session or requests.Session()

    # ------------------------------------------------------------------ envio
    def send(self, notification: Notification) -> None:
        webhook = self._webhooks[notification.channel]
        payload = self._build_payload(notification)
        last_error = "nenhuma tentativa executada"

        for attempt in range(1, self.retries + 1):
            try:
                response = self._session.post(webhook, json=payload, timeout=self.timeout_s)
            except requests.RequestException as exc:
                # Nunca interpolar `exc` cru: RequestException embute a URL
                # completa, e a URL do webhook E a credencial.  SEC-2
                last_error = f"{type(exc).__name__}"
                log.warning(
                    "Falha de rede ao notificar (tentativa %d/%d): %s",
                    attempt,
                    self.retries,
                    last_error,
                )
                self._sleep_before_retry(attempt)  # o `except` antigo nao dormia
                continue

            if response.status_code in (200, 204):
                return

            if response.status_code == 429:
                wait = self._retry_after(response)
                log.warning("Rate limit do Discord; aguardando %.1fs antes de repetir", wait)
                self.clock.sleep(wait)
                last_error = "HTTP 429 (rate limit)"
                continue

            if 400 <= response.status_code < 500:
                # 401/403/404 = webhook invalido ou revogado. Repetir nao ajuda.
                raise NotificationError(
                    f"Webhook rejeitou a mensagem: HTTP {response.status_code} "
                    "(webhook invalido, revogado ou payload malformado)"
                )

            last_error = f"HTTP {response.status_code}"
            log.warning("Discord respondeu %s (tentativa %d/%d)", last_error, attempt, self.retries)
            self._sleep_before_retry(attempt)

        raise NotificationError(f"Nao foi possivel entregar a notificacao: {last_error}")

    def _sleep_before_retry(self, attempt: int) -> None:
        """Backoff exponencial com jitter -- nao rajada de 3 tentativas juntas."""
        base = min(30.0, 2.0**attempt)
        self.clock.sleep(base + random.uniform(0, 0.5 * base))  # noqa: S311 - jitter, nao cripto

    def _retry_after(self, response: requests.Response) -> float:
        """O Discord manda `Retry-After` no header e/ou no corpo JSON."""
        header = response.headers.get("Retry-After")
        if header:
            try:
                return min(60.0, float(header))
            except ValueError:
                pass
        try:
            body = response.json()
            return min(60.0, float(body.get("retry_after", 5.0)))
        except (ValueError, AttributeError, TypeError):
            return 5.0

    # ---------------------------------------------------------------- payload
    def _build_payload(self, notification: Notification) -> dict[str, object]:
        embed: dict[str, object] = {
            "title": notification.title[:256],
            "description": notification.body[:4096],
            "color": _COLORS.get(notification.severity, _COLORS[Severity.INFO]),
        }
        if notification.url:
            embed["url"] = notification.url
        if notification.timestamp:
            embed["timestamp"] = notification.timestamp.isoformat()
        if notification.fields:
            embed["fields"] = [
                {"name": name[:256], "value": str(value)[:1024], "inline": True}
                for name, value in notification.fields[:25]
            ]
        if notification.footer:
            embed["footer"] = {"text": notification.footer[:2048]}

        payload: dict[str, object] = {
            "username": self.username,
            "embeds": [embed],
            # Sem isto, um embed com "@everyone" no texto ainda pingaria todos.
            # Mencao e decisao explicita, nunca efeito colateral do conteudo.
            "allowed_mentions": {"parse": []},
        }

        if notification.mention and self.mention:
            payload["content"] = self.mention
            payload["allowed_mentions"] = _allowed_mentions_for(self.mention)

        return payload


def _allowed_mentions_for(mention: str) -> dict[str, object]:
    """Libera exatamente o que foi configurado, e nada alem.  SCR-5"""
    if mention.startswith("<@&") and mention.endswith(">"):
        return {"parse": [], "roles": [mention[3:-1]]}
    if mention.startswith("<@") and mention.endswith(">"):
        return {"parse": [], "users": [mention[2:-1].lstrip("!")]}
    if mention in ("@everyone", "@here"):
        return {"parse": ["everyone"]}
    return {"parse": []}


class NullNotifier:
    """Descarta tudo. Para `--dry-run` e para os testes."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
        self.sent.append(notification)
        log.info("[dry-run] %s | %s", notification.title, notification.body)
