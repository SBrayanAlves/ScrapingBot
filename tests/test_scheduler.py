"""Cadencia, backoff, janela de operacao e sinais de saude."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from conftest import FakeFetcher, FakeNotifier
from scrapingbot.clock import FakeClock
from scrapingbot.config import Settings
from scrapingbot.errors import UpstreamRejected
from scrapingbot.observability.heartbeat import HealthTracker
from scrapingbot.scheduler import Scheduler
from scrapingbot.service import MonitorService, Thresholds
from scrapingbot.storage.sqlite import InMemoryRepository

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


def make_settings(**kwargs) -> Settings:
    from pathlib import Path

    defaults = {
        "target_url": "https://x.com/api",
        "page_url": "https://x.com",
        "referer": "https://x.com",
        "alert_webhook": "https://discord.com/api/webhooks/1/a",
        "log_webhook": "https://discord.com/api/webhooks/2/b",
        "alert_mention": "",
        "db_path": Path("nao-usado.db"),
        "retention_days": 30,
        "events_retention_days": 730,
        "backup_dir": Path("nao-usado-bkp"),
        "backup_keep": 3,
        "interval_min_s": 45.0,
        "interval_max_s": 75.0,
        "cycle_deadline_s": 40.0,
        "backoff_base_s": 60.0,
        "backoff_max_s": 1800.0,
        "active_days": None,
        "active_hour_start": 0,
        "active_hour_end": 24,
        "timezone": ZoneInfo("America/Sao_Paulo"),
        "alert_threshold": 1,
        "max_plausible_delta": 200,
        "max_plausible_amount": 100_000,
        "http_timeout_s": 10.0,
        "http_retries": 3,
        "http_backoff_factor": 2.0,
        "warmup_enabled": False,
        "session_max_cycles": 40,
        "prefetch_delay_min_s": 0.0,
        "prefetch_delay_max_s": 0.0,
        "fetch_backend": "requests",
        "cache_buster_param": "_",
        "no_cache_headers": False,
        "heartbeat_every": 15,
        "failure_alert_threshold": 5,
        "stale_alert_threshold": 30,
        "deadman_url": None,
        "lock_path": Path("nao-usado.lock"),
        "notify_timeout_s": 10.0,
        "notify_retries": 3,
        "log_level": "INFO",
        "log_file": None,
        "log_max_bytes": 1000,
        "log_backups": 1,
        "env_file": None,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def build(script, *, settings=None, clock=None, notifier=None):
    settings = settings or make_settings()
    clock = clock or FakeClock()
    notifier = notifier or FakeNotifier()
    repo = InMemoryRepository()
    service = MonitorService(
        fetcher=FakeFetcher(script),
        repository=repo,
        notifier=notifier,
        clock=clock,
        thresholds=Thresholds(alert_delta=settings.alert_threshold),
    )
    scheduler = Scheduler(
        service=service, settings=settings, clock=clock, notifier=notifier, maintenance=None
    )
    return scheduler, repo, notifier, clock


# ------------------------------------------------------------------ cadencia
def test_ciclo_normal_usa_o_intervalo_configurado():
    scheduler, _, _, clock = build([100, 101, 102])
    scheduler.run_forever(max_cycles=3)
    assert all(45.0 <= s <= 75.0 for s in clock.slept)


def test_falha_do_alvo_aciona_backoff_exponencial():
    """A v1 batia ~60x/hora para sempre contra quem ja a tinha rejeitado --
    transformando falha temporaria em bloqueio permanente de IP.  BUG-17"""
    erros = [UpstreamRejected("403", status=403) for _ in range(4)]
    scheduler, _, _, clock = build(erros)
    scheduler.run_forever(max_cycles=4)
    # 60 * 2^0, 2^1, 2^2, 2^3, com jitter de +-20%
    assert clock.slept[0] >= 45.0
    assert clock.slept[-1] > clock.slept[0] * 3


def test_backoff_respeita_o_teto():
    erros = [UpstreamRejected("403", status=403) for _ in range(12)]
    settings = make_settings(backoff_max_s=300.0)
    scheduler, _, _, clock = build(erros, settings=settings)
    scheduler.run_forever(max_cycles=12)
    assert max(clock.slept) <= 300.0 * 1.2


def test_sucesso_zera_o_backoff():
    script = [UpstreamRejected("403", status=403), UpstreamRejected("403", status=403), 100, 100]
    scheduler, _, _, clock = build(script)
    scheduler.run_forever(max_cycles=4)
    assert clock.slept[-1] <= 75.0


# -------------------------------------------------------------------- sinais
def test_shutdown_interrompe_o_laco():
    scheduler, _, _, _ = build([100] * 10)
    scheduler.stop()
    scheduler.run_forever(max_cycles=10)
    assert scheduler.stopping


def test_excecao_inesperada_nao_mata_o_processo():
    """REL-2: um erro num ciclo nao pode encerrar o monitoramento."""

    class Explosivo:
        def fetch(self):
            raise RuntimeError("algo totalmente inesperado")

        def close(self):
            pass

    settings = make_settings()
    clock = FakeClock()
    service = MonitorService(
        fetcher=Explosivo(),
        repository=InMemoryRepository(),
        notifier=FakeNotifier(),
        clock=clock,
    )
    scheduler = Scheduler(service=service, settings=settings, clock=clock, notifier=FakeNotifier())
    scheduler.run_forever(max_cycles=3)  # nao levanta


# ------------------------------------------------------------------- janela
@pytest.mark.parametrize(
    ("dia", "hora", "dentro"),
    [
        (1, 10, True),  # terca, 10h
        (1, 20, False),  # terca, 20h -- fora da faixa
        (0, 10, False),  # segunda -- dia nao permitido
        (6, 9, True),  # domingo, 9h
    ],
)
def test_janela_de_operacao_vive_no_codigo(dia, hora, dentro):
    """O README prometia ter/qui/dom 8-19h; o codigo rodava 24/7.  ARQ-8"""
    settings = make_settings(
        active_days=frozenset({1, 3, 6}), active_hour_start=8, active_hour_end=19
    )
    # 2026-08-31 e uma segunda (weekday 0); somamos o offset ate o dia desejado.
    base = datetime(2026, 8, 31, hora, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    momento = base + timedelta(days=dia)
    clock = FakeClock(start=momento.astimezone(UTC))
    scheduler, _, _, _ = build([100], settings=settings, clock=clock)
    assert scheduler._within_window() is dentro


def test_sem_janela_configurada_roda_sempre():
    scheduler, _, _, _ = build([100])
    assert scheduler._within_window() is True


# -------------------------------------------------------------------- saude
def test_alerta_de_falhas_dispara_uma_vez_e_cala():
    """Sem isso, uma queda de 6h vira 360 mensagens e o canal e silenciado."""
    tracker = HealthTracker(failure_alert_threshold=3)
    for _ in range(3):
        tracker.record_failure()
    assert tracker.should_alert_failures() is True
    tracker.record_failure()
    assert tracker.should_alert_failures() is False


def test_alerta_de_falhas_rearma_apos_recuperar():
    tracker = HealthTracker(failure_alert_threshold=2)
    tracker.record_failure()
    tracker.record_failure()
    assert tracker.should_alert_failures() is True
    tracker.record_success(payload_hash="a")
    for _ in range(2):
        tracker.record_failure()
    assert tracker.should_alert_failures() is True


def test_payload_congelado_e_detectado():
    """SCR-7: a hipotese "o site so manda resposta velha", medida."""
    tracker = HealthTracker(stale_alert_threshold=3)
    for _ in range(5):
        tracker.record_success(payload_hash="sempre-o-mesmo")
    assert tracker.consecutive_stale >= 3
    assert tracker.should_alert_stale() is True


def test_payload_que_muda_nao_dispara_suspeita():
    tracker = HealthTracker(stale_alert_threshold=3)
    for index in range(10):
        tracker.record_success(payload_hash=f"h{index}")
    assert tracker.should_alert_stale() is False


def test_heartbeat_so_a_cada_n_ciclos():
    """Um contador em um lugar so -- eram dois `_pass`/`_WARNING`.  ARQ-5"""
    tracker = HealthTracker(heartbeat_every=3)
    tracker.record_success()
    tracker.record_success()
    assert tracker.should_heartbeat() is False
    tracker.record_success()
    assert tracker.should_heartbeat() is True
    assert tracker.should_heartbeat() is False  # zerou


def test_taxa_de_sucesso_e_p95():
    tracker = HealthTracker()
    for latencia in (100, 200, 300, 400):
        tracker.record_success(latency_ms=latencia)
    tracker.record_failure()
    assert tracker.success_rate == pytest.approx(0.8)
    assert tracker.latency_p95_ms == 400


def test_fora_da_janela_avisa_no_log_e_nao_fica_mudo(caplog):
    """Silencio total e indistinguivel de processo travado.

    Antes, um bot saudavel fora do horario nao escrevia UMA linha sequer -- o
    dono olhava o log vazio e concluia que estava quebrado.
    """
    settings = make_settings(
        active_days=frozenset({1, 3, 6}), active_hour_start=8, active_hour_end=18
    )
    meia_noite = datetime(2026, 9, 1, 0, 40, tzinfo=ZoneInfo("America/Sao_Paulo"))
    clock = FakeClock(start=meia_noite.astimezone(UTC))
    scheduler, _, _, _ = build([100], settings=settings, clock=clock)

    with caplog.at_level("INFO"):
        scheduler.run_forever(max_cycles=3)

    fora = [r for r in caplog.records if "Fora da janela" in r.message]
    assert len(fora) == 1, "deve avisar uma vez, nao a cada ciclo"
    assert "ter, qui, dom" in caplog.text
    assert "08h-18h" in caplog.text
