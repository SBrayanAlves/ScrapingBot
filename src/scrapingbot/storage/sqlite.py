"""Implementacao SQLite do Repository.

BUG-10  o context manager e dono da transacao: commit no sucesso, rollback na
        excecao, close no finally. Sumiu todo `conn.commit()` dos chamadores
ARQ-2   o SQL vive aqui e em nenhum outro lugar; `service.py` nao abre cursor
ARQ-7   `os.makedirs` deixou de rodar no import
DAT-8   PRAGMAs completos para o modo WAL
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from ..errors import StorageError
from ..models import Event, EventKind, RunResult, Snapshot
from .migrations import apply_migrations

log = logging.getLogger(__name__)


def _parse_dt(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class SqliteRepository:
    """Repositorio concreto. Cria o diretorio e migra no `setup()`, nao no import."""

    def __init__(self, db_path: Path, *, busy_timeout_s: float = 7.0) -> None:
        self.db_path = Path(db_path)
        self._busy_timeout_ms = int(busy_timeout_s * 1000)

    # ------------------------------------------------------------------ boot
    def setup(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)  # ARQ-7
        with self.connection() as conn:
            # journal_mode e persistente no arquivo -- basta uma vez, no setup.
            conn.execute("PRAGMA journal_mode=WAL")
            # auto_vacuum precisa ser definido antes do banco ter paginas.  DAT-7
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        with self.connection() as conn:
            version = apply_migrations(conn)
        log.info("Banco pronto em %s (schema v%d)", self.db_path, version)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Conexao + transacao. Uma excecao aqui faz rollback POR INTENCAO."""
        conn = sqlite3.connect(self.db_path, timeout=self._busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")  # DAT-8
            conn.execute("PRAGMA synchronous=NORMAL")  # seguro com WAL, bem menos fsync
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise StorageError(str(exc)) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -------------------------------------------------------------- snapshots
    def last_snapshot(self) -> Snapshot | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id, observed_at, amount, payload_hash "
                "FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return Snapshot(
            id=row["id"],
            observed_at=_parse_dt(row["observed_at"]),
            amount=row["amount"],
            payload_hash=row["payload_hash"],
        )

    def save_snapshot(self, snapshot: Snapshot) -> Snapshot:
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO snapshots (observed_at, amount, payload_hash) VALUES (?, ?, ?)",
                (snapshot.observed_at.isoformat(), snapshot.amount, snapshot.payload_hash),
            )
            new_id = cursor.lastrowid
        return Snapshot(
            id=new_id,
            observed_at=snapshot.observed_at,
            amount=snapshot.amount,
            payload_hash=snapshot.payload_hash,
        )

    # ----------------------------------------------------------------- outbox
    def save_event(self, event: Event) -> Event:
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO events (observed_at, kind, previous, current, delta, notified) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                (
                    event.observed_at.isoformat(),
                    event.kind.value,
                    event.previous,
                    event.current,
                    event.delta,
                ),
            )
            new_id = cursor.lastrowid
        return Event(
            id=new_id,
            observed_at=event.observed_at,
            kind=event.kind,
            previous=event.previous,
            current=event.current,
            delta=event.delta,
            notified=False,
        )

    def mark_notified(self, event_id: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE events SET notified = 1, notified_at = ?, last_error = NULL WHERE id = ?",
                (datetime.now(UTC).isoformat(), event_id),
            )

    def mark_notification_failed(self, event_id: int, error: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE events SET attempts = attempts + 1, last_error = ? WHERE id = ?",
                (error[:500], event_id),
            )

    def pending_events(self, limit: int = 20) -> list[Event]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id, observed_at, kind, previous, current, delta "
                "FROM events WHERE notified = 0 ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Event(
                id=row["id"],
                observed_at=_parse_dt(row["observed_at"]),
                kind=EventKind(row["kind"]),
                previous=row["previous"],
                current=row["current"],
                delta=row["delta"],
                notified=False,
            )
            for row in rows
        ]

    # ------------------------------------------------------------------- runs
    def save_run(self, run: RunResult) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO runs "
                "(run_id, started_at, status, duration_ms, observed_amount, cache_age, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.started_at.isoformat(),
                    run.status.value,
                    run.duration_ms,
                    run.observed_amount,
                    run.cache_age,
                    run.error[:500] if run.error else None,
                ),
            )

    def last_successful_run_at(self) -> datetime | None:
        """Base do HEALTHCHECK do container: "coletou nos ultimos N minutos?".

        So e respondivel porque `runs` grava tambem os ciclos sem novidade.
        INF-6 depende de DAT-1.
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT started_at FROM runs WHERE status = 'ok' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return _parse_dt(row["started_at"]) if row else None


class InMemoryRepository:
    """Repositorio falso para os testes -- mesma interface, zero I/O.  ENG-1"""

    def __init__(self) -> None:
        self.snapshots: list[Snapshot] = []
        self.events: list[Event] = []
        self.runs: list[RunResult] = []
        self._next_id = 1

    def _take_id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def last_snapshot(self) -> Snapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    def save_snapshot(self, snapshot: Snapshot) -> Snapshot:
        stored = Snapshot(
            id=self._take_id(),
            observed_at=snapshot.observed_at,
            amount=snapshot.amount,
            payload_hash=snapshot.payload_hash,
        )
        self.snapshots.append(stored)
        return stored

    def save_event(self, event: Event) -> Event:
        stored = Event(
            id=self._take_id(),
            observed_at=event.observed_at,
            kind=event.kind,
            previous=event.previous,
            current=event.current,
            delta=event.delta,
            notified=False,
        )
        self.events.append(stored)
        return stored

    def mark_notified(self, event_id: int) -> None:
        for index, event in enumerate(self.events):
            if event.id == event_id:
                self.events[index] = Event(
                    id=event.id,
                    observed_at=event.observed_at,
                    kind=event.kind,
                    previous=event.previous,
                    current=event.current,
                    delta=event.delta,
                    notified=True,
                )

    def mark_notification_failed(self, _event_id: int, _error: str) -> None:
        # O fake nao precisa contabilizar tentativas -- so o SQLite precisa.
        return None

    def pending_events(self, limit: int = 20) -> list[Event]:
        return [event for event in self.events if not event.notified][:limit]

    def save_run(self, run: RunResult) -> None:
        self.runs.append(run)
