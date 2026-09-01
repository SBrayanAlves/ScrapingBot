"""Regra de negocio.  ARQ-1 / ARQ-2

O `rn_service` antigo abria cursor, escrevia SELECT, dois INSERT identicos e
chamava commit, tudo misturado com a decisao. Aqui a decisao e uma funcao pura
(`decide`) e a orquestracao conversa com tres interfaces -- Fetcher, Repository,
Notifier. Nao ha SQL, nao ha `requests`, nao ha Discord neste arquivo.

E por isso que o teste mais valioso do projeto ("subiu 3 produtos, entao
notifica UMA vez e persiste") cabe em cinco linhas, sem rede e sem banco.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from .clock import Clock
from .errors import (
    NotificationError,
    ScraperError,
    StorageError,
    UnexpectedPayload,
    UpstreamRejected,
    UpstreamUnavailable,
)
from .fetch.protocol import Fetcher
from .models import Event, EventKind, FetchResult, RunResult, RunStatus, Snapshot
from .notify.protocol import Channel, Notification, Notifier, Severity
from .storage.protocol import Repository

log = logging.getLogger(__name__)

# Placeholder de timestamp: `decide` e pura e nao conhece o relogio.
# Quem grava o evento e que carimba a hora.
_UNSET = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Thresholds:
    """As decisoes de negocio, nomeadas.

    O `> 2` do codigo antigo era um numero magico sem explicacao -- e, pior,
    guardava a notificacao E o INSERT. Aumentos de 1 ou 2 nunca eram
    persistidos: o banco ficava defasado e o contador acumulava. Se o alvo
    publica de um em um, o alerta so disparava depois de tres publicacoes.
    E EXATAMENTE ISSO QUE O CLIENTE PERCEBE COMO "NOTIFICACAO ATRASADA".  BUG-8
    """

    alert_delta: int = 1  # delta minimo para acordar alguem
    max_plausible_delta: int = 200  # acima disto e anomalia, nao noticia  BUG-15
    max_plausible_amount: int = 100_000


def decide(previous: Snapshot | None, current: int, limits: Thresholds) -> Event | None:
    """Funcao PURA: dado o estado anterior e o valor observado, o que aconteceu?

    Sem I/O, sem relogio, sem log. Devolve o evento a registrar, ou None quando
    nao ha nada digno de nota. O `observed_at` e preenchido pelo chamador.
    """
    if previous is None:
        return Event(
            observed_at=_UNSET,
            kind=EventKind.FIRST_RUN,
            previous=None,
            current=current,
            delta=0,
        )

    delta = current - previous.amount

    if delta <= 0:
        # Queda ou estabilidade nao geram evento -- mas o snapshot e gravado
        # de qualquer jeito pelo chamador. Persistir e decidir sao coisas
        # separadas; foi juntar as duas que criou o BUG-8.
        return None

    if delta > limits.max_plausible_delta or current > limits.max_plausible_amount:
        # Um salto absurdo quase nunca e "chegou estoque": e o alvo mudando o
        # contrato da API. Sem isto, `50000 - 480` viraria um @everyone
        # anunciando 49.520 produtos.  BUG-15
        return Event(
            observed_at=_UNSET,
            kind=EventKind.ANOMALY,
            previous=previous.amount,
            current=current,
            delta=delta,
        )

    if delta < limits.alert_delta:
        return None

    return Event(
        observed_at=_UNSET,
        kind=EventKind.INCREASE,
        previous=previous.amount,
        current=current,
        delta=delta,
    )


class MonitorService:
    """Orquestra um ciclo: coleta -> decide -> persiste -> entrega."""

    def __init__(
        self,
        *,
        fetcher: Fetcher,
        repository: Repository,
        notifier: Notifier,
        clock: Clock,
        thresholds: Thresholds | None = None,
        page_url: str | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.repo = repository
        self.notifier = notifier
        self.clock = clock
        self.limits = thresholds or Thresholds()
        self.page_url = page_url

    # ------------------------------------------------------------------ ciclo
    def run_once(self, run_id: str) -> RunResult:
        started_at = self.clock.now()
        started_mono = self.clock.monotonic()

        def finish(
            status: RunStatus,
            *,
            amount: int | None = None,
            error: str | None = None,
            cache_age: int | None = None,
            payload_hash: str | None = None,
            events: list[Event] | None = None,
        ) -> RunResult:
            result = RunResult(
                run_id=run_id,
                started_at=started_at,
                status=status,
                duration_ms=int((self.clock.monotonic() - started_mono) * 1000),
                observed_amount=amount,
                error=error,
                cache_age=cache_age,
                payload_hash=payload_hash,
                events=events or [],
            )
            try:
                self.repo.save_run(result)  # DAT-1: TODO ciclo vira linha
            except StorageError:
                log.exception("Nao foi possivel registrar o ciclo")
            return result

        # 1. A fila de entrega vem primeiro: um alerta de ha 5 minutos que nao
        #    saiu importa mais que a coleta de agora.  BUG-13
        self._flush_pending()

        # 2. Coleta
        try:
            observation = self.fetcher.fetch()
        except UpstreamRejected as exc:
            log.warning("Alvo recusou a coleta: %s", exc)
            return finish(RunStatus.UPSTREAM_REJECTED, error=str(exc))
        except UpstreamUnavailable as exc:
            log.warning("Alvo indisponivel: %s", exc)
            return finish(RunStatus.UPSTREAM_UNAVAILABLE, error=str(exc))
        except UnexpectedPayload as exc:
            # Categoria propria de proposito: isto NAO e falha de rede. Significa
            # que o alvo mudou o contrato e o bot esta cego.  OBS-4
            log.error("Payload inesperado -- o bot pode estar cego: %s", exc)
            self._try_notify(
                Notification(
                    title="Formato da resposta mudou",
                    body=(
                        "O campo esperado sumiu do JSON do alvo. O bot nao esta "
                        "coletando dado nenhum ate isso ser ajustado."
                    ),
                    channel=Channel.LOG,
                    severity=Severity.ERROR,
                    fields=(("Detalhe", str(exc)[:900]),),
                    timestamp=started_at,
                )
            )
            return finish(RunStatus.UNEXPECTED_PAYLOAD, error=str(exc))
        except ScraperError as exc:
            log.exception("Falha de coleta nao classificada")
            return finish(RunStatus.ERROR, error=str(exc))

        if observation.amount < 0:
            return finish(
                RunStatus.IMPLAUSIBLE,
                amount=observation.amount,
                error=f"contagem negativa: {observation.amount}",
                cache_age=observation.cache_age,
            )

        # 3. SEMPRE persiste o observado. Persistir e notificar sao decisoes
        #    independentes -- foi juntar as duas que gerou o BUG-8.
        previous = self.repo.last_snapshot()
        self.repo.save_snapshot(
            Snapshot(
                observed_at=started_at,
                amount=observation.amount,
                payload_hash=observation.payload_hash,
            )
        )

        # 4. Decide (puro) e entrega
        event = decide(previous, observation.amount, self.limits)
        events: list[Event] = []
        if event is not None:
            stored = self.repo.save_event(
                Event(
                    observed_at=started_at,
                    kind=event.kind,
                    previous=event.previous,
                    current=event.current,
                    delta=event.delta,
                )
            )
            events.append(stored)
            self._deliver(stored, observation)

        return finish(
            RunStatus.OK,
            amount=observation.amount,
            cache_age=observation.cache_age,
            payload_hash=observation.payload_hash,
            events=events,
        )

    # ------------------------------------------------------------- entrega
    def _deliver(self, event: Event, observation: FetchResult | None = None) -> None:
        """Tenta entregar; o evento so sai da fila quando o Discord confirma."""
        if event.id is None:
            return
        try:
            self.notifier.send(self._render(event, observation))
        except NotificationError as exc:
            # O evento continua com notified=0 e sera tentado de novo no proximo
            # ciclo. Antes, o alerta simplesmente sumia -- e como o banco ja
            # tinha sido atualizado, aquele lote nunca mais seria notificado.
            log.warning("Entrega falhou, evento %d permanece na fila: %s", event.id, exc)
            self.repo.mark_notification_failed(event.id, str(exc))
        else:
            self.repo.mark_notified(event.id)

    def _flush_pending(self) -> None:
        try:
            pending = self.repo.pending_events()
        except StorageError:
            log.exception("Nao foi possivel ler a fila de eventos pendentes")
            return
        if not pending:
            return
        log.info("Reprocessando %d evento(s) pendente(s)", len(pending))
        for event in pending:
            self._deliver(event)

    def _render(self, event: Event, observation: FetchResult | None = None) -> Notification:
        """Traduz evento de dominio em mensagem. Aqui e onde o PRD-2 acontece."""
        extra_fields: tuple[tuple[str, str], ...] = ()
        if observation is not None:
            extra_fields = (
                ("Latencia", f"{observation.latency_ms} ms"),
                ("Cache do alvo", _describe_cache(observation)),
            )

        if event.kind is EventKind.INCREASE:
            plural = "PRODUTOS" if event.delta > 1 else "PRODUTO"
            return Notification(
                title=f"{event.delta} {plural} no ar",
                body=(
                    f"O catalogo monitorado subiu de **{event.previous}** para **{event.current}**."
                ),
                channel=Channel.PUBLIC,
                severity=Severity.SUCCESS,
                fields=(
                    ("Antes", str(event.previous)),
                    ("Agora", str(event.current)),
                    ("Variacao", f"+{event.delta}"),
                ),
                mention=True,
                url=self.page_url,
                timestamp=event.observed_at,
                footer="ScrapingBot",
            )

        if event.kind is EventKind.ANOMALY:
            return Notification(
                title="Variacao implausivel ignorada",
                body=(
                    f"O valor saltou de **{event.previous}** para **{event.current}** "
                    f"(delta {event.delta:+d}). Isso quase sempre significa que o alvo "
                    "mudou o contrato da API, nao que entraram produtos. "
                    "Nenhum alerta foi enviado ao canal publico."
                ),
                channel=Channel.LOG,
                severity=Severity.WARNING,
                fields=(
                    ("Antes", str(event.previous)),
                    ("Agora", str(event.current)),
                    *extra_fields,
                ),
                timestamp=event.observed_at,
            )

        return Notification(
            title="Linha de base registrada",
            body=(
                f"Primeira coleta: **{event.current}** itens. A partir de agora as "
                "variacoes sao comparadas com este valor."
            ),
            channel=Channel.LOG,
            severity=Severity.INFO,
            timestamp=event.observed_at,
        )

    def _try_notify(self, notification: Notification) -> None:
        """Notificacao operacional: se falhar, so registra. Nao entra na fila."""
        try:
            self.notifier.send(notification)
        except NotificationError as exc:
            log.warning("Notificacao operacional nao entregue: %s", exc)


def _describe_cache(observation: FetchResult) -> str:
    parts = []
    if observation.cache_age is not None:
        parts.append(f"Age={observation.cache_age}s")
    if observation.cache_status:
        parts.append(observation.cache_status)
    return " ".join(parts) or "sem headers de cache"
