"""Fakes de Fetcher, Notifier e Clock.  ENG-1

Nenhum teste toca rede, disco (fora de tmp_path) ou Discord. A suite inteira
roda em menos de um segundo -- que e a diferenca entre uma suite que existe e
uma que ninguem executa.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from scrapingbot.clock import FakeClock
from scrapingbot.errors import NotificationError, ScraperError
from scrapingbot.models import FetchResult
from scrapingbot.notify.protocol import Notification
from scrapingbot.storage.sqlite import InMemoryRepository, SqliteRepository


class FakeFetcher:
    """Devolve valores de um roteiro. Um item pode ser int ou excecao."""

    def __init__(self, script: list[int | Exception] | None = None) -> None:
        self.script: list[int | Exception] = list(script or [])
        self.calls = 0
        self.closed = False

    def fetch(self) -> FetchResult:
        self.calls += 1
        if not self.script:
            raise ScraperError("roteiro do FakeFetcher esgotado")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return FetchResult(
            amount=item,
            payload_hash=f"hash-{item}",
            latency_ms=10,
            http_status=200,
        )

    def close(self) -> None:
        self.closed = True


class FakeNotifier:
    """Registra o que foi enviado. `fail_times` simula Discord fora do ar."""

    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[Notification] = []
        self.fail_times = fail_times
        self.attempts = 0

    def send(self, notification: Notification) -> None:
        self.attempts += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise NotificationError("Discord indisponivel (simulado)")
        self.sent.append(notification)

    @property
    def public(self) -> list[Notification]:
        return [n for n in self.sent if n.channel.value == "public"]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture
def sqlite_repo(tmp_path: Path) -> Iterator[SqliteRepository]:
    repository = SqliteRepository(tmp_path / "test.db")
    repository.setup()
    yield repository
