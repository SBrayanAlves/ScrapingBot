"""Manutencao do banco: agregacao, retencao, vacuum incremental e backup.

BUG-12  isto rodava em `cleanup.py`, agendado por um cron DO HOST que o
        container nao tem -- ou seja, retencao implementada e retencao zero na
        pratica. Agora e uma tarefa do proprio processo, disparada pelo laco
DAT-5   retencao em dois niveis: AGREGA antes de descartar, entao o historico
        de saude vira kilobytes por mes em vez de sumir
DAT-6   `VACUUM INTO` -- backup atomico e consistente sem parar o bot
DAT-7   `incremental_vacuum` na limpeza; VACUUM completo so mensal
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .sqlite import SqliteRepository

log = logging.getLogger(__name__)

_LAST_RUN_KEY = "maintenance.last_run_at"
_LAST_FULL_VACUUM_KEY = "maintenance.last_full_vacuum_at"


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    hours_aggregated: int = 0
    runs_deleted: int = 0
    snapshots_deleted: int = 0
    events_deleted: int = 0
    backup_path: Path | None = None
    full_vacuum: bool = False

    @property
    def did_something(self) -> bool:
        return bool(
            self.hours_aggregated
            or self.runs_deleted
            or self.snapshots_deleted
            or self.events_deleted
            or self.backup_path
        )

    def describe(self) -> str:
        parts = [
            f"horas_agregadas={self.hours_aggregated}",
            f"runs_removidos={self.runs_deleted}",
            f"snapshots_removidos={self.snapshots_deleted}",
            f"eventos_removidos={self.events_deleted}",
        ]
        if self.backup_path:
            parts.append(f"backup={self.backup_path.name}")
        if self.full_vacuum:
            parts.append("vacuum=completo")
        return " ".join(parts)


class Maintenance:
    """Tarefa diaria do bot. Sem segundo processo, sem segundo ponto de deploy."""

    def __init__(
        self,
        repo: SqliteRepository,
        *,
        retention_days: int,
        events_retention_days: int,
        backup_dir: Path,
        backup_keep: int,
    ) -> None:
        self.repo = repo
        self.retention_days = retention_days
        self.events_retention_days = events_retention_days
        self.backup_dir = Path(backup_dir)
        self.backup_keep = backup_keep

    # -------------------------------------------------------------- agenda
    def last_run_at(self) -> datetime | None:
        with self.repo.connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (_LAST_RUN_KEY,)).fetchone()
        return datetime.fromisoformat(row["value"]) if row else None

    def is_due(self, now: datetime, *, every_hours: int = 24) -> bool:
        last = self.last_run_at()
        return last is None or (now - last) >= timedelta(hours=every_hours)

    def _stamp(self, key: str, moment: datetime) -> None:
        with self.repo.connection() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, moment.isoformat()),
            )

    # ------------------------------------------------------------ execucao
    def run(self, now: datetime | None = None) -> MaintenanceReport:
        now = now or datetime.now(UTC)
        run_cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        event_cutoff = (now - timedelta(days=self.events_retention_days)).isoformat()

        with self.repo.connection() as conn:
            # 1. AGREGA antes de apagar. Esta e a diferenca entre "retencao" e
            #    "perda de dados": o detalhe some, a serie historica fica.
            aggregated = conn.execute(
                """
                INSERT INTO run_hourly (hour, runs, failures, latency_p95_ms,
                                        min_amount, max_amount)
                SELECT substr(started_at, 1, 13)                            AS hour,
                       COUNT(*)                                            AS runs,
                       SUM(CASE WHEN status <> 'ok' THEN 1 ELSE 0 END)     AS failures,
                       MAX(duration_ms)                                    AS latency_p95_ms,
                       MIN(observed_amount)                                AS min_amount,
                       MAX(observed_amount)                                AS max_amount
                  FROM runs
                 WHERE started_at < ?
                 GROUP BY hour
                ON CONFLICT(hour) DO UPDATE SET
                       runs           = run_hourly.runs + excluded.runs,
                       failures       = run_hourly.failures + excluded.failures,
                       latency_p95_ms = MAX(run_hourly.latency_p95_ms, excluded.latency_p95_ms),
                       min_amount     = MIN(run_hourly.min_amount, excluded.min_amount),
                       max_amount     = MAX(run_hourly.max_amount, excluded.max_amount)
                """,
                (run_cutoff,),
            ).rowcount

            runs_deleted = conn.execute("DELETE FROM runs WHERE started_at < ?", (run_cutoff,))
            runs_removed = runs_deleted.rowcount

            snaps_removed = conn.execute(
                "DELETE FROM snapshots WHERE observed_at < ?", (run_cutoff,)
            ).rowcount

            # Eventos entregues sao o historico de negocio: ficam por anos.
            # Pendentes NUNCA sao apagados -- sao a fila de entrega.  BUG-13
            events_removed = conn.execute(
                "DELETE FROM events WHERE observed_at < ? AND notified = 1", (event_cutoff,)
            ).rowcount

        backup = self._backup(now)
        full_vacuum = self._vacuum(now)
        self._stamp(_LAST_RUN_KEY, now)

        report = MaintenanceReport(
            hours_aggregated=max(0, aggregated),
            runs_deleted=max(0, runs_removed),
            snapshots_deleted=max(0, snaps_removed),
            events_deleted=max(0, events_removed),
            backup_path=backup,
            full_vacuum=full_vacuum,
        )
        log.info("Manutencao concluida: %s", report.describe())
        return report

    # -------------------------------------------------------------- backup
    def _backup(self, now: datetime) -> Path | None:
        """`VACUUM INTO`: uma linha de SQL, atomico, sem parar o bot.  DAT-6"""
        if self.backup_keep <= 0:
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        target = self.backup_dir / f"scrapingbot-{now:%Y-%m-%d}.db"
        target.unlink(missing_ok=True)  # VACUUM INTO recusa destino existente
        with self.repo.connection() as conn:
            conn.execute("VACUUM INTO ?", (str(target),))

        # Rotacao: manter apenas as N copias mais recentes.
        backups = sorted(self.backup_dir.glob("scrapingbot-*.db"), reverse=True)
        for stale in backups[self.backup_keep :]:
            stale.unlink(missing_ok=True)
        return target

    def _vacuum(self, now: datetime) -> bool:
        """Incremental sempre; completo no maximo uma vez por mes.  DAT-7"""
        with self.repo.connection() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (_LAST_FULL_VACUUM_KEY,)
            ).fetchone()
        last_full = datetime.fromisoformat(row["value"]) if row else None

        if last_full is None or (now - last_full) >= timedelta(days=30):
            # VACUUM reescreve o banco inteiro sob lock exclusivo -- por isso
            # nao roda a cada limpeza. Fora de transacao, senao o SQLite recusa.
            import sqlite3

            conn = sqlite3.connect(self.repo.db_path)
            try:
                conn.isolation_level = None
                conn.execute("VACUUM")
            finally:
                conn.close()
            self._stamp(_LAST_FULL_VACUUM_KEY, now)
            return True

        with self.repo.connection() as conn:
            conn.execute("PRAGMA incremental_vacuum")
        return False
