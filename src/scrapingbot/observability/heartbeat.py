"""Saude do sistema: heartbeat, falhas consecutivas e suspeita de bloqueio.

ARQ-5  um unico contador, em um lugar so (antes eram dois `_pass`/`_WARNING`
       identicos em main.py e scraper.py, fadados a dessincronizar)
OBS-5  o heartbeat dizia que o bot estava VIVO, nao que estava FUNCIONANDO:
       com 403 permanente voce continuava recebendo [HEALTHBEAT] para sempre
SCR-7  novo: detecta payload congelado, que e a assinatura de um soft-block
       ou de cache do CDN -- exatamente a hipotese "o site so manda URL antiga"
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HealthTracker:
    """Estado de saude entre ciclos. Puro: nao faz I/O, so contabiliza."""

    heartbeat_every: int = 15
    failure_alert_threshold: int = 5
    stale_alert_threshold: int = 30

    cycles: int = 0
    consecutive_failures: int = 0
    consecutive_stale: int = 0
    total_runs: int = 0
    total_failures: int = 0
    _failure_alerted: bool = field(default=False, repr=False)
    _stale_alerted: bool = field(default=False, repr=False)
    _last_hash: str | None = field(default=None, repr=False)
    latencies: list[int] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------- registro
    def record_success(self, *, payload_hash: str | None = None, latency_ms: int = 0) -> None:
        self.total_runs += 1
        self.cycles += 1
        self.consecutive_failures = 0
        self._failure_alerted = False
        self.latencies.append(latency_ms)
        del self.latencies[:-200]  # janela deslizante: memoria nao cresce

        if payload_hash is not None:
            if payload_hash == self._last_hash:
                self.consecutive_stale += 1
            else:
                self.consecutive_stale = 0
                self._stale_alerted = False
            self._last_hash = payload_hash

    def record_failure(self) -> None:
        self.total_runs += 1
        self.total_failures += 1
        self.cycles += 1
        self.consecutive_failures += 1

    # ------------------------------------------------------------- decisoes
    def should_heartbeat(self) -> bool:
        """A cada N ciclos, e so quando o bot esta realmente coletando."""
        if self.heartbeat_every <= 0 or self.cycles < self.heartbeat_every:
            return False
        self.cycles = 0
        return True

    def should_alert_failures(self) -> bool:
        """Dispara UMA vez ao cruzar o limiar e cala ate recuperar.

        Sem esse "cala ate recuperar", uma queda de 6 horas do alvo vira 360
        mensagens no Discord e o canal e silenciado -- que e o oposto do
        objetivo. Meia duzia de linhas para 90% do valor de um circuit breaker.
        """
        if self.consecutive_failures >= self.failure_alert_threshold and not self._failure_alerted:
            self._failure_alerted = True
            return True
        return False

    def should_alert_stale(self) -> bool:
        """N respostas byte-a-byte identicas seguidas.

        Nao prova bloqueio, mas e o unico sinal observavel de que o alvo parou
        de nos dar dado fresco -- seja por cache de borda, seja porque nos
        colocaram em uma resposta congelada.
        """
        if self.stale_alert_threshold <= 0:
            return False
        if self.consecutive_stale >= self.stale_alert_threshold and not self._stale_alerted:
            self._stale_alerted = True
            return True
        return False

    # -------------------------------------------------------------- metrica
    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return 1.0 - (self.total_failures / self.total_runs)

    @property
    def latency_p95_ms(self) -> int:
        """p95 da janela recente. Sobe muito antes de o alvo comecar a recusar."""
        if not self.latencies:
            return 0
        ordered = sorted(self.latencies)
        index = min(len(ordered) - 1, int(len(ordered) * 0.95))
        return ordered[index]

    def summary(self) -> str:
        return (
            f"ciclos={self.total_runs} sucesso={self.success_rate:.1%} "
            f"p95={self.latency_p95_ms}ms falhas_seguidas={self.consecutive_failures} "
            f"payload_repetido={self.consecutive_stale}"
        )
