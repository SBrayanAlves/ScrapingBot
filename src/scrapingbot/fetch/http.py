"""Coleta HTTP.

Alem de corrigir os pontos da auditoria (SCR-1..SCR-3, BUG-6), este modulo
instrumenta a resposta o suficiente para responder a pergunta do cliente --
"a notificacao esta atrasando" -- com evidencia em vez de palpite:

  * `payload_hash`  -> a resposta esta MUDANDO? Se nao, o bot nao esta atrasado:
                       o alvo e que nao esta entregando dado novo.  SCR-7
  * `cache_age`     -> header `Age`: quantos segundos a resposta ficou no CDN.
                       Se ele cresce, o atraso e da borda, nao do bot.
  * `cache_status`  -> HIT/MISS do CDN.
  * `server_date`   -> relogio do alvo, para comparar com o nosso.
  * `latency_ms`    -> sobe muito antes de um alvo comecar a recusar trafego.

SCR-6 (novo, fora da auditoria): o maior vetor de deteccao NAO e o User-Agent.
E o fingerprint de TLS (JA3/JA4) e de HTTP/2. `requests` fala TLS com a ordem
de cipher suites do OpenSSL e HTTP/1.1; um Chrome real tem ordem propria, envia
GREASE e fala h2. Qualquer WAF moderno ve "UA de Chrome + handshake de Python"
e a conta nao fecha -- por mais perfeito que seja o header. Por isso existe o
backend opcional `curl_cffi`, que imita o handshake de um Chrome de verdade.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import random
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..clock import Clock
from ..errors import UnexpectedPayload, UpstreamRejected, UpstreamUnavailable
from ..models import FetchResult
from .profiles import BrowserProfile, pick_profile, supported_accept_encoding

log = logging.getLogger(__name__)

# Caminho dentro do JSON ate a contagem. Explicito e nomeado, porque quando ele
# muda o bot fica cego e voce precisa de um erro que diga exatamente isso.
_AMOUNT_PATH = ("data", "productSearch", "recordsFiltered")
_REJECTION_STATUSES = frozenset({401, 403, 407, 429, 451})


def _extract_amount(payload: Any) -> int:
    """Percorre o caminho esperado, nomeando exatamente onde quebrou.  OBS-4"""
    node = payload
    for index, key in enumerate(_AMOUNT_PATH):
        if not isinstance(node, dict) or key not in node:
            trail = ".".join(_AMOUNT_PATH[:index]) or "<raiz>"
            available = list(node.keys())[:10] if isinstance(node, dict) else type(node).__name__
            raise UnexpectedPayload(
                f"Campo {'.'.join(_AMOUNT_PATH)} ausente: quebrou em {trail!r}; "
                f"o que veio: {available}"
            )
        node = node[key]

    if isinstance(node, bool) or not isinstance(node, int | float | str):
        raise UnexpectedPayload(f"{'.'.join(_AMOUNT_PATH)} nao e numerico: {node!r}")
    try:
        return int(node)
    except (TypeError, ValueError) as exc:
        raise UnexpectedPayload(
            f"{'.'.join(_AMOUNT_PATH)} nao converte para int: {node!r}"
        ) from exc


def _payload_fingerprint(raw: bytes) -> str:
    """Hash do corpo bruto. Barato, e detecta contrato congelado.  PRD-6 / SCR-7"""
    return hashlib.sha256(raw).hexdigest()[:16]


def _cache_age(headers: Any) -> int | None:
    raw = headers.get("Age")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _cache_status(headers: Any) -> str | None:
    for name in ("x-cache", "cf-cache-status", "x-vtex-cache", "x-cache-status", "cdn-cache"):
        value = headers.get(name)
        if value:
            return str(value)[:60]
    return None


def _server_date(headers: Any) -> Any:
    raw = headers.get("Date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def _with_cache_buster(url: str, param: str, value: int) -> str:
    """Acrescenta (ou atualiza) o parametro anti-cache preservando o resto.

    O codigo antigo fazia `f"{url}&_={ts}"`, o que quebra se a URL nao tiver
    query string e duplica o parametro se ja tiver.
    """
    if not param:
        return url
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != param]
    query.append((param, str(value)))
    return urlunparse(parts._replace(query=urlencode(query)))


class HttpFetcher:
    """Coleta com identidade coerente e sessao com ciclo de vida definido."""

    def __init__(
        self,
        *,
        target_url: str,
        page_url: str,
        referer: str,
        clock: Clock,
        timeout_s: float = 10.0,
        retries: int = 3,
        backoff_factor: float = 2.0,
        warmup: bool = True,
        session_max_cycles: int = 40,
        prefetch_delay: tuple[float, float] = (1.5, 3.5),
        backend: str = "auto",
        cache_buster_param: str = "_",
        no_cache_headers: bool = False,
        rng: random.Random | None = None,
    ) -> None:
        self.target_url = target_url
        self.page_url = page_url
        self.referer = referer
        self.clock = clock
        self.timeout_s = timeout_s
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.warmup = warmup
        self.session_max_cycles = session_max_cycles
        self.prefetch_delay = prefetch_delay
        self.cache_buster_param = cache_buster_param
        self.no_cache_headers = no_cache_headers
        self._rng = rng or random.SystemRandom()
        self._accept_encoding = supported_accept_encoding()
        self._backend = self._resolve_backend(backend)

        self._session: Any | None = None
        self._profile: BrowserProfile | None = None
        self._session_cycles = 0

    # ---------------------------------------------------------------- backend
    @staticmethod
    def _resolve_backend(requested: str) -> str:
        if requested == "requests":
            return "requests"
        try:
            import curl_cffi  # noqa: F401
        except ImportError:
            if requested == "curl_cffi":
                log.warning(
                    "FETCH_BACKEND=curl_cffi pedido mas o pacote nao esta instalado "
                    "(pip install 'scrapingbot[stealth]'); caindo para `requests`. "
                    "Sem ele, o fingerprint TLS/HTTP2 e o do Python, nao o do Chrome."
                )
            return "requests"
        return "curl_cffi"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def profile_name(self) -> str | None:
        return self._profile.name if self._profile else None

    # ---------------------------------------------------------------- sessao
    def _new_session(self) -> None:
        """Recria a identidade INTEIRA: cookies novos, perfil novo.  SCR-1

        Trocar UA mantendo cookies e sinal de deteccao, nao disfarce. Ou a
        identidade e nova de ponta a ponta, ou ela nao muda.
        """
        self.close()
        self._profile = pick_profile(self._rng, exclude=self.profile_name)
        self._session_cycles = 0

        if self._backend == "curl_cffi":
            from curl_cffi import requests as curl_requests

            impersonate = "chrome" if self._profile.sec_ch_ua else "firefox"
            self._session = curl_requests.Session(impersonate=impersonate)
        else:
            session = requests.Session()
            retry = Retry(
                total=self.retries,
                backoff_factor=self.backoff_factor,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
                respect_retry_after_header=True,  # SCR-4
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._session = session

        assert self._session is not None
        self._session.headers.clear()
        self._session.headers.update(self._profile.api_headers(self.referer, self._accept_encoding))
        log.info(
            "Nova sessao: perfil=%s backend=%s accept_encoding=%s",
            self._profile.name,
            self._backend,
            self._accept_encoding,
        )
        if self.warmup:
            self._warm_up()

    def _warm_up(self) -> None:
        """Visita a pagina HTML antes de chamar a API.  SCR-8

        E o que um usuario real faz: abre a pagina, o front-end dispara o XHR.
        Uma sessao cujo PRIMEIRO request e a API interna, sem nunca ter visto a
        pagina, e um padrao facil de marcar. Alem disso, e aqui que se obtem os
        cookies de sessao/anti-bot que a API espera.

        O codigo antigo tinha a intencao certa, mas mandava headers de XHR para
        uma pagina HTML -- e so na criacao da sessao, que nunca era recriada.
        """
        assert self._session is not None and self._profile is not None
        headers = self._profile.document_headers(self._accept_encoding)
        try:
            self._session.get(self.page_url, headers=headers, timeout=self.timeout_s)
            # Pausa entre abrir a pagina e o XHR: o navegador tambem leva um
            # tempo para renderizar e disparar o fetch.
            self.clock.sleep(self.clock.uniform(0.4, 1.2))
        except Exception as exc:
            log.debug("Aquecimento falhou (segue mesmo assim): %s", exc)

    def close(self) -> None:
        if self._session is not None:
            with contextlib.suppress(Exception):
                self._session.close()
            self._session = None

    # ----------------------------------------------------------------- coleta
    def fetch(self) -> FetchResult:
        if self._session is None or self._session_cycles >= self.session_max_cycles:
            self._new_session()
        assert self._session is not None and self._profile is not None
        self._session_cycles += 1

        url = _with_cache_buster(
            self.target_url, self.cache_buster_param, int(self.clock.now().timestamp())
        )
        headers: dict[str, str] = {}
        if self.no_cache_headers:
            # Desligado por padrao: um Chrome so envia isto em reload forcado.
            # Ligue apenas se medir que o CDN esta servindo resposta velha.
            headers["Cache-Control"] = "no-cache"
            headers["Pragma"] = "no-cache"

        # Jitter ANTES da chamada -- e o unico ponto do ciclo onde ele nao
        # atrapalha a medicao de latencia.
        self.clock.sleep(self.clock.uniform(*self.prefetch_delay))

        started = self.clock.monotonic()
        try:
            response = self._session.get(url, headers=headers or None, timeout=self.timeout_s)
        except Exception as exc:
            raise UpstreamUnavailable(f"{type(exc).__name__}: {exc}") from exc
        latency_ms = int((self.clock.monotonic() - started) * 1000)

        status = int(response.status_code)
        if status in _REJECTION_STATUSES:
            retry_after = response.headers.get("Retry-After")
            raise UpstreamRejected(
                f"Alvo recusou a requisicao: HTTP {status}",
                status=status,
                retry_after=float(retry_after) if _is_number(retry_after) else None,
            )
        if status >= 500:
            raise UpstreamUnavailable(f"Alvo indisponivel: HTTP {status}")
        if status >= 400:
            raise UnexpectedPayload(f"Resposta inesperada do alvo: HTTP {status}")

        raw = response.content
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            preview = raw[:120]
            raise UnexpectedPayload(
                f"Resposta nao e JSON valido ({exc}); primeiros bytes: {preview!r}"
            ) from exc

        amount = _extract_amount(payload)

        return FetchResult(
            amount=amount,
            payload_hash=_payload_fingerprint(raw),
            latency_ms=latency_ms,
            http_status=status,
            cache_age=_cache_age(response.headers),
            cache_status=_cache_status(response.headers),
            server_date=_server_date(response.headers),
            profile=self._profile.name,
        )


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
