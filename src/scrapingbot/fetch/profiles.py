"""Perfis de navegador coerentes.  SCR-1 / SCR-2 / SCR-3

O erro do codigo antigo nao era "pouco disfarce", era **disfarce incoerente**:

  * `fake_useragent` sorteava um UA qualquer -- Chrome, Firefox, Safari, versao
    antiga, mobile -- a cada requisicao;
  * os `Sec-CH-UA` que todo Chrome moderno envia nao existiam, entao o servidor
    via "Chrome 120" sem os headers que Chrome 120 sempre manda;
  * o UA trocava mas os COOKIES continuavam os mesmos: do lado do servidor,
    uma sessao unica que muda de navegador e de sistema operacional a cada 60s.

Nenhum usuario real faz isso. O padrao foi CRIADO pela tentativa de esconder.

A correcao e tratar identidade como um pacote fechado: um perfil e um conjunto
coerente (UA + client hints + plataforma + idioma), escolhido inteiro, mantido
pela sessao inteira, e trocado apenas junto com os cookies.

REFERENCIA DE VERDADE: abra o DevTools no site alvo, ache a requisicao que o
proprio front-end faz para este endpoint, "Copy as cURL", e compare header por
header. O que esta aqui e uma aproximacao boa; o que esta la e o gabarito.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class BrowserProfile:
    """Uma identidade completa. Todos os campos precisam combinar entre si."""

    name: str
    user_agent: str
    sec_ch_ua: str | None  # None para Firefox, que nao envia client hints
    platform: str  # valor de sec-ch-ua-platform
    accept_language: str
    mobile: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    def api_headers(self, referer: str, accept_encoding: str) -> dict[str, str]:
        """Headers de uma chamada XHR/fetch, na ordem em que o Chrome os envia.

        A ORDEM importa: e parte do fingerprint HTTP. `requests` preserva a
        ordem de insercao do dict, entao construir na ordem certa e de graca.
        """
        headers: dict[str, str] = {}
        if self.sec_ch_ua:
            headers["sec-ch-ua"] = self.sec_ch_ua
            headers["sec-ch-ua-mobile"] = "?1" if self.mobile else "?0"
            headers["sec-ch-ua-platform"] = f'"{self.platform}"'
        headers["User-Agent"] = self.user_agent
        # `application/json, text/plain, */*` e o Accept que o axios manda -- e
        # o que a maioria das lojas usa no front. Nao ha Content-Type: GET nao
        # tem corpo, e navegador nenhum envia esse header num GET.  SCR-2
        headers["Accept"] = "application/json, text/plain, */*"
        headers["Sec-Fetch-Site"] = "same-origin"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Referer"] = referer
        headers["Accept-Encoding"] = accept_encoding
        headers["Accept-Language"] = self.accept_language
        if self.sec_ch_ua:
            headers["Priority"] = "u=1, i"
        headers.update(self.extra)
        return headers

    def document_headers(self, accept_encoding: str) -> dict[str, str]:
        """Headers de navegacao (a pagina HTML), usados no aquecimento.  SCR-8

        Sao DIFERENTES dos de XHR: `Sec-Fetch-Dest: document`, `Accept` de HTML,
        `Upgrade-Insecure-Requests`. O codigo antigo aquecia a sessao mandando
        headers de XHR para uma pagina HTML -- combinacao que nao existe.
        """
        headers: dict[str, str] = {}
        if self.sec_ch_ua:
            headers["sec-ch-ua"] = self.sec_ch_ua
            headers["sec-ch-ua-mobile"] = "?1" if self.mobile else "?0"
            headers["sec-ch-ua-platform"] = f'"{self.platform}"'
        headers["Upgrade-Insecure-Requests"] = "1"
        headers["User-Agent"] = self.user_agent
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        )
        headers["Sec-Fetch-Site"] = "none"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-User"] = "?1"
        headers["Sec-Fetch-Dest"] = "document"
        headers["Accept-Encoding"] = accept_encoding
        headers["Accept-Language"] = self.accept_language
        if self.sec_ch_ua:
            headers["Priority"] = "u=0, i"
        return headers


_PT_BR = "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"

# Poucos perfis, todos plausiveis para um visitante brasileiro de loja online.
# Cinco identidades coerentes valem mais que dez mil incoerentes.
PROFILES: tuple[BrowserProfile, ...] = (
    BrowserProfile(
        name="chrome-133-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
        sec_ch_ua='"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        platform="Windows",
        accept_language=_PT_BR,
    ),
    BrowserProfile(
        name="chrome-132-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        ),
        sec_ch_ua='"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
        platform="Windows",
        accept_language=_PT_BR,
    ),
    BrowserProfile(
        name="edge-133-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"
        ),
        sec_ch_ua='"Not(A:Brand";v="99", "Microsoft Edge";v="133", "Chromium";v="133"',
        platform="Windows",
        accept_language=_PT_BR,
    ),
    BrowserProfile(
        name="chrome-133-mac",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        ),
        sec_ch_ua='"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        platform="macOS",
        accept_language=_PT_BR,
    ),
    BrowserProfile(
        # Firefox nao envia client hints -- por isso `sec_ch_ua=None`. Enviar
        # Sec-CH-UA com UA de Firefox seria exatamente o tipo de incoerencia
        # que este modulo existe para evitar.
        name="firefox-135-win",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0"
        ),
        sec_ch_ua=None,
        platform="Windows",
        accept_language="pt-BR,pt;q=0.8,en-US;q=0.5,en;q=0.3",
    ),
)

PROFILES_BY_NAME = {profile.name: profile for profile in PROFILES}


def pick_profile(rng: random.Random | None = None, *, exclude: str | None = None) -> BrowserProfile:
    """Sorteia um perfil inteiro, evitando repetir o anterior quando possivel."""
    generator = rng or random.SystemRandom()
    candidates = [p for p in PROFILES if p.name != exclude] or list(PROFILES)
    return generator.choice(candidates)


def supported_accept_encoding() -> str:
    """Anuncia so o que este processo consegue DESCOMPRIMIR.  BUG-6

    O codigo antigo anunciava `br, zstd` sem ter as bibliotecas instaladas: se o
    servidor honrasse, chegavam bytes binarios e `response.json()` estourava.
    Funcionava por sorte.

    Note a tensao: um Chrome real SEMPRE manda `gzip, deflate, br, zstd`, entao
    anunciar menos e um desvio de fingerprint. Por isso `brotli` e `zstandard`
    entraram nas dependencias -- assim o honesto e o realista coincidem.
    """
    encodings = ["gzip", "deflate"]
    try:
        import brotli  # noqa: F401

        encodings.append("br")
    except ImportError:
        try:
            import brotlicffi  # noqa: F401

            encodings.append("br")
        except ImportError:
            pass
    try:
        import zstandard  # noqa: F401

        encodings.append("zstd")
    except ImportError:
        pass
    return ", ".join(encodings)
