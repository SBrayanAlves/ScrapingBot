"""Migracoes de schema com `PRAGMA user_version`.  ENG-5

`CREATE TABLE IF NOT EXISTS` cobre banco novo e so. No dia em que voce
adiciona uma coluna, todo banco existente continua com o schema velho e o
INSERT falha em producao. Nao precisa de Alembic: uma lista de funcoes
aplicadas em ordem, dentro de uma transacao, resolve.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

log = logging.getLogger(__name__)

Migration = Callable[[sqlite3.Connection], None]


def _v1_baseline(conn: sqlite3.Connection) -> None:
    """Separa o que estava fundido numa tabela so.  DAT-1 / DAT-2 / DAT-3"""
    conn.executescript(
        """
        -- Uma linha por OBSERVACAO. O nome antigo (`products`) mentia: a tabela
        -- nunca guardou produtos, guarda uma contagem.  DAT-3
        CREATE TABLE IF NOT EXISTS snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at  TEXT    NOT NULL,   -- ISO-8601 UTC com offset  DAT-2/BUG-7
            amount       INTEGER NOT NULL,
            payload_hash TEXT
        );

        -- Uma linha por MUDANCA. `notified` e a coluna que transforma entrega
        -- "melhor esforco" em entrega garantida.  BUG-13
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at  TEXT    NOT NULL,
            kind         TEXT    NOT NULL,
            previous     INTEGER,
            current      INTEGER NOT NULL,
            delta        INTEGER NOT NULL,
            notified     INTEGER NOT NULL DEFAULT 0,
            notified_at  TEXT,
            attempts     INTEGER NOT NULL DEFAULT 0,
            last_error   TEXT
        );

        -- Uma linha por CICLO, com ou sem novidade. Sem ela, "nada aconteceu"
        -- e "o bot morreu" sao indistinguiveis -- e o HEALTHCHECK do container
        -- nao tem em que se basear.  DAT-1 / INF-6
        CREATE TABLE IF NOT EXISTS runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT    NOT NULL,
            started_at      TEXT    NOT NULL,
            status          TEXT    NOT NULL,
            duration_ms     INTEGER NOT NULL,
            observed_amount INTEGER,
            cache_age       INTEGER,
            error           TEXT
        );

        -- Resumo por hora. Agregado ANTES de descartar o detalhe, entao o
        -- historico de saude sobrevive a retencao.  DAT-5
        CREATE TABLE IF NOT EXISTS run_hourly (
            hour            TEXT PRIMARY KEY,   -- "2026-08-31T14"
            runs            INTEGER NOT NULL,
            failures        INTEGER NOT NULL,
            latency_p95_ms  INTEGER,
            min_amount      INTEGER,
            max_amount      INTEGER
        );

        -- Sem indice, o DELETE da limpeza e full scan. Com ~1.400 linhas/dia em
        -- `runs` isso deixa de ser irrelevante rapido. O momento de criar o
        -- indice e junto com a tabela, nao depois do problema.  DAT-4
        CREATE INDEX IF NOT EXISTS idx_snapshots_observed_at ON snapshots(observed_at);
        CREATE INDEX IF NOT EXISTS idx_events_observed_at    ON events(observed_at);
        CREATE INDEX IF NOT EXISTS idx_events_pending        ON events(notified)
            WHERE notified = 0;
        CREATE INDEX IF NOT EXISTS idx_runs_started_at       ON runs(started_at);
        """
    )


def _v2_import_legacy_products(conn: sqlite3.Connection) -> None:
    """Importa a tabela `products` da v1 do bot, se ela existir neste arquivo.

    O historico antigo tem apenas granularidade de dia (o `strftime("%Y-%m-%d")`
    jogava a hora fora). Marcamos as linhas importadas com meio-dia UTC para
    deixar explicito que a hora e desconhecida, em vez de fingir precisao.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='products'"
    ).fetchone()
    if not exists:
        return

    rows = conn.execute("SELECT amount, date FROM products ORDER BY id").fetchall()
    if not rows:
        return

    conn.executemany(
        "INSERT INTO snapshots (observed_at, amount, payload_hash) VALUES (?, ?, NULL)",
        [(f"{date}T12:00:00+00:00", amount) for amount, date in rows],
    )
    conn.execute("ALTER TABLE products RENAME TO products_legacy_v1")
    log.info("Migracao: %d linhas de `products` importadas para `snapshots`", len(rows))


def _v3_meta(conn: sqlite3.Connection) -> None:
    """Chave/valor para estado operacional (ex.: quando a manutencao rodou).

    Existe como migracao separada, e nao dentro da v1, de proposito: e a prova
    executavel de que o mecanismo de migracao funciona em banco ja povoado.
    """
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


MIGRATIONS: tuple[Migration, ...] = (
    _v1_baseline,
    _v2_import_legacy_products,
    _v3_meta,
)


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Aplica o que faltar, em ordem. Devolve a versao final.

    Cada migracao roda em sua propria transacao: se a terceira falhar, as duas
    primeiras continuam aplicadas e a `user_version` reflete a verdade.
    """
    current: int = conn.execute("PRAGMA user_version").fetchone()[0]
    target = len(MIGRATIONS)

    if current > target:
        raise RuntimeError(
            f"Banco na versao {current}, mas este codigo so conhece ate {target}. "
            "Voce esta rodando uma versao antiga do bot contra um banco novo."
        )

    for version in range(current, target):
        migration = MIGRATIONS[version]
        log.info("Aplicando migracao %d (%s)", version + 1, migration.__name__)
        with conn:  # commit no sucesso, rollback na excecao
            migration(conn)
            conn.execute(f"PRAGMA user_version = {version + 1}")

    return target
