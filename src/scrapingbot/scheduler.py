"""O laco: cadencia, backoff, sinais, janela de operacao e manutencao.

ARQ-6   SIGTERM/SIGINT ligam uma flag e o `Event.wait()` acorda na hora --
        o container passa a parar em 1s em vez de levar SIGKILL apos 10s
BUG-17  falha do alvo muda a cadencia. Antes, com 403 permanente, o bot
        continuava batendo ~60x/hora para sempre contra quem ja o rejeitou --
        e transformava uma falha temporaria em bloqueio permanente de IP
BUG-16  o ciclo mede a propria duracao e reporta quando estoura o orcamento
BUG-12  a manutencao do banco roda aqui dentro; nao ha segundo processo
REL-1   dead-man's switch: quem avisa passa a ser um terceiro que continua
        vivo quando o bot nao esta
REL-2   try/except de ultimo recurso: um erro em um ciclo nao mata o processo
ARQ-8   a janela de operacao vive NO CODIGO -- o container ignora o cron do host
"""

from __future__ import annotations

import logging
import random
import signal
import threading
from types import FrameType

import requests

from .clock import Clock
from .config import Settings
from .models import RunResult, RunStatus
from .notify.protocol import Channel, Notification, Notifier, Severity
from .observability.heartbeat import HealthTracker
from .observability.logging import new_run_id
from .service import MonitorService
from .storage.maintenance import Maintenance

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        *,
        service: MonitorService,
        settings: Settings,
        clock: Clock,
        notifier: Notifier,
        maintenance: Maintenance | None = None,
        health: HealthTracker | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.service = service
        self.settings = settings
        self.clock = clock
        self.notifier = notifier
        self.maintenance = maintenance
        self.health = health or HealthTracker(
            heartbeat_every=settings.heartbeat_every,
            failure_alert_threshold=settings.failure_alert_threshold,
            stale_alert_threshold=settings.stale_alert_threshold,
        )
        self._rng = rng or random.SystemRandom()
        self._shutdown = threading.Event()
        self._fora_da_janela: bool | None = None  # None = ainda nao sabemos
        self._deadman_session = requests.Session()

    # ------------------------------------------------------------- ciclo de vida
    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._handle_signal)
            except (ValueError, OSError):  # thread secundaria ou plataforma sem o sinal
                log.debug("Nao foi possivel instalar handler para %s", sig)

    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        log.info("Sinal %s recebido -- encerrando ao fim do ciclo", signal.Signals(signum).name)
        self._shutdown.set()

    def stop(self) -> None:
        self._shutdown.set()

    @property
    def stopping(self) -> bool:
        return self._shutdown.is_set()

    # ------------------------------------------------------------------- laco
    def run_forever(self, max_cycles: int | None = None) -> None:
        """`max_cycles` existe para o teste: o laco de producao passa None."""
        cycles = 0
        log.info("ScrapingBot iniciado. %s", self.settings.describe())

        while not self._shutdown.is_set():
            if max_cycles is not None and cycles >= max_cycles:
                break
            cycles += 1

            if not self._within_window():
                # Sem esta linha o bot fica horas em silencio absoluto e parece
                # morto -- indistinguivel de um processo travado. Loga so na
                # TRANSICAO, senao polui o log com uma linha por minuto.
                if self._fora_da_janela is not True:
                    self._fora_da_janela = True
                    log.info(
                        "Fora da janela de operacao (%s, %02dh-%02dh %s). "
                        "Aguardando; nenhuma coleta sera feita ate la.",
                        self._descreve_dias(),
                        self.settings.active_hour_start,
                        self.settings.active_hour_end,
                        self.settings.timezone.key,
                    )
                self._sleep(self._seconds_until_window())
                continue

            if self._fora_da_janela:
                log.info("Dentro da janela de operacao -- retomando as coletas")
            self._fora_da_janela = False

            run_id = new_run_id()
            try:
                result = self.service.run_once(run_id)
            except Exception:
                log.exception("Erro nao tratado no ciclo -- o laco continua")
                self.health.record_failure()
                self._sleep(self._next_delay(failed=True))
                continue

            self._observe(result)
            self._run_maintenance_if_due()
            self._sleep(self._next_delay(failed=not result.ok))

        log.info("Encerrado. %s", self.health.summary())

    # -------------------------------------------------------------- observacao
    def _observe(self, result: RunResult) -> None:
        if result.status is RunStatus.OK:
            self.health.record_success(
                payload_hash=result.payload_hash,
                latency_ms=result.duration_ms,
            )
            self._ping_deadman()  # so pinga quando REALMENTE coletou  REL-1
        else:
            self.health.record_failure()

        if result.duration_ms > self.settings.cycle_deadline_s * 1000:
            # BUG-16: um sistema periodico que nao mede o proprio tempo de ciclo
            # nao sabe se esta periodico.
            log.warning(
                "Ciclo estourou o orcamento: %dms (limite %.0fms)",
                result.duration_ms,
                self.settings.cycle_deadline_s * 1000,
            )

        if self.health.should_alert_failures():
            self._notify_log(
                title="Bot sem coletar",
                body=(
                    f"{self.health.consecutive_failures} ciclos consecutivos falharam. "
                    f"Ultimo erro: {result.error or 'desconhecido'}"
                ),
                severity=Severity.ERROR,
            )

        if self.health.should_alert_stale():
            # A resposta do alvo nao muda ha muito tempo. Isso NAO prova
            # bloqueio -- mas e o unico sinal observavel de que paramos de
            # receber dado fresco, seja por cache de borda, seja porque nos
            # colocaram numa resposta congelada.  SCR-7
            self._notify_log(
                title="Resposta do alvo congelada",
                body=(
                    f"As ultimas {self.health.consecutive_stale} coletas voltaram "
                    "byte a byte identicas. Ou o catalogo esta realmente parado, "
                    "ou estamos recebendo cache/resposta fixa. Vale conferir a "
                    "pagina no navegador e comparar com o que o bot recebe."
                ),
                severity=Severity.WARNING,
            )

        if self.health.should_heartbeat():
            self._notify_log(
                title="Heartbeat",
                body=self.health.summary(),
                severity=Severity.INFO,
                fields=(
                    ("Ultimo valor", str(result.observed_amount)),
                    ("Cache (Age)", str(result.cache_age) if result.cache_age is not None else "-"),
                ),
            )

    # ------------------------------------------------------------------ tempo
    def _next_delay(self, *, failed: bool) -> float:
        """Cadencia normal com jitter; backoff exponencial apos falhas.  BUG-17"""
        if not failed or self.health.consecutive_failures == 0:
            return self.clock.uniform(self.settings.interval_min_s, self.settings.interval_max_s)

        exponent = min(self.health.consecutive_failures - 1, 10)
        delay = min(self.settings.backoff_base_s * (2**exponent), self.settings.backoff_max_s)
        # Jitter de +-20%: sem ele, varias instancias (ou varios restarts)
        # sincronizam e voltam a bater no alvo todas ao mesmo tempo.
        jittered = delay * self._rng.uniform(0.8, 1.2)
        log.info(
            "Backoff: %d falha(s) seguida(s) -> proxima tentativa em %.0fs",
            self.health.consecutive_failures,
            jittered,
        )
        return jittered

    def _sleep(self, seconds: float) -> None:
        """Espera interrompivel: SIGTERM acorda o processo na hora.  ARQ-6"""
        self.clock.wait(self._shutdown, seconds)

    def _within_window(self) -> bool:
        """Janela de operacao, em horario local.  ARQ-8"""
        settings = self.settings
        if (
            settings.active_days is None
            and settings.active_hour_start == 0
            and (settings.active_hour_end == 24)
        ):
            return True
        local = settings.local(self.clock.now())
        if settings.active_days is not None and local.weekday() not in settings.active_days:
            return False
        return settings.active_hour_start <= local.hour < settings.active_hour_end

    def _descreve_dias(self) -> str:
        """Traduz `active_days` para algo legivel no log."""
        if self.settings.active_days is None:
            return "todos os dias"
        nomes = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
        return ", ".join(nomes[dia] for dia in sorted(self.settings.active_days))

    def _seconds_until_window(self) -> float:
        """Dorme ate a proxima checagem, nunca mais que 15 minutos.

        Dormir ate exatamente a virada seria mais eficiente, mas 15 minutos
        mantem o processo responsivo a mudanca de fuso/horario de verao sem
        codigo de calendario.
        """
        return min(900.0, max(60.0, self.settings.interval_max_s))

    # ------------------------------------------------------------ manutencao
    def _run_maintenance_if_due(self) -> None:
        if self.maintenance is None:
            return
        try:
            if not self.maintenance.is_due(self.clock.now()):
                return
            report = self.maintenance.run(self.clock.now())
        except Exception:
            log.exception("Manutencao falhou")
            return
        if report.did_something:
            self._notify_log(
                title="Manutencao do banco",
                body=report.describe(),
                severity=Severity.INFO,
            )

    # -------------------------------------------------------------- dead-man
    def _ping_deadman(self) -> None:
        """Um GET a cada coleta bem-sucedida.  REL-1

        O heartbeat do Discord e enviado PELO PROPRIO BOT: se o processo cair,
        o container for morto pelo OOM killer ou o host reiniciar, o sinal nao
        e um alerta, e SILENCIO -- e silencio e o que ninguem percebe. Aqui a
        logica se inverte: um terceiro (healthchecks.io, Cronitor) alerta pela
        AUSENCIA do ping. Tres linhas, e o item de maior retorno da auditoria.
        """
        url = self.settings.deadman_url
        if not url:
            return
        try:
            self._deadman_session.get(url, timeout=5)
        except requests.RequestException as exc:
            log.debug("Ping do dead-man falhou: %s", type(exc).__name__)

    # ------------------------------------------------------------- utilitario
    def _notify_log(
        self,
        *,
        title: str,
        body: str,
        severity: Severity,
        fields: tuple[tuple[str, str], ...] = (),
    ) -> None:
        from .errors import NotificationError

        try:
            self.notifier.send(
                Notification(
                    title=title,
                    body=body,
                    channel=Channel.LOG,
                    severity=severity,
                    fields=fields,
                    timestamp=self.clock.now(),
                )
            )
        except NotificationError as exc:
            log.warning("Notificacao operacional nao entregue: %s", exc)
