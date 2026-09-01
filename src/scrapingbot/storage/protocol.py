"""Interface de persistencia vista pela regra de negocio.  ARQ-2

A regra de negocio nao sabe que existe SQLite. Ela conhece estes seis metodos.
E o que permite `test_service.py` rodar em milissegundos com um repositorio de
memoria -- o teste mais valioso do projeto, hoje impossivel de escrever.
"""

from __future__ import annotations

from typing import Protocol

from ..models import Event, RunResult, Snapshot


class Repository(Protocol):
    def last_snapshot(self) -> Snapshot | None:
        """Ultima observacao gravada, ou None no primeiro boot."""
        ...

    def save_snapshot(self, snapshot: Snapshot) -> Snapshot:
        """Persiste a observacao. SEMPRE chamado, mudando o valor ou nao.  BUG-8"""
        ...

    def save_event(self, event: Event) -> Event:
        """Grava o evento como pendente. Devolve o evento com id.  BUG-13"""
        ...

    def mark_notified(self, event_id: int) -> None:
        """Confirma a entrega. So depois disso o evento sai da fila."""
        ...

    def mark_notification_failed(self, event_id: int, error: str) -> None:
        """Registra a tentativa falha; o evento continua pendente."""
        ...

    def pending_events(self, limit: int = 20) -> list[Event]:
        """Eventos persistidos que ainda nao foram entregues."""
        ...

    def save_run(self, run: RunResult) -> None:
        """Registra o ciclo -- inclusive os que nao acharam novidade.  DAT-1"""
        ...
