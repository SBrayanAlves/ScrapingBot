"""Lock de instancia unica.  BUG-14

Os cenarios sao reais: o container sobe enquanto o cron do host ainda esta
ativo; um `docker run` e disparado duas vezes; a limpeza roda junto com o laco.
O resultado sao alertas duplicados e dois escritores disputando o SQLite --
`database is locked`, que antes era engolido pelo `except Exception` generico.

Barato, e elimina uma classe inteira de bug fantasma.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import TracebackType

from .errors import AlreadyRunningError

log = logging.getLogger(__name__)


class InstanceLock:
    """Lock de arquivo exclusivo, adquirido no boot e solto na saida.

    Usa `fcntl` no Linux/macOS e `msvcrt` no Windows -- o servidor e Linux, mas
    o desenvolvimento e Windows e um lock que so funciona em um dos dois nao
    serve para nada.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            self._lock(handle)
        except OSError as exc:
            os.close(handle)
            existing = self._read_pid()
            raise AlreadyRunningError(
                f"Ja existe outra instancia do ScrapingBot em execucao "
                f"(lock: {self.path}{f', pid {existing}' if existing else ''}). "
                "Duas instancias produzem alertas duplicados -- esta vai encerrar."
            ) from exc

        os.ftruncate(handle, 0)
        os.write(handle, str(os.getpid()).encode())
        os.fsync(handle)
        self._handle = handle
        log.info("Lock adquirido em %s (pid %d)", self.path, os.getpid())

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._unlock(self._handle)
        finally:
            os.close(self._handle)
            self._handle = None
            self.path.unlink(missing_ok=True)

    def _read_pid(self) -> str | None:
        try:
            return self.path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    @staticmethod
    def _lock(handle: int) -> None:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle: int) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_UN)

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
