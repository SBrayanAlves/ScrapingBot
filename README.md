# 🕷️ ScrapingBot

Monitor de catálogo: consulta um endpoint público de busca de uma loja online,
detecta quando novos itens entram no ar e avisa em um canal do Discord.

Roda sozinho, em container, e — mais importante — **sabe dizer quando não está
funcionando**.

```
┌──────────┐   ┌───────────┐   ┌─────────┐   ┌──────────┐
│ Fetcher  │──▶│  Service  │──▶│  Repo   │   │ Notifier │
│  (HTTP)  │   │ regra pura│──▶│(SQLite) │   │(Discord) │
└──────────┘   └─────┬─────┘   └─────────┘   └────▲─────┘
                     └───────── outbox ───────────┘
```

---

## Início rápido

```bash
git clone https://github.com/SBrayanAlves/ScrapingBot.git
cd ScrapingBot
cp .env.example .env          # preencha as 5 variáveis obrigatórias

docker compose run --rm scrapingbot doctor -n 5    # confere o alvo
docker compose run --rm scrapingbot once --dry-run # um ciclo, sem notificar
docker compose up -d                               # no ar
```

Sem Docker:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m scrapingbot run
```

---

## Comandos

| Comando | Para quê |
|---|---|
| `run` | Laço principal (padrão) |
| `once [--dry-run]` | Um único ciclo — ideal para depurar |
| `doctor [-n N]` | **É o bot, o cache do alvo ou bloqueio?** Ver abaixo |
| `stats [-d DIAS]` | Relatório: taxa de sucesso, latência, horários de publicação |
| `maintenance` | Retenção, agregação e backup sob demanda |
| `healthcheck` | Sai 0 se houve coleta recente (usado pelo `HEALTHCHECK`) |
| `import-legacy ARQ` | Importa o `DataBase.db` da v1 |
| `config` | Configuração efetiva, com segredos ocultos |

### `doctor` — o comando que responde "por que está atrasando?"

```console
$ python -m scrapingbot doctor -n 5
backend=curl_cffi  alvo=<oculto>
[1] valor=480      hash=3f1a9c02e8b74d15 latencia=  312ms  http=200  Age=0    cache=MISS  perfil=chrome-133-win
[2] valor=480      hash=3f1a9c02e8b74d15 latencia=   89ms  http=200  Age=47   cache=HIT   perfil=chrome-133-win
...

--- diagnostico ---
Corpo IDENTICO nas 5 coletas (hash 3f1a9c02e8b74d15).
E o header Age subiu de 0s para 188s: voce esta lendo uma resposta em cache.
O atraso e da borda do alvo, nao do bot.
```

Ele separa as três hipóteses: **bug do bot**, **cache do CDN** ou **bloqueio**.

---

## O que mudou da v1 (e por quê)

Esta é a v2. A v1 funcionava, mas tinha um defeito que explica exatamente a
queixa que originou a reescrita — *"a notificação está atrasando"*:

> `if difference > 2:` guardava **a notificação E o `INSERT`**. Aumentos de 1 ou
> 2 itens nunca eram persistidos nem notificados — o banco ficava defasado e o
> alerta só disparava depois que o acúmulo cruzava 3. Se o alvo publica de um em
> um, o alerta chega com duas publicações de atraso.

O `CHANGELOG.md` lista as 79 correções. As quatro que mais importam:

| | |
|---|---|
| **Persistir ≠ notificar** | Todo valor observado é gravado; o limiar decide só se alguém é acordado (`ALERT_THRESHOLD`, padrão 1) |
| **Outbox** | O alerta só sai da fila quando o Discord confirma. Antes, uma falha de entrega perdia o alerta **para sempre** e em silêncio |
| **Dead-man's switch** | Um serviço externo alerta pela *ausência* do ping. O heartbeat antigo era enviado pelo próprio bot — se ele morresse, o sinal era silêncio |
| **Stealth coerente** | Identidade completa por sessão, trocada junto com os cookies. A v1 trocava de User-Agent **mantendo os cookies**, o que é sinal de detecção, não disfarce |

---

## Stealth

O bot consulta um endpoint **público** — o mesmo que o navegador de qualquer
visitante chama — a ~60 requisições/hora, com backoff ao primeiro sinal de
recusa.

O detalhe que mais importa e que quase todo tutorial ignora: **o maior vetor de
detecção não é o User-Agent, é o fingerprint de TLS e HTTP/2.** Um "Chrome 133"
que fala HTTP/1.1 com a ordem de cifras do OpenSSL não engana ninguém.

```bash
pip install "scrapingbot[stealth]"   # habilita o backend curl_cffi
```

📖 **[`docs/stealth.md`](docs/stealth.md)** — o playbook completo: o que foi
feito, o que ainda falta, o que **não** vale a pena, e como validar contra o
alvo real usando o DevTools.

---

## Configuração

Tudo por variável de ambiente, validado no boot — se faltar uma obrigatória, o
processo para dizendo **o nome dela**. Nenhum número mágico ficou no código:
limiar de alerta, cadência, retenção, timeouts e limites de plausibilidade são
todos ajustáveis sem rebuild.

Cinco obrigatórias: `URL`, `P_URL`, `REFERER`, `DISCORD_ALERT_WEBHOOK`,
`DISCORD_LOG_WEBHOOK`. As ~30 opcionais estão documentadas uma a uma em
[`.env.example`](.env.example).

---

## Dados

| Tabela | Uma linha por | Responde |
|---|---|---|
| `snapshots` | observação | qual era o valor às 14h32 de terça? |
| `events` | mudança | o alerta foi entregue? quando? |
| `runs` | **ciclo** | o bot rodou? com que latência? |
| `run_hourly` | hora (agregado) | como estava a saúde há 8 meses? |

Migrações versionadas por `PRAGMA user_version`; retenção que **agrega antes de
descartar**; backup diário via `VACUUM INTO` com rotação.

`stats` usa isso para responder a pergunta mais útil que o sistema coleta e a
v1 jogava fora: **a que horas o alvo publica.**

---

## Estrutura

```
src/scrapingbot/
├── __main__.py          # composition root: monta tudo e injeta
├── config.py            # dataclass frozen, validada no boot
├── clock.py             # tempo injetável (a suíte roda em 0,3s por causa dele)
├── service.py           # ← regra de negócio pura, sem I/O
├── scheduler.py         # laço, backoff, SIGTERM, janela, manutenção
├── models.py errors.py lock.py
├── fetch/               # protocol · http · profiles (stealth)
├── storage/             # protocol · sqlite · migrations · maintenance
├── notify/              # protocol · discord (embeds, Retry-After)
└── observability/       # logging (run_id, redação) · heartbeat
tests/                   # 111 testes, sem rede e sem banco real
docs/                    # MELHORIAS · decisoes · operacao · stealth
```

---

## Desenvolvimento

```bash
pip install -e ".[dev]"
pre-commit install

pytest                        # 111 testes, ~0,3s
ruff check src tests && ruff format src tests
mypy
```

CI roda lint, tipos, testes, build da imagem, `pip-audit` e `trivy` a cada PR.

---

## Documentação

- **[`docs/entenda.md`](docs/entenda.md)** — 👈 **comece aqui se você escreveu a
  v1**: o que mudou, o que ignorar, e como mexer em cada coisa
- **[`docs/operacao.md`](docs/operacao.md)** — deploy, migração da v1,
  diagnóstico, rotação de webhook, backup
- **[`docs/stealth.md`](docs/stealth.md)** — anti-detecção, com ordem de
  prioridade e o que evitar
- **[`docs/decisoes.md`](docs/decisoes.md)** — ADRs: por que SQLite, por que o
  limiar 1, por que não Pydantic
- **[`docs/status-melhorias.md`](docs/status-melhorias.md)** — os 79 pontos da
  auditoria, um a um, e onde cada um foi resolvido
- **[`docs/MELHORIAS.md`](docs/MELHORIAS.md)** — a auditoria original que
  originou esta versão

---

## Licença

MIT — ver [`LICENSE`](LICENSE).
