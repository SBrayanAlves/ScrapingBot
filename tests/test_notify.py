"""Entrega no Discord: rate limit, falha total, mencao e redacao."""

from __future__ import annotations

import pytest
import responses

from scrapingbot.clock import FakeClock
from scrapingbot.errors import NotificationError
from scrapingbot.notify.discord import DiscordNotifier, _allowed_mentions_for
from scrapingbot.notify.protocol import Channel, Notification, Severity

ALERT = "https://discord.com/api/webhooks/111/token-secreto-do-alerta"
LOGS = "https://discord.com/api/webhooks/222/token-secreto-do-log"


def make_notifier(**kwargs) -> DiscordNotifier:
    defaults = {"alert_webhook": ALERT, "log_webhook": LOGS, "clock": FakeClock(), "retries": 3}
    defaults.update(kwargs)
    return DiscordNotifier(**defaults)


def alerta(**kwargs) -> Notification:
    defaults = {
        "title": "3 PRODUTOS no ar",
        "body": "subiu de 100 para 103",
        "channel": Channel.PUBLIC,
        "severity": Severity.SUCCESS,
        "mention": True,
    }
    defaults.update(kwargs)
    return Notification(**defaults)


@responses.activate
def test_204_conta_como_entregue():
    responses.add(responses.POST, ALERT, status=204)
    make_notifier().send(alerta())
    assert len(responses.calls) == 1


@responses.activate
def test_canal_publico_e_canal_de_log_sao_webhooks_distintos():
    responses.add(responses.POST, LOGS, status=204)
    make_notifier().send(alerta(channel=Channel.LOG, mention=False))
    assert responses.calls[0].request.url == LOGS


@responses.activate
def test_esgotar_tentativas_levanta_em_vez_de_devolver_none():
    """A v1 devolvia None no sucesso, no esgotamento e na excecao.  BUG-18"""
    for _ in range(3):
        responses.add(responses.POST, ALERT, status=500)
    with pytest.raises(NotificationError):
        make_notifier().send(alerta())


@responses.activate
def test_429_respeita_retry_after_e_repete():
    """A v1 ignorava 429 e dormia 3s fixos.  SCR-4"""
    responses.add(responses.POST, ALERT, status=429, headers={"Retry-After": "2"})
    responses.add(responses.POST, ALERT, status=204)
    clock = FakeClock()
    make_notifier(clock=clock).send(alerta())
    assert 2.0 in clock.slept
    assert len(responses.calls) == 2


@responses.activate
def test_erro_de_cliente_nao_e_repetido():
    """404 = webhook revogado. Repetir 3x nao ressuscita a credencial."""
    responses.add(responses.POST, ALERT, status=404)
    with pytest.raises(NotificationError, match="404"):
        make_notifier().send(alerta())
    assert len(responses.calls) == 1


@responses.activate
def test_falha_de_rede_dorme_entre_tentativas():
    """No `except` a v1 nao dormia: as 3 tentativas saiam quase juntas."""
    from requests.exceptions import ConnectionError as ReqConnError

    for _ in range(3):
        responses.add(responses.POST, ALERT, body=ReqConnError("sem rede"))
    clock = FakeClock()
    with pytest.raises(NotificationError):
        make_notifier(clock=clock).send(alerta())
    assert len(clock.slept) == 3
    assert all(s > 0 for s in clock.slept)


@responses.activate
def test_erro_de_rede_nao_vaza_o_token_do_webhook():
    """RequestException embute a URL completa -- e a URL E a credencial.  SEC-2"""
    from requests.exceptions import ConnectionError as ReqConnError

    for _ in range(3):
        responses.add(responses.POST, ALERT, body=ReqConnError(f"falhou ao conectar em {ALERT}"))
    with pytest.raises(NotificationError) as exc:
        make_notifier().send(alerta())
    assert "token-secreto" not in str(exc.value)


# ------------------------------------------------------------------ payload
@responses.activate
def test_sem_mencao_configurada_ninguem_e_pingado():
    responses.add(responses.POST, ALERT, status=204)
    make_notifier(mention="").send(alerta())
    body = responses.calls[0].request.body
    payload = body if isinstance(body, str) else body.decode()
    assert "content" not in payload
    assert '"parse": []' in payload.replace("'", '"')


@responses.activate
def test_mencao_configurada_vira_cargo_e_nao_everyone():
    """`@everyone` em todo alerta e o caminho mais curto para silenciarem o canal.
    SCR-5"""
    responses.add(responses.POST, ALERT, status=204)
    make_notifier(mention="<@&999>").send(alerta())
    payload = responses.calls[0].request.body
    payload = payload if isinstance(payload, str) else payload.decode()
    assert "<@&999>" in payload
    assert "everyone" not in payload


@responses.activate
def test_embed_carrega_antes_e_depois():
    """PRD-2: o valor anterior e o novo lado a lado, nao so a diferenca."""
    responses.add(responses.POST, ALERT, status=204)
    make_notifier().send(alerta(fields=(("Antes", "100"), ("Agora", "103"), ("Variacao", "+3"))))
    payload = responses.calls[0].request.body
    payload = payload if isinstance(payload, str) else payload.decode()
    assert "embeds" in payload
    assert "Antes" in payload and "Agora" in payload


@pytest.mark.parametrize(
    ("mention", "chave"),
    [("<@&123>", "roles"), ("<@456>", "users"), ("@everyone", "parse")],
)
def test_allowed_mentions_libera_so_o_configurado(mention, chave):
    assert chave in _allowed_mentions_for(mention)


def test_texto_do_embed_nao_pinga_ninguem_sozinho():
    """Sem allowed_mentions, um '@everyone' no CORPO ainda pingaria todos."""
    notifier = make_notifier(mention="")
    payload = notifier._build_payload(alerta(body="cuidado @everyone", mention=False))
    assert payload["allowed_mentions"] == {"parse": []}
