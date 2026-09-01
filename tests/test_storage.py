"""Migracoes, transacoes, outbox e retencao."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from scrapingbot.errors import StorageError
from scrapingbot.models import Event, EventKind, RunResult, RunStatus, Snapshot
from scrapingbot.storage.maintenance import Maintenance
from scrapingbot.storage.migrations import MIGRATIONS, apply_migrations
from scrapingbot.storage.sqlite import SqliteRepository

NOW = datetime(2026, 8, 31, 14, 30, tzinfo=UTC)


# ------------------------------------------------------------------ migracoes
def test_setup_aplica_todas_as_migracoes(tmp_path):
    repo = SqliteRepository(tmp_path / "db.sqlite")
    repo.setup()
    with repo.connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_setup_e_idempotente(tmp_path):
    repo = SqliteRepository(tmp_path / "db.sqlite")
    repo.setup()
    repo.setup()
    with repo.connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)


def test_banco_mais_novo_que_o_codigo_e_recusado(tmp_path):
    """Rodar codigo antigo contra banco novo corrompe dado em silencio.  ENG-5"""
    path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 5}")
    conn.commit()
    with pytest.raises(RuntimeError, match="versao"):
        apply_migrations(conn)
    conn.close()


def test_historico_da_v1_e_importado(tmp_path):
    """O banco antigo tem dados reais; a migracao nao pode descarta-los."""
    path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, amount INTEGER, date TEXT)")
    conn.executemany(
        "INSERT INTO products (amount, date) VALUES (?, ?)",
        [(371, "2026-06-11"), (374, "2026-06-11"), (377, "2026-06-16")],
    )
    conn.commit()
    conn.close()

    repo = SqliteRepository(path)
    repo.setup()
    with repo.connection() as check:
        total = check.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        renomeada = check.execute(
            "SELECT 1 FROM sqlite_master WHERE name='products_legacy_v1'"
        ).fetchone()
    assert total == 3
    assert renomeada  # o original fica no banco, so sai do caminho


# ----------------------------------------------------------------- transacao
def test_excecao_dentro_do_context_manager_faz_rollback(sqlite_repo):
    """Na v1, uma excecao entre execute e commit descartava por acidente.  BUG-10"""
    with pytest.raises(ValueError), sqlite_repo.connection() as conn:
        conn.execute(
            "INSERT INTO snapshots (observed_at, amount) VALUES (?, ?)", (NOW.isoformat(), 1)
        )
        raise ValueError("algo deu errado no meio")

    assert sqlite_repo.last_snapshot() is None


def test_erro_de_sql_vira_storage_error(sqlite_repo):
    with pytest.raises(StorageError), sqlite_repo.connection() as conn:
        conn.execute("SELECT * FROM tabela_que_nao_existe")


# ---------------------------------------------------------------- snapshots
def test_snapshot_preserva_hora_e_fuso(sqlite_repo):
    """A v1 gravava so a data e jogava fora a hora -- a informacao mais valiosa.
    DAT-2"""
    sqlite_repo.save_snapshot(Snapshot(observed_at=NOW, amount=480, payload_hash="abc"))
    recuperado = sqlite_repo.last_snapshot()
    assert recuperado is not None
    assert recuperado.observed_at == NOW
    assert recuperado.observed_at.tzinfo is not None
    assert recuperado.payload_hash == "abc"


# -------------------------------------------------------------------- outbox
def test_evento_nasce_pendente_e_sai_da_fila_ao_confirmar(sqlite_repo):
    event = sqlite_repo.save_event(
        Event(observed_at=NOW, kind=EventKind.INCREASE, previous=100, current=105, delta=5)
    )
    assert len(sqlite_repo.pending_events()) == 1
    assert event.id is not None
    sqlite_repo.mark_notified(event.id)
    assert sqlite_repo.pending_events() == []


def test_falha_de_entrega_incrementa_tentativas_sem_tirar_da_fila(sqlite_repo):
    event = sqlite_repo.save_event(
        Event(observed_at=NOW, kind=EventKind.INCREASE, previous=1, current=2, delta=1)
    )
    assert event.id is not None
    sqlite_repo.mark_notification_failed(event.id, "Discord fora do ar")
    assert len(sqlite_repo.pending_events()) == 1
    with sqlite_repo.connection() as conn:
        row = conn.execute("SELECT attempts, last_error FROM events WHERE id = ?", (event.id,))
        attempts, error = row.fetchone()
    assert attempts == 1
    assert "Discord" in error


# ---------------------------------------------------------------------- runs
def test_healthcheck_enxerga_a_ultima_coleta(sqlite_repo):
    sqlite_repo.save_run(
        RunResult(run_id="a", started_at=NOW, status=RunStatus.OK, duration_ms=120)
    )
    assert sqlite_repo.last_successful_run_at() == NOW


def test_healthcheck_ignora_ciclos_que_falharam(sqlite_repo):
    sqlite_repo.save_run(
        RunResult(run_id="a", started_at=NOW, status=RunStatus.UPSTREAM_REJECTED, duration_ms=10)
    )
    assert sqlite_repo.last_successful_run_at() is None


# --------------------------------------------------------------- manutencao
def _maintenance(repo, tmp_path, **kwargs):
    defaults = {
        "retention_days": 30,
        "events_retention_days": 730,
        "backup_dir": tmp_path / "bkp",
        "backup_keep": 3,
    }
    defaults.update(kwargs)
    return Maintenance(repo, **defaults)


def test_retencao_agrega_antes_de_apagar(sqlite_repo, tmp_path):
    """Descartar o detalhe sem agregar seria perda de dado, nao retencao.  DAT-5"""
    antigo = NOW - timedelta(days=60)
    for index in range(5):
        sqlite_repo.save_run(
            RunResult(
                run_id=f"r{index}",
                started_at=antigo,
                status=RunStatus.OK if index else RunStatus.ERROR,
                duration_ms=100 + index,
                observed_amount=400 + index,
            )
        )
    _maintenance(sqlite_repo, tmp_path).run(NOW)

    with sqlite_repo.connection() as conn:
        restantes = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        resumo = conn.execute("SELECT runs, failures FROM run_hourly").fetchone()
    assert restantes == 0
    assert resumo["runs"] == 5
    assert resumo["failures"] == 1


def test_eventos_pendentes_nunca_sao_apagados(sqlite_repo, tmp_path):
    """A fila de entrega nao pode ser vitima da retencao.  BUG-13"""
    velho = NOW - timedelta(days=3000)
    sqlite_repo.save_event(
        Event(observed_at=velho, kind=EventKind.INCREASE, previous=1, current=9, delta=8)
    )
    _maintenance(sqlite_repo, tmp_path).run(NOW)
    assert len(sqlite_repo.pending_events()) == 1


def test_backup_e_gerado_e_rotacionado(sqlite_repo, tmp_path):
    maintenance = _maintenance(sqlite_repo, tmp_path, backup_keep=2)
    for offset in range(4):
        maintenance.run(NOW + timedelta(days=offset))
    copias = sorted((tmp_path / "bkp").glob("scrapingbot-*.db"))
    assert len(copias) == 2  # DAT-6
    assert all(c.stat().st_size > 0 for c in copias)


def test_manutencao_so_roda_uma_vez_por_dia(sqlite_repo, tmp_path):
    maintenance = _maintenance(sqlite_repo, tmp_path)
    assert maintenance.is_due(NOW)
    maintenance.run(NOW)
    assert not maintenance.is_due(NOW + timedelta(hours=6))
    assert maintenance.is_due(NOW + timedelta(hours=25))


def test_ultimo_snapshot_e_o_mais_recente_nao_o_de_id_maior(sqlite_repo):
    """O `import-legacy` grava historico antigo com ids novos.

    Ordenando por id, a "ultima" observacao viraria uma de meses atras -- e o
    bot compararia a coleta de hoje contra ela, podendo disparar um alerta
    falso para o canal publico.
    """
    sqlite_repo.save_snapshot(Snapshot(observed_at=NOW, amount=75))  # hoje
    antiga = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    sqlite_repo.save_snapshot(Snapshot(observed_at=antiga, amount=377))  # importada

    ultima = sqlite_repo.last_snapshot()
    assert ultima is not None
    assert ultima.amount == 75, "pegou a linha de id maior em vez da mais recente"
