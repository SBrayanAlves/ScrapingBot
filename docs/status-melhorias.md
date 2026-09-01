# Status da auditoria — onde cada ponto foi resolvido

Rastreabilidade dos 79 pontos de [`MELHORIAS.md`](MELHORIAS.md) para o código
da v2.0.0. Os identificadores aparecem como comentário no próprio arquivo, então
`grep -rn "BUG-8" src/` leva direto à correção.

**Placar: 74 aplicados · 3 parciais · 2 decisões do dono.**

---

## BUG — quebrava em produção (18)

| ID | Status | Onde |
|---|---|---|
| BUG-1 UTF-16 no requirements | ✅ | `requirements.txt` (UTF-8) + hook `fix-byte-order-marker` |
| BUG-2 pacote `logging` do PyPI | ✅ | `pyproject.toml` — só deps diretas; `pytz`/`six` fora |
| BUG-3 `cleanup.py` executa no import | ✅ | Arquivo eliminado; virou `storage/maintenance.py`, chamado pelo laço |
| BUG-4 `requests` sem timeout | ✅ | `notify/discord.py` — `timeout=self.timeout_s` |
| BUG-5 banco pelo `cwd` | ✅ | `config.py` — `DB_PATH`; nunca `os.getcwd()` |
| BUG-6 `Accept-Encoding` mentiroso | ✅ | `fetch/profiles.py::supported_accept_encoding` + `brotli`/`zstandard` nas deps |
| BUG-7 `datetime.now()` sem fuso | ✅ | `clock.py` — sempre UTC aware; `TIMEZONE` só na exibição |
| BUG-8 **`> 2` engolia notificação e INSERT** | ✅ | `service.py::decide` + `Thresholds`; testes `test_aumento_de_um_gera_alerta`, `test_todo_valor_observado_e_persistido_mesmo_sem_alerta` |
| BUG-9 `filemode="w"` apagava o log | ✅ | `observability/logging.py` — `RotatingFileHandler` |
| BUG-10 transação sem rollback | ✅ | `storage/sqlite.py::connection` — commit/rollback/close |
| BUG-11 `any` minúsculo | ✅ | Tipagem completa; `mypy` limpo |
| BUG-12 limpeza nunca rodava no Docker | ✅ | `scheduler.py::_run_maintenance_if_due` |
| BUG-13 alerta perdido em silêncio | ✅ | Outbox: `events.notified` + `service.py::_flush_pending` |
| BUG-14 duas instâncias | ✅ | `lock.py::InstanceLock` (fcntl/msvcrt) |
| BUG-15 valor absurdo vira `@everyone` | ✅ | `EventKind.ANOMALY` → canal de log, não público |
| BUG-16 orçamento de ciclo | ✅ | `CYCLE_DEADLINE_S`; `duration_ms` gravado em `runs` |
| BUG-17 falha não muda cadência | ✅ | `scheduler.py::_next_delay` — backoff exponencial + jitter |
| BUG-18 `send_message` sempre `None` | ✅ | `Notifier.send` levanta `NotificationError` |

## INF — Docker e configuração (6)

| ID | Status | Onde |
|---|---|---|
| INF-1 banco morre com o container | ✅ | `VOLUME`, `DB_PATH`, volume nomeado no compose |
| INF-2 `.env.example` dessincronizado | ✅ | `.env.example` — 35 variáveis, uma comentada por vez |
| INF-3 `.dockerignore` deixava `data/` | ✅ | `.dockerignore` |
| INF-4 `EXPOSE $PORT` + notas de estudo | ✅ | Removido; notas em `decisoes.md` (apêndice) |
| INF-5 nada validado no boot | ✅ | `config.py::load_settings` — erro nomeia a variável |
| INF-6 `chown -R` + sem HEALTHCHECK | ✅ | Usuário antes do COPY; `HEALTHCHECK` chama `healthcheck` |

## ARQ — arquitetura (8)

| ID | Status | Onde |
|---|---|---|
| ARQ-1 scraper conhece o Discord | ✅ | `fetch/protocol.py` — devolve `FetchResult` ou levanta |
| ARQ-2 SQL na regra de negócio | ✅ | `storage/protocol.py` + `sqlite.py` |
| ARQ-3 `load_dotenv` em 3 módulos | ✅ | Só em `config.py` |
| ARQ-4 dois `ScrapingBot` diferentes | ✅ | `alert_webhook` / `log_webhook` |
| ARQ-5 dois `_pass`/`_WARNING` | ✅ | `observability/heartbeat.py::HealthTracker` |
| ARQ-6 sem desligamento gracioso | ✅ | `scheduler.py` — SIGTERM + `Event.wait()` |
| ARQ-7 `makedirs` no import | ✅ | `SqliteRepository.setup()` |
| ARQ-8 README ≠ código (janela) | ✅ | `ACTIVE_DAYS`/`ACTIVE_HOUR_*` — **default 24/7; defina se a janela importa** |

## OBS — observabilidade (5)

| ID | Status | Onde |
|---|---|---|
| OBS-1 `docker logs` vazio | ✅ | `StreamHandler(sys.stdout)` |
| OBS-2 logger raiz, sem traceback | ✅ | `getLogger(__name__)`, `%s` preguiçoso, `log.exception` |
| OBS-3 log sem rotação | ✅ | `RotatingFileHandler` + `max-size` no compose |
| OBS-4 tudo vira "Validation Error" | ✅ | `errors.py` — hierarquia; `RunStatus` por categoria |
| OBS-5 heartbeat mente | ✅ | Falhas consecutivas + alerta único que rearma |

## ENG — engenharia e testes (13)

| ID | Status | Onde |
|---|---|---|
| ENG-1 zero testes | ✅ | 111 testes; os 4 pedidos, mais outbox/lock/config/redação |
| ENG-2 sem lint/format/tipos | ✅ | `ruff` + `mypy` + `pre-commit` |
| ENG-3 sem CI | ✅ | `.github/workflows/ci.yml` |
| ENG-4 `pip freeze` | ✅ | `pyproject.toml` (diretas) + `requirements.txt` (lock) |
| ENG-5 sem migrações | ✅ | `storage/migrations.py` — `PRAGMA user_version` |
| ENG-6 comentários que mentem | ✅ | Reescritos; `attempt` no lugar de `_` |
| ENG-7 não instalável | ✅ | `src/scrapingbot`, `[project.scripts]`, `python -m scrapingbot` |
| ENG-8 tempo não injetável | ✅ | `clock.py` — `SystemClock` / `FakeClock` |
| ENG-9 números mágicos | ✅ | Todos em `Settings`, com override por env |
| ENG-10 sem LICENSE/CHANGELOG | ✅ | `LICENSE` (MIT), `CHANGELOG.md`, `.editorconfig` |
| ENG-11 `Project.txt` versionado | ✅ | → `docs/historico-projeto.txt`; a verdade está nos ADRs |
| ENG-12 git sem história | ⚠️ **você** | Ferramental pronto (CI + pre-commit). Branch/PR/conventional commits daqui pra frente |
| ENG-13 sem CD nem versão de imagem | ◐ parcial | Imagem versionada (`scrapingbot:2.0.0`); publicação no `ghcr.io` não configurada |

## SCR — scraping e stealth (5 + 3 novos)

| ID | Status | Onde |
|---|---|---|
| SCR-1 UA rotativo com cookies fixos | ✅ | `fetch/http.py::_new_session` — identidade inteira por sessão |
| SCR-2 `Content-Type` em GET | ✅ | `fetch/profiles.py::api_headers` + `Sec-CH-UA` coerentes |
| SCR-3 `fake_useragent` | ✅ | 5 perfis fixos e coerentes; dependência removida |
| SCR-4 retry do Discord ignora 429 | ✅ | `notify/discord.py::_retry_after` |
| SCR-5 `@everyone` | ✅ | `ALERT_MENTION` + `allowed_mentions` restrito |
| **SCR-6** fingerprint TLS/HTTP2 | ✅ novo | Backend `curl_cffi` opcional — o vetor que headers não cobrem |
| **SCR-7** detecção de resposta congelada | ✅ novo | `payload_hash` + `Age` + alerta de staleness |
| **SCR-8** aquecimento incoerente | ✅ novo | `document_headers` na página, `api_headers` no XHR |

## DAT — dados (8)

| ID | Status | Onde |
|---|---|---|
| DAT-1 só grava mudanças | ✅ | Tabelas `runs` + `events` + `snapshots` |
| DAT-2 granularidade de dia | ✅ | `observed_at` ISO-8601 UTC com offset |
| DAT-3 `products` não guarda produtos | ✅ | → `snapshots` |
| DAT-4 sem índice | ✅ | 4 índices criados junto com as tabelas |
| DAT-5 retenção mágica de 6 dias | ✅ | Agrega em `run_hourly` **antes** de apagar |
| DAT-6 sem backup | ✅ | `VACUUM INTO` diário com rotação |
| DAT-7 `VACUUM` completo sempre | ✅ | Incremental na limpeza; completo mensal |
| DAT-8 PRAGMAs incompletos | ✅ | `synchronous=NORMAL`, `busy_timeout`, `auto_vacuum` |

## REL — confiabilidade (6)

| ID | Status | Onde |
|---|---|---|
| REL-1 heartbeat não detecta morte | ✅ | `DEADMAN_URL` — **precisa ser preenchido para valer** |
| REL-2 sem política de restart | ✅ | `restart: unless-stopped` + `try/except` de último recurso |
| REL-3 sem compose | ✅ | `docker-compose.yml` |
| REL-4 base não fixada por digest | ◐ parcial | Instruções no Dockerfile; **o digest tem que ser gerado na sua máquina** |
| REL-5 sem `run_id` | ✅ | `contextvars` + filtro de logging |
| REL-6 sem limites de recurso | ✅ | `mem_limit: 256m`, `cpus: 0.5` |

## SEC — segurança (4)

| ID | Status | Onde |
|---|---|---|
| SEC-1 webhooks sem rotação | ◐ parcial | Procedimento em `operacao.md §6`; **mover o `.env` para fora do OneDrive é ação sua** |
| SEC-2 segredo no log | ✅ | `RedactingFilter`; o notifier nunca interpola a exceção crua |
| SEC-3 sem varredura | ✅ | `pip-audit` + `trivy` no CI |
| SEC-4 legitimidade não documentada | ⚠️ **você** | Checklist em `stealth.md §6`; **só você pode conferir `robots.txt` e ToS do alvo** |

## PRD — evolução (6)

| ID | Status | Onde |
|---|---|---|
| PRD-1 multi-alvo | ⬜ próximo | Arquitetura já suporta (as interfaces existem); falta o `monitors.yaml` |
| PRD-2 notificação rica | ✅ | Embeds com cor, antes → depois, link, timestamp |
| PRD-3 relatório | ✅ | `scrapingbot stats` — inclui horários de publicação |
| PRD-4 múltiplos canais | ✅ base | `Notifier` é `Protocol`; um `TelegramNotifier` é uma classe nova |
| PRD-5 proxies | ⬜ | Deliberadamente **não** feito — ver `stealth.md §4` |
| PRD-6 hash do payload | ✅ | `payload_hash` gravado em `snapshots` |

---

## O que depende de você

1. **`DEADMAN_URL`** — maior retorno por linha da auditoria, e só funciona
   depois de criar o check no healthchecks.io.
2. **Digest da imagem base** (`REL-4`) — precisa ser gerado no seu ambiente.
3. **Mover o `.env` para fora do OneDrive** em produção (`SEC-1`).
4. **Preencher `stealth.md §6`** com `robots.txt` e ToS do alvo (`SEC-4`).
5. **Decidir a janela de operação** (`ARQ-8`): hoje o default é 24/7. Se
   terça/quinta/domingo 8h–19h ainda é a intenção real, ponha
   `ACTIVE_DAYS=1,3,6`, `ACTIVE_HOUR_START=8`, `ACTIVE_HOUR_END=19`.
6. **Branch + PR daqui pra frente** (`ENG-12`) — o CI já roda nos PRs.
