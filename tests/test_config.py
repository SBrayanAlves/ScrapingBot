"""Configuracao validada no boot e redacao de segredos no log."""

from __future__ import annotations

import logging

import pytest

from scrapingbot.config import load_settings
from scrapingbot.errors import ConfigError
from scrapingbot.observability.logging import RedactingFilter, redact

MINIMO = {
    "URL": "https://loja.example.com/api?fq=x",
    "P_URL": "https://loja.example.com/categoria",
    "REFERER": "https://loja.example.com/categoria",
    "DISCORD_ALERT_WEBHOOK": "https://discord.com/api/webhooks/1/aaa",
    "DISCORD_LOG_WEBHOOK": "https://discord.com/api/webhooks/2/bbb",
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Ambiente limpo: nenhuma variavel do .env real vaza para o teste."""
    for chave in [
        *MINIMO,
        "SCRAPINGBOT",
        "LOGGINGSBOT",
        "DB_PATH",
        "ALERT_THRESHOLD",
        "INTERVAL_MIN_S",
        "INTERVAL_MAX_S",
        "ACTIVE_DAYS",
        "ACTIVE_HOUR_START",
        "ACTIVE_HOUR_END",
        "FETCH_BACKEND",
        "TIMEZONE",
        "WARMUP_ENABLED",
    ]:
        monkeypatch.delenv(chave, raising=False)
    for chave, valor in MINIMO.items():
        monkeypatch.setenv(chave, valor)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "db.sqlite"))
    return monkeypatch


def carregar(tmp_path):
    """Aponta para um .env inexistente: so o ambiente do teste vale."""
    return load_settings(tmp_path / "nao-existe.env")


# ------------------------------------------------------------------ validacao
def test_variavel_faltando_falha_com_o_nome_dela(env, tmp_path):
    """`os.getenv` devolvia None em silencio e o erro aparecia muito depois,
    disfarcado de falha de rede dentro de um except que engolia tudo.  INF-5"""
    env.delenv("URL")
    with pytest.raises(ConfigError, match="URL"):
        carregar(tmp_path)


def test_nomes_antigos_do_env_continuam_funcionando(env, tmp_path):
    """O .env que ja esta no servidor nao pode quebrar no deploy.  ARQ-4"""
    env.delenv("DISCORD_ALERT_WEBHOOK")
    env.setenv("SCRAPINGBOT", "https://discord.com/api/webhooks/9/legado")
    assert carregar(tmp_path).alert_webhook.endswith("legado")


def test_intervalo_invertido_e_recusado(env, tmp_path):
    env.setenv("INTERVAL_MIN_S", "90")
    env.setenv("INTERVAL_MAX_S", "30")
    with pytest.raises(ConfigError, match="Intervalo"):
        carregar(tmp_path)


def test_valor_nao_numerico_e_recusado(env, tmp_path):
    env.setenv("ALERT_THRESHOLD", "muitos")
    with pytest.raises(ConfigError, match="ALERT_THRESHOLD"):
        carregar(tmp_path)


def test_janela_horaria_invalida_e_recusada(env, tmp_path):
    env.setenv("ACTIVE_HOUR_START", "20")
    env.setenv("ACTIVE_HOUR_END", "8")
    with pytest.raises(ConfigError, match="horaria"):
        carregar(tmp_path)


def test_dias_ativos_fora_da_faixa_sao_recusados(env, tmp_path):
    env.setenv("ACTIVE_DAYS", "1,9")
    with pytest.raises(ConfigError, match="ACTIVE_DAYS"):
        carregar(tmp_path)


def test_dias_ativos_sao_parseados(env, tmp_path):
    env.setenv("ACTIVE_DAYS", "1,3,6")
    assert carregar(tmp_path).active_days == frozenset({1, 3, 6})


def test_backend_desconhecido_e_recusado(env, tmp_path):
    env.setenv("FETCH_BACKEND", "selenium")
    with pytest.raises(ConfigError, match="FETCH_BACKEND"):
        carregar(tmp_path)


def test_fuso_invalido_e_recusado(env, tmp_path):
    env.setenv("TIMEZONE", "Marte/Olympus")
    with pytest.raises(ConfigError, match="TIMEZONE"):
        carregar(tmp_path)


def test_booleano_aceita_forma_em_portugues(env, tmp_path):
    env.setenv("WARMUP_ENABLED", "nao")
    assert carregar(tmp_path).warmup_enabled is False


def test_defaults_sao_sensatos(env, tmp_path):
    settings = carregar(tmp_path)
    assert settings.alert_threshold == 1  # nao mais o `> 2` magico  BUG-8
    assert settings.interval_min_s < settings.interval_max_s
    assert settings.timezone.key == "America/Sao_Paulo"  # BUG-7


def test_describe_nao_vaza_segredo_nem_alvo(env, tmp_path):
    saida = carregar(tmp_path).describe()
    assert "webhooks/1/aaa" not in saida
    assert "loja.example.com" not in saida
    assert "alert_webhook=<oculto>" in saida


# -------------------------------------------------------------------- redacao
@pytest.mark.parametrize(
    "texto",
    [
        "POST https://discord.com/api/webhooks/123456/abcDEF-token_secreto falhou",
        "erro em https://discordapp.com/api/webhooks/999/xyzTOKEN123",
    ],
)
def test_token_de_webhook_e_removido(texto):
    """Um segredo em log e um segredo vazado.  SEC-2"""
    limpo = redact(texto)
    assert "token" not in limpo.lower() or "[REDACTED]" in limpo
    assert "[REDACTED]" in limpo


def test_query_string_do_alvo_e_removida():
    limpo = redact("GET https://loja.com/api/search?fq=categoria&_=1234567890 -> 200")
    assert "fq=categoria" not in limpo


def test_filtro_aplica_redacao_na_mensagem_do_record():
    filtro = RedactingFilter()
    record = logging.LogRecord(
        "t",
        logging.ERROR,
        "f",
        1,
        "falhou em https://discord.com/api/webhooks/1/SEGREDO",
        (),
        None,
    )
    filtro.filter(record)
    assert "SEGREDO" not in record.getMessage()


def test_filtro_aplica_redacao_nos_argumentos():
    """`log.warning("erro: %s", exc)` -- o segredo costuma vir pelo argumento."""
    filtro = RedactingFilter()
    record = logging.LogRecord(
        "t",
        logging.ERROR,
        "f",
        1,
        "erro: %s",
        ("https://discord.com/api/webhooks/1/SEGREDO",),
        None,
    )
    filtro.filter(record)
    assert "SEGREDO" not in record.getMessage()


# ------------------------------------------------- descoberta do arquivo .env
def test_env_e_encontrado_a_partir_do_diretorio_atual(env, tmp_path, monkeypatch):
    """O caso do cron: `cd /projeto && .venv/bin/python -m scrapingbot run`.

    Com `pip install .` o pacote vive em site-packages, entao procurar o .env
    a partir de onde o CODIGO esta aponta para dentro da venv. O bot morria no
    boot dizendo que faltava URL, mesmo com o .env preenchido do lado.
    """
    projeto = tmp_path / "projeto"
    projeto.mkdir()
    (projeto / ".env").write_text(
        "URL=https://do-arquivo.example/api\n"
        "P_URL=https://do-arquivo.example\n"
        "REFERER=https://do-arquivo.example\n"
        "DISCORD_ALERT_WEBHOOK=https://discord.com/api/webhooks/7/zzz\n"
        "DISCORD_LOG_WEBHOOK=https://discord.com/api/webhooks/8/www\n",
        encoding="utf-8",
    )
    for chave in MINIMO:
        monkeypatch.delenv(chave, raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.chdir(projeto)

    settings = load_settings()
    assert settings.env_file == projeto / ".env"
    assert settings.target_url == "https://do-arquivo.example/api"


def test_banco_fica_ao_lado_do_env_encontrado(env, tmp_path, monkeypatch):
    """Sem DB_PATH, o banco acompanha o .env -- nunca o cwd por acidente."""
    projeto = tmp_path / "outro"
    projeto.mkdir()
    (projeto / ".env").write_text(
        "URL=https://x.example/api\nP_URL=https://x.example\nREFERER=https://x.example\n"
        "DISCORD_ALERT_WEBHOOK=https://discord.com/api/webhooks/1/a\n"
        "DISCORD_LOG_WEBHOOK=https://discord.com/api/webhooks/2/b\n",
        encoding="utf-8",
    )
    for chave in MINIMO:
        monkeypatch.delenv(chave, raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.chdir(projeto)

    assert load_settings().db_path == projeto / "data" / "scrapingbot.db"


def test_env_file_explicito_inexistente_nao_cai_para_o_cwd(env, tmp_path):
    """`--env-file` apontando para nada = usar so o ambiente, sem surpresa."""
    settings = load_settings(tmp_path / "nao-existe.env")
    assert settings.env_file is None
