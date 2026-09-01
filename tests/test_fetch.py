"""Coleta HTTP com respostas reais simuladas.  ENG-1 (teste 3 e 4)"""

from __future__ import annotations

import json

import pytest
import responses
from requests.exceptions import ConnectTimeout

from scrapingbot.clock import FakeClock
from scrapingbot.errors import UnexpectedPayload, UpstreamRejected, UpstreamUnavailable
from scrapingbot.fetch.http import HttpFetcher, _extract_amount, _with_cache_buster
from scrapingbot.fetch.profiles import PROFILES, pick_profile, supported_accept_encoding

TARGET = "https://loja.example.com/api/search?fq=x"
PAGE = "https://loja.example.com/categoria"

# Fixture com o formato real do alvo (VTEX Intelligent Search).
PAYLOAD_OK = {"data": {"productSearch": {"recordsFiltered": 480, "products": []}}}


def make_fetcher(**kwargs) -> HttpFetcher:
    defaults = {
        "target_url": TARGET,
        "page_url": PAGE,
        "referer": PAGE,
        "clock": FakeClock(),
        "warmup": False,
        "prefetch_delay": (0.0, 0.0),
        "backend": "requests",
    }
    defaults.update(kwargs)
    return HttpFetcher(**defaults)


# ------------------------------------------------------------------- parse
def test_extrai_o_campo_esperado():
    assert _extract_amount(PAYLOAD_OK) == 480


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": {}},
        {"data": {"productSearch": {}}},
        {"data": {"productSearch": {"recordsFiltered": None}}},
        {"data": {"productSearch": {"recordsFiltered": "abc"}}},
        {"data": None},
    ],
)
def test_payload_fora_do_contrato_levanta_erro_nomeado(payload):
    with pytest.raises(UnexpectedPayload):
        _extract_amount(payload)


def test_mensagem_de_erro_diz_onde_quebrou():
    with pytest.raises(UnexpectedPayload, match="productSearch"):
        _extract_amount({"data": {"outraCoisa": 1}})


# --------------------------------------------------------------- cache buster
def test_cache_buster_em_url_com_query():
    url = _with_cache_buster("https://x.com/api?a=1", "_", 999)
    assert url.endswith("_=999")
    assert "a=1" in url


def test_cache_buster_em_url_sem_query():
    """A v1 fazia f"{url}&_={ts}" -- gerava `...path&_=1` sem `?`."""
    assert _with_cache_buster("https://x.com/api", "_", 999) == "https://x.com/api?_=999"


def test_cache_buster_nao_duplica_parametro():
    url = _with_cache_buster("https://x.com/api?_=1", "_", 2)
    assert url.count("_=") == 1
    assert url.endswith("_=2")


def test_cache_buster_desligavel():
    assert _with_cache_buster("https://x.com/api", "", 999) == "https://x.com/api"


# -------------------------------------------------------------------- http
@responses.activate
def test_coleta_bem_sucedida_extrai_metadados_de_cache():
    responses.add(
        responses.GET,
        "https://loja.example.com/api/search",
        json=PAYLOAD_OK,
        status=200,
        headers={"Age": "42", "x-cache": "HIT", "Date": "Mon, 31 Aug 2026 12:00:00 GMT"},
    )
    result = make_fetcher().fetch()
    assert result.amount == 480
    assert result.cache_age == 42
    assert result.cache_status == "HIT"
    assert result.server_date is not None
    assert len(result.payload_hash) == 16


@responses.activate
def test_403_vira_upstream_rejected_com_status():
    responses.add(responses.GET, "https://loja.example.com/api/search", status=403)
    with pytest.raises(UpstreamRejected) as exc:
        make_fetcher().fetch()
    assert exc.value.status == 403


@responses.activate
def test_429_carrega_retry_after():
    responses.add(
        responses.GET,
        "https://loja.example.com/api/search",
        status=429,
        headers={"Retry-After": "30"},
    )
    with pytest.raises(UpstreamRejected) as exc:
        make_fetcher(retries=0).fetch()
    assert exc.value.retry_after == 30.0


@responses.activate
def test_503_vira_upstream_unavailable():
    responses.add(responses.GET, "https://loja.example.com/api/search", status=503)
    with pytest.raises(UpstreamUnavailable):
        make_fetcher(retries=0).fetch()


@responses.activate
def test_timeout_vira_upstream_unavailable():
    responses.add(
        responses.GET, "https://loja.example.com/api/search", body=ConnectTimeout("estourou")
    )
    with pytest.raises(UpstreamUnavailable):
        make_fetcher(retries=0).fetch()


@responses.activate
def test_json_malformado_vira_unexpected_payload():
    responses.add(
        responses.GET, "https://loja.example.com/api/search", body="<html>manutencao</html>"
    )
    with pytest.raises(UnexpectedPayload, match="JSON"):
        make_fetcher().fetch()


@responses.activate
def test_hash_muda_quando_o_corpo_muda():
    """A base da deteccao de resposta congelada.  SCR-7"""
    responses.add(responses.GET, "https://loja.example.com/api/search", json=PAYLOAD_OK)
    responses.add(
        responses.GET,
        "https://loja.example.com/api/search",
        json={"data": {"productSearch": {"recordsFiltered": 481, "products": []}}},
    )
    fetcher = make_fetcher()
    primeiro = fetcher.fetch()
    segundo = fetcher.fetch()
    assert primeiro.payload_hash != segundo.payload_hash


@responses.activate
def test_hash_estavel_quando_o_corpo_nao_muda():
    body = json.dumps(PAYLOAD_OK)
    for _ in range(2):
        responses.add(
            responses.GET,
            "https://loja.example.com/api/search",
            body=body,
            content_type="application/json",
        )
    fetcher = make_fetcher()
    assert fetcher.fetch().payload_hash == fetcher.fetch().payload_hash


# ----------------------------------------------------------------- stealth
@responses.activate
def test_nao_envia_content_type_em_get():
    """GET nao tem corpo -- navegador nenhum manda Content-Type nele.  SCR-2"""
    responses.add(responses.GET, "https://loja.example.com/api/search", json=PAYLOAD_OK)
    make_fetcher().fetch()
    enviados = {k.lower() for k in responses.calls[0].request.headers}
    assert "content-type" not in enviados


@responses.activate
def test_nao_envia_no_cache_por_padrao():
    """Chrome so manda isso em reload forcado; mandar sempre e um tell."""
    responses.add(responses.GET, "https://loja.example.com/api/search", json=PAYLOAD_OK)
    make_fetcher().fetch()
    headers = {k.lower() for k in responses.calls[0].request.headers}
    assert "pragma" not in headers


@responses.activate
def test_user_agent_nao_muda_dentro_da_mesma_sessao():
    """Trocar UA mantendo cookies e sinal de deteccao, nao disfarce.  SCR-1"""
    for _ in range(3):
        responses.add(responses.GET, "https://loja.example.com/api/search", json=PAYLOAD_OK)
    fetcher = make_fetcher(session_max_cycles=100)
    for _ in range(3):
        fetcher.fetch()
    agents = {call.request.headers["User-Agent"] for call in responses.calls}
    assert len(agents) == 1


@responses.activate
def test_sessao_e_recriada_apos_o_limite_de_ciclos():
    for _ in range(6):
        responses.add(responses.GET, "https://loja.example.com/api/search", json=PAYLOAD_OK)
    fetcher = make_fetcher(session_max_cycles=2)
    perfis = {fetcher.fetch().profile for _ in range(6)}
    assert len(perfis) > 1  # a identidade inteira mudou pelo menos uma vez


def test_perfis_sao_internamente_coerentes():
    """Client hints so existem em navegadores que os enviam.  SCR-3"""
    for profile in PROFILES:
        headers = profile.api_headers("https://x.com", "gzip")
        if "Firefox" in profile.user_agent:
            assert profile.sec_ch_ua is None
            assert "sec-ch-ua" not in headers
        else:
            assert profile.sec_ch_ua is not None
            assert "sec-ch-ua" in headers
            assert profile.platform in headers["sec-ch-ua-platform"]
        assert "Content-Type" not in headers


def test_headers_de_documento_diferem_dos_de_xhr():
    """Aquecimento usa headers de navegacao, nao de fetch.  SCR-8"""
    profile = PROFILES[0]
    doc = profile.document_headers("gzip")
    api = profile.api_headers("https://x.com", "gzip")
    assert doc["Sec-Fetch-Dest"] == "document"
    assert api["Sec-Fetch-Dest"] == "empty"
    assert doc["Accept"].startswith("text/html")


def test_pick_profile_evita_repetir_o_anterior():
    escolhido = pick_profile(exclude=PROFILES[0].name)
    assert escolhido.name != PROFILES[0].name


def test_accept_encoding_so_anuncia_o_que_da_para_descomprimir():
    """A v1 anunciava br/zstd sem ter as libs -- funcionava por sorte.  BUG-6"""
    encoding = supported_accept_encoding()
    assert "gzip" in encoding
    if "br" in encoding:
        try:
            import brotli  # noqa: F401
        except ImportError:
            import brotlicffi  # noqa: F401
    if "zstd" in encoding:
        import zstandard  # noqa: F401
