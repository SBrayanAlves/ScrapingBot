"""Instancia unica.  BUG-14"""

from __future__ import annotations

import pytest

from scrapingbot.errors import AlreadyRunningError
from scrapingbot.lock import InstanceLock


def test_segunda_instancia_e_recusada(tmp_path):
    """Duas instancias produzem alertas duplicados e `database is locked` --
    que antes era engolido pelo `except Exception` generico do rn_service."""
    caminho = tmp_path / "bot.lock"
    primeira = InstanceLock(caminho)
    primeira.acquire()
    try:
        with pytest.raises(AlreadyRunningError, match="outra instancia"):
            InstanceLock(caminho).acquire()
    finally:
        primeira.release()


def test_lock_liberado_pode_ser_readquirido(tmp_path):
    caminho = tmp_path / "bot.lock"
    with InstanceLock(caminho):
        pass
    with InstanceLock(caminho):
        pass  # nao levanta


def test_lock_grava_o_pid(tmp_path):
    """O pid no arquivo e o que permite a mensagem "ja rodando, pid N".

    No Windows o `msvcrt.locking` bloqueia o range 0-1 ate para leitura vinda
    do proprio processo, entao a conferencia do conteudo so vale no POSIX --
    que e onde o bot roda em producao.
    """
    import os

    caminho = tmp_path / "bot.lock"
    with InstanceLock(caminho):
        assert caminho.exists()
        if os.name != "nt":
            assert caminho.read_text(encoding="utf-8").strip() == str(os.getpid())
