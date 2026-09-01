"""Tempo injetavel.  ENG-8

Todo comportamento interessante deste sistema e temporal: "alerta a cada N
ciclos", "faz backoff crescente", "limpa depois de N dias". Com `time.sleep` e
`datetime.now` chamados direto nos modulos, nenhum deles da para testar sem
esperar de verdade. Com um Clock injetado, a suite roda em milissegundos.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Fonte unica de tempo do sistema."""

    def now(self) -> datetime:
        """Instante atual, sempre timezone-aware em UTC.  BUG-7 / DAT-2"""
        ...

    def monotonic(self) -> float:
        """Relogio monotonico -- para medir duracao, nunca `now()`."""
        ...

    def sleep(self, seconds: float) -> None: ...

    def wait(self, event: threading.Event, seconds: float) -> bool:
        """Espera interrompivel. Devolve True se o evento foi acionado.  ARQ-6"""
        ...

    def uniform(self, low: float, high: float) -> float:
        """Sorteio uniforme -- injetavel para tornar o jitter deterministico."""
        ...


class SystemClock:
    """Implementacao real."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.SystemRandom()

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def wait(self, event: threading.Event, seconds: float) -> bool:
        return event.wait(max(0.0, seconds))

    def uniform(self, low: float, high: float) -> float:
        return self._rng.uniform(low, high)


class FakeClock:
    """Clock controlado pelo teste. O tempo so anda quando o teste manda."""

    def __init__(self, start: datetime | None = None, *, uniform_at: float = 0.5) -> None:
        self._now = start or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        self._mono = 0.0
        self.slept: list[float] = []
        self._uniform_at = uniform_at  # 0.0 = minimo, 1.0 = maximo da faixa

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now += timedelta(seconds=seconds)
        self._mono += seconds

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.advance(seconds)

    def wait(self, event: threading.Event, seconds: float) -> bool:
        self.slept.append(seconds)
        self.advance(seconds)
        return event.is_set()

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self._uniform_at
