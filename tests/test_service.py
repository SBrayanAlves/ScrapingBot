"""O teste que justifica a reescrita.

Na v1 era impossivel escrever: a regra de negocio abria cursor SQL, chamava o
scraper que por sua vez falava com o Discord. Aqui ele cabe em cinco linhas,
sem rede, sem banco, sem webhook -- e roda em milissegundos.
"""

from __future__ import annotations

import pytest

from conftest import FakeFetcher, FakeNotifier
from scrapingbot.clock import FakeClock
from scrapingbot.errors import UnexpectedPayload, UpstreamRejected, UpstreamUnavailable
from scrapingbot.models import EventKind, RunStatus, Snapshot
from scrapingbot.service import MonitorService, Thresholds, decide
from scrapingbot.storage.sqlite import InMemoryRepository


def build(script, *, repo=None, notifier=None, limits=None, clock=None):
    repo = repo or InMemoryRepository()
    notifier = notifier or FakeNotifier()
    return (
        MonitorService(
            fetcher=FakeFetcher(script),
            repository=repo,
            notifier=notifier,
            clock=clock or FakeClock(),
            thresholds=limits or Thresholds(),
        ),
        repo,
        notifier,
    )


# ---------------------------------------------------------------- decide (puro)
def test_primeira_execucao_gera_linha_de_base():
    event = decide(None, 100, Thresholds())
    assert event is not None
    assert event.kind is EventKind.FIRST_RUN


def test_queda_nao_gera_evento():
    anterior = Snapshot(observed_at=FakeClock().now(), amount=100)
    assert decide(anterior, 90, Thresholds()) is None


def test_valor_igual_nao_gera_evento():
    anterior = Snapshot(observed_at=FakeClock().now(), amount=100)
    assert decide(anterior, 100, Thresholds()) is None


def test_aumento_de_um_gera_alerta():
    """A regressao central: na v1, `if difference > 2` engolia isto.

    Um produto entrando sozinho nao era notificado NEM persistido -- e so
    virava alerta depois de tres publicacoes. E o "atraso" que o cliente ve.
    """
    anterior = Snapshot(observed_at=FakeClock().now(), amount=100)
    event = decide(anterior, 101, Thresholds())
    assert event is not None
    assert event.kind is EventKind.INCREASE
    assert event.delta == 1


def test_salto_absurdo_vira_anomalia_nao_alerta():
    anterior = Snapshot(observed_at=FakeClock().now(), amount=480)
    event = decide(anterior, 50_000, Thresholds(max_plausible_delta=200))
    assert event is not None
    assert event.kind is EventKind.ANOMALY
    assert not event.is_alertable  # nao acorda o canal publico  BUG-15


def test_limiar_configuravel_suprime_ruido():
    anterior = Snapshot(observed_at=FakeClock().now(), amount=100)
    assert decide(anterior, 102, Thresholds(alert_delta=5)) is None
    assert decide(anterior, 106, Thresholds(alert_delta=5)) is not None


# ------------------------------------------------------------------ orquestracao
def test_subiu_tres_notifica_uma_vez_e_persiste():
    service, repo, notifier = build([100, 103])
    service.run_once("r1")  # linha de base
    service.run_once("r2")

    assert [s.amount for s in repo.snapshots] == [100, 103]
    assert len(notifier.public) == 1
    assert "3 PRODUTOS" in notifier.public[0].title


def test_todo_valor_observado_e_persistido_mesmo_sem_alerta():
    """Persistir e notificar sao decisoes independentes.  BUG-8"""
    service, repo, _ = build([100, 101, 99, 99])
    for index in range(4):
        service.run_once(f"r{index}")
    assert [s.amount for s in repo.snapshots] == [100, 101, 99, 99]


def test_todo_ciclo_vira_linha_em_runs():
    """Sem isto, "nada aconteceu" e "o bot morreu" sao iguais no banco.  DAT-1"""
    service, repo, _ = build([100, 100, 100])
    for index in range(3):
        service.run_once(f"r{index}")
    assert len(repo.runs) == 3
    assert all(run.status is RunStatus.OK for run in repo.runs)


def test_falha_de_entrega_mantem_o_evento_na_fila():
    """O pior tipo de falha da v1: alerta perdido em silencio.  BUG-13"""
    notifier = FakeNotifier(fail_times=99)
    service, repo, _ = build([100, 105], notifier=notifier)
    service.run_once("r1")
    service.run_once("r2")

    pendentes = repo.pending_events()
    assert any(e.kind is EventKind.INCREASE for e in pendentes)


def test_evento_pendente_e_reenviado_no_ciclo_seguinte():
    notifier = FakeNotifier(fail_times=2)  # falha na base e no aumento
    service, repo, _ = build([100, 105, 105], notifier=notifier)
    service.run_once("r1")
    service.run_once("r2")
    assert repo.pending_events()  # ainda na fila

    service.run_once("r3")  # Discord voltou
    assert not repo.pending_events()
    assert any(n.title.startswith("5 PRODUTOS") for n in notifier.sent)


def test_alerta_nao_repete_apos_entrega_confirmada():
    service, _repo, notifier = build([100, 105, 105, 105])
    for index in range(4):
        service.run_once(f"r{index}")
    assert len(notifier.public) == 1


# ---------------------------------------------------------------- classificacao
@pytest.mark.parametrize(
    ("erro", "esperado"),
    [
        (UpstreamUnavailable("timeout"), RunStatus.UPSTREAM_UNAVAILABLE),
        (UpstreamRejected("403", status=403), RunStatus.UPSTREAM_REJECTED),
        (UnexpectedPayload("campo sumiu"), RunStatus.UNEXPECTED_PAYLOAD),
    ],
)
def test_cada_falha_tem_status_proprio(erro, esperado):
    """Na v1 as tres chegavam ao log como "Validation Error/Logic".  OBS-4"""
    service, repo, _ = build([erro])
    result = service.run_once("r1")
    assert result.status is esperado
    assert repo.runs[-1].status is esperado


def test_mudanca_de_contrato_avisa_no_canal_de_log():
    service, _, notifier = build([UnexpectedPayload("data.productSearch sumiu")])
    service.run_once("r1")
    assert any(n.title == "Formato da resposta mudou" for n in notifier.sent)
    assert not notifier.public  # nao polui o canal do cliente


def test_falha_de_coleta_nao_apaga_a_linha_de_base():
    service, repo, _ = build([100, UpstreamUnavailable("timeout"), 104])
    service.run_once("r1")
    service.run_once("r2")
    service.run_once("r3")
    assert len(repo.snapshots) == 2  # a falha nao gravou snapshot
    assert repo.snapshots[-1].amount == 104
