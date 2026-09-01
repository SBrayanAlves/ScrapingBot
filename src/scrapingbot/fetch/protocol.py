"""Interface de coleta vista pela regra de negocio.  ARQ-1

O scraper antigo importava `notifier` e `webhook` e mandava mensagem sozinho --
seta de dependencia ao contrario. Consequencia pratica: nao dava para testar o
scraper sem webhook valido, nao dava para reaproveita-lo, e a decisao de
"quando alertar" morava em tres arquivos.

Aqui o contrato e um so: devolve `FetchResult` ou levanta `ScraperError`.
O fetcher nao sabe o que e Discord.
"""

from __future__ import annotations

from typing import Protocol

from ..models import FetchResult


class Fetcher(Protocol):
    def fetch(self) -> FetchResult:
        """Coleta uma observacao.

        Raises:
            UpstreamUnavailable: rede, timeout, 5xx -- transitorio.
            UpstreamRejected: 403/429 -- o alvo nos recusou.
            UnexpectedPayload: o JSON mudou de formato -- exige acao humana.
        """
        ...

    def close(self) -> None:
        """Libera a sessao/conexoes."""
        ...
