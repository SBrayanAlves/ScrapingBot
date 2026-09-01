# Plano de Melhorias — ScrapingBot

> **Base:** commit `71ab8f1` · 6 módulos · ~330 linhas
> **Auditoria 1:** 41 pontos — status **0/41 aplicados** (worktree idêntico ao commit auditado)
> **Auditoria 2 (esta):** +38 pontos novos
> **Total: 79 pontos** · Objetivo: reescrita do projeto em nível sênior

---

## 0. Como ler este documento

A **Auditoria 1** olhou para o código como ele está: o que quebra, o que não testa, o que não sobe.
A **Auditoria 2** olha para o sistema como ele *opera ao longo do tempo*: o que acontece depois de três meses rodando sozinho, o que você não consegue responder quando algo dá errado, e o que falta para isso deixar de ser um script e virar um produto.

Os dois conjuntos estão aqui porque nenhum foi aplicado ainda — e porque a reescrita deve resolver os dois de uma vez, não em sequência.

**Convenção de IDs:** `BUG` (quebra hoje) · `INF` (Docker/config) · `ARQ` (arquitetura) · `OBS` (observabilidade) · `ENG` (engenharia/testes) · `SCR` (scraping/stealth) · `DAT` (dados) · `REL` (confiabilidade) · `SEC` (segurança) · `PRD` (produto).

### Placar

| Categoria | Auditoria 1 | Auditoria 2 | Total |
|---|---:|---:|---:|
| BUG — quebra em produção | 11 | 7 | 18 |
| INF — Docker e configuração | 6 | — | 6 |
| ARQ — arquitetura | 8 | — | 8 |
| OBS — observabilidade | 5 | — | 5 |
| ENG — engenharia e testes | 6 | 7 | 13 |
| SCR — scraping e stealth | 5 | — | 5 |
| DAT — modelagem e retenção de dados | — | 8 | 8 |
| REL — confiabilidade e operação | — | 6 | 6 |
| SEC — segurança | — | 4 | 4 |
| PRD — evolução de produto | — | 6 | 6 |
| **Total** | **41** | **38** | **79** |

Por severidade — **auditoria 2:** 1 crítico · 9 alto · 16 médio · 6 baixo · 6 evolução.
**Acumulado (79):** 5 críticos · 21 alto · 36 médio · 11 baixo · 6 evolução.

---

# PARTE I — Auditoria 1 (todos ainda abertos)

## BUG — Coisas que já estão quebradas

| ID | Sev | Problema | Correção |
|---|---|---|---|
| **BUG-1** | 🔴 Crítico | `requirements.txt` está em **UTF-16** (BOM `FF FE`, 2 bytes por caractere) — resultado de `pip freeze >` no PowerShell. O `pip` espera UTF-8, então o `RUN pip install` do Docker falha. **A imagem não sobe numa máquina limpa hoje.** | Regravar em UTF-8. Nunca usar redirecionamento do PowerShell: `pip freeze \| Out-File -Encoding utf8` |
| **BUG-2** | 🔴 Crítico | `logging==0.4.9.6` **não é a stdlib** — é um pacote abandonado do PyPI de 2004 que só está no índice porque ninguém reivindicou o nome. É o vetor exato de *dependency confusion*. `pytz` e `six` também estão listados sem serem importados. | Remover `logging`, `pytz`, `six`. Deixar só `requests`, `python-dotenv`, `fake-useragent` |
| **BUG-3** | 🔴 Crítico | `cleanup.py:42-43` — `limpeza = Clear()` e `limpeza.main()` estão em nível de módulo. **Qualquer `import cleanup` executa `DELETE` + `VACUUM`.** | `if __name__ == "__main__":`. Regra geral: nenhum módulo faz trabalho real ao ser importado |
| **BUG-4** | 🟠 Alto | `src/notifier.py:11` — único `requests` do sistema **sem `timeout`**. Se o Discord aceitar o TCP e não responder, o laço principal congela para sempre: sem log, sem alerta, sem processo morto para o supervisor reiniciar | `timeout=10`, como você já fez certo no scraper |
| **BUG-5** | 🟠 Alto | `src/database.py:15` usa `os.getcwd()` em vez do `root_dir` calculado 2 linhas antes. Rodando por cron, o bot cria um banco vazio em outro lugar e compara contra o nada. **A prova está no repo: existem dois `DataBase.db`**, um na raiz e outro em `data/`, com datas diferentes | Trocar por `root_dir`; apagar o banco órfão após conferir qual tem os dados bons |
| **BUG-6** | 🟠 Alto | `scraper.py:53` anuncia `Accept-Encoding: br, zstd`, mas nem `brotli` nem `zstandard` estão instalados. Se o servidor honrar, você recebe bytes binários e `response.json()` estoura. Funciona hoje por sorte | Instalar `urllib3[brotli,zstd]` **ou** reduzir para `gzip, deflate`. Anunciar só o que você processa |
| **BUG-7** | 🟠 Alto | `datetime.now()` sem timezone. Containers `python:slim` rodam em UTC; no Brasil (UTC−3) tudo entre 21h e meia-noite grava a data do dia seguinte — desalinhando o `cleanup.py` e corrompendo qualquer análise histórica | `ZoneInfo("America/Sao_Paulo")` (stdlib, dispensa `pytz`) — ou melhor: gravar UTC ISO-8601 e converter só na exibição |
| **BUG-8** | 🟡 Médio | `service.py:60` — `if difference > 2` guarda **a notificação E o `INSERT`**. Aumentos de 1 ou 2 nunca são persistidos: o banco fica defasado e o contador acumula. Se o alvo publica de um em um, o alerta nunca dispara | Separar as decisões: **sempre** persistir o observado; usar o limiar **só** para decidir se notifica. O `2` é número mágico sem explicação |
| **BUG-9** | 🟡 Médio | `main.py:16` — `filemode="w"` apaga o log inteiro a cada reinício. O momento em que você mais precisa do log é logo após um crash, que é exatamente quando ele é zerado. E não há rotação | `RotatingFileHandler` com `maxBytes` e `backupCount` — ver OBS-1 e OBS-3 |
| **BUG-10** | 🟡 Médio | `get_connection` só tem `try/finally: close()`. Uma exceção entre `execute` e `commit` descarta a transação por acidente, não por intenção. E o `commit` está espalhado pelos chamadores — a fronteira transacional não é visível | O context manager vira dono da transação: `commit()` no sucesso, `rollback()` no `except`, `close()` no `finally`. Some todo `conn.commit()` dos chamadores |
| **BUG-11** | 🟢 Baixo | `validate_data(data: any)` — `any` minúsculo é a função builtin, não `typing.Any`. Assinatura exata de código que nunca passou por type checker | O tipo honesto aqui é `int \| None` |

## INF — Docker e configuração

| ID | Sev | Problema | Correção |
|---|---|---|---|
| **INF-1** | 🟠 Alto | **O banco morre junto com o container.** `DOCKER_ENV` decide se o caminho é `/app/data`, mas essa variável não é definida em lugar nenhum do Dockerfile. E não há `VOLUME` nem instrução de montagem no README — todo `docker rm` zera o histórico e o bot volta ao estado "primeira execução" | `ENV DOCKER_ENV=1` + `VOLUME ["/app/data"]`, documentar `-v scrapingbot-data:/app/data`. Melhor: eliminar a variável e ler `DB_PATH` |
| **INF-2** | 🟠 Alto | `.env.example` declara `URL`, `WEBHOOK`, `WEBHOOK_LOGGINGS`. O código lê `URL`, `P_URL`, `REFERER`, `SCRAPINGBOT`, `LOGGINGSBOT`. **Quem clonar não consegue rodar** — e descobre isso via `requests.get(None)` | Sincronizar + comentário de uma linha por variável. Um `.env.example` errado é pior que nenhum |
| **INF-3** | 🟡 Médio | `.dockerignore` ignora `DataBase.db` mas **não a pasta `data/`**. O `COPY . .` assa o seu banco local — com o histórico real de coletas — dentro de cada imagem | Adicionar `data/` e `*.db` |
| **INF-4** | 🟡 Médio | `EXPOSE $PORT` — `$PORT` nunca é definido, expande para vazio. E o projeto não é servidor. Os ~15 comentários sobre mapeamento de portas são notas de estudo | Remover; mover as notas para arquivo próprio. Dockerfile de produção descreve o que a imagem *é* |
| **INF-5** | 🟡 Médio | **Nenhuma variável de ambiente é validada no boot.** `os.getenv` devolve `None` em silêncio e o erro aparece muito depois, disfarçado de falha de rede, dentro de um `except` que engole tudo | `src/config.py` com `@dataclass(frozen=True)` carregado uma vez, que levanta erro **nomeando** a variável faltante |
| **INF-6** | 🟢 Baixo | `RUN chown -R appuser /app` duplica o tamanho de tudo que foi copiado (camada nova com cópias). E não há `HEALTHCHECK` | `COPY --chown=appuser:appuser`, usuário criado antes do COPY. `HEALTHCHECK` que verifique se o bot escreveu no banco nos últimos N minutos — testa vida real, não "o processo existe" |

## ARQ — Arquitetura

| ID | Sev | Problema | Correção |
|---|---|---|---|
| **ARQ-1** | 🟠 Alto | **O scraper conhece o Discord** — seta de dependência ao contrário. `scraper.py` importa `notifier` e `webhook` e envia mensagens sozinho. Resultado: não dá para testar o scraper sem webhook válido, não dá para reaproveitá-lo, e "quando alertar" vive em três arquivos | `catch_data` retorna `int` ou levanta `ScraperError`. O service captura e decide. O scraper não importa nada de Discord |
| **ARQ-2** | 🟠 Alto | **SQL cru dentro da regra de negócio.** `rn_service` abre cursor, escreve `SELECT`, dois `INSERT` idênticos e chama `commit`, tudo misturado com a decisão. O `DataBaseManager` não é camada de dados — é fornecedor de conexões | `ProductRepository` com `last_amount() -> int \| None` e `save(amount)`. O service fica com ~15 linhas de regra pura. **Este item é o que destrava ENG-1** |
| **ARQ-3** | 🟡 Médio | `load_dotenv` é chamado em 3 módulos — e em `database.py` **duas vezes** (linhas 7 e 17). Cada módulo carrega configuração por conta própria em vez de recebê-la | Consolidar no `config.py` do INF-5. Os módulos recebem valores no construtor |
| **ARQ-4** | 🟡 Médio | Duas coisas diferentes se chamam `ScrapingBot`: a classe em `service.py` e a string de URL em `webhook.py`. O `import ScrapingBot as DScraping` em dois arquivos é o sintoma | Constantes em `UPPER_SNAKE_CASE` com nomes de papel: `DISCORD_ALERT_WEBHOOK`, `DISCORD_LOG_WEBHOOK` |
| **ARQ-5** | 🟡 Médio | Dois pares `_pass`/`_WARNING` com o mesmo nome e o mesmo limite 15 fazendo coisas diferentes (`main.py` e `scraper.py`). Vão dessincronizar assim que um ciclo falhar | Um único `HeartbeatReporter(every=15)`, reportando em um lugar só |
| **ARQ-6** | 🟡 Médio | **Sem desligamento gracioso.** `while True` não trata `SIGTERM`/`SIGINT`. O Docker manda SIGTERM, espera 10s e mata — pegando transação aberta ou requisição em voo | `signal.signal(SIGTERM, ...)` ligando uma flag; `while not shutdown.is_set()` e `shutdown.wait(delay)` no lugar do sleep — o container também passa a parar na hora |
| **ARQ-7** | 🟡 Médio | `os.makedirs(...)` em nível de módulo (`database.py:19`) — **importar cria diretórios no disco.** Segundo caso de import com efeito colateral, junto com BUG-3 | Mover para `__init__` ou `start_setup` |
| **ARQ-8** | 🟢 Baixo | O README promete cron às terças, quintas e domingos, 8h–19h, intervalo de 1–3 min. O `main.py` é `while True` com `random.uniform(45, 75)`: **roda 24/7, quase 3× mais rápido.** O `Project.txt` ainda marca o item 6 como concluído | Decidir qual é a verdade. Se a janela importa, ela precisa estar **no código** — o container ignora o cron do host |

## OBS — Observabilidade

| ID | Sev | Problema | Correção |
|---|---|---|---|
| **OBS-1** | 🟠 Alto | **`docker logs` não mostra absolutamente nada.** `basicConfig(filename=...)` manda tudo para um arquivo dentro do container. O `PYTHONUNBUFFERED=1` do Dockerfile existe justamente para o caso oposto. Para investigar, você precisa entrar no container — e o arquivo pode já ter sido zerado pelo BUG-9 | `StreamHandler` para stdout. Log em container vai para stdout; o runtime coleta |
| **OBS-2** | 🟡 Médio | Tudo escreve no logger **raiz** — nenhuma linha diz de onde veio. E `logging.error(f"...")` formata mesmo com o nível desligado, além de impedir agrupamento por template | `log = logging.getLogger(__name__)` por módulo + formatação preguiçosa `log.error("erro: %s", e)`. Em `except`, `log.exception(...)` — traz o traceback que hoje você joga fora |
| **OBS-3** | 🟡 Médio | Log cresce sem limite dentro de container sem volume. Falha que aparece três meses depois, de madrugada | `RotatingFileHandler(maxBytes=5_000_000, backupCount=3)` — ou parar de escrever em arquivo se OBS-1 for resolvido |
| **OBS-4** | 🟡 Médio | Falha de rede chega ao log **disfarçada de erro de validação**: `catch_data` devolve `None` → `validate_data` levanta `ValueError` → service loga `"Validation Error/Logic"`. Timeout, 503 e JSON com formato novo produzem a mesma linha | Hierarquia de exceções: `ScraperError` → `UpstreamUnavailable` / `UnexpectedPayload`. Um 503 você espera; mudança de payload você precisa saber **agora** — significa que o bot está cego |
| **OBS-5** | 🟡 Médio | **O heartbeat avisa que o bot está vivo, não que está funcionando.** Se o alvo passar a devolver 403 para sempre, você continua recebendo `[HEALTHBEAT]` a cada 15 ciclos, indefinidamente, sem nenhum dado sendo coletado | Contador de falhas **consecutivas** que dispara alerta distinto ao cruzar ~5 e para de repetir até recuperar. Meia dúzia de linhas para 90% do valor de um circuit breaker |

## ENG — Engenharia e testes

| ID | Sev | Problema | Correção |
|---|---|---|---|
| **ENG-1** | 🔴 Crítico | **Zero testes.** É o primeiro lugar onde um revisor olha, e a ausência responde a pergunta antes de qualquer código ser lido. Sem testes, cada correção desta lista é uma aposta | Não precisa de cobertura alta, precisa dos 4 certos: **(1)** a regra de negócio com repositório falso — vazio, subiu, desceu, igual, subiu 1 (o BUG-8); **(2)** `validate_data` com `None`, negativo, string, float; **(3)** o parse do JSON com fixture real + versão com chave faltando; **(4)** `catch_data` com `responses`/`requests-mock`: 200, 429, timeout, JSON malformado. **O teste 1 só é possível depois do ARQ-2** — não é coincidência: código difícil de testar é código mal acoplado visto de outro ângulo |
| **ENG-2** | 🟠 Alto | Sem linter, sem formatador, sem type checker. Imports não usados, espaços no fim de linha, aspas inconsistentes, o BUG-11 — tudo isso um linter pega em um segundo | `ruff` (lint + format em uma ferramenta), `mypy` permissivo apertando aos poucos, `pre-commit` — ferramenta que depende de disciplina não funciona |
| **ENG-3** | 🟠 Alto | **Sem CI.** O histórico mostra commits direto no `main` com mensagens como "Atualizando". O BUG-1 passou despercebido justamente porque **nenhuma máquina limpa nunca tentou instalar o projeto** | GitHub Actions de ~20 linhas: instala deps, roda `ruff`, roda `pytest`, faz `docker build`. Só isso já teria pego 2 dos 4 críticos. O badge verde é o sinal mais barato de maturidade que existe |
| **ENG-4** | 🟡 Médio | `requirements.txt` de `pip freeze` mistura o que você escolheu com o que veio junto. `certifi`, `idna`, `charset-normalizer`, `urllib3` estão lá porque `requests` os trouxe — e agora você fixa as versões dos quatro | `pyproject.toml` com dependências **diretas** + lock gerado à parte (`uv lock` / `pip-compile`). Fica claro o que é decisão e o que é consequência |
| **ENG-5** | 🟡 Médio | **Sem versionamento de schema.** `CREATE TABLE IF NOT EXISTS` cobre banco novo e só. No dia em que você adicionar uma coluna, todo banco existente continua com o schema velho e o `INSERT` falha em produção | Não precisa de Alembic: `PRAGMA user_version` + lista de funções de migração aplicadas em ordem. ~20 linhas |
| **ENG-6** | 🟢 Baixo | Comentários que mentem: `database.py:12-14` afirma que `root_dir` termina em `/src` (é o pai de `src`); os comentários `4.1`/`4.2` de `service.py` estão trocados em relação ao `Project.txt`; `notifier.py:9` declara `for _ in` como descartável e depois usa `_+1` | Apagar o que descreve o óbvio, corrigir o que mente, renomear para `attempt`. **Comentário errado é pior que comentário nenhum, porque o leitor confia nele** |

## SCR — Scraping e stealth

| ID | Sev | Problema | Correção |
|---|---|---|---|
| **SCR-1** | 🟠 Alto | **Trocar de User-Agent mantendo os mesmos cookies é sinal de detecção, não disfarce.** `catch_data` sorteia UA novo a cada requisição, mas a `Session` é a mesma. Do lado do servidor: uma sessão única que muda de navegador e de SO a cada 60s. Nenhum usuário real faz isso — **você criou o padrão tentando se esconder** | Um UA por sessão, fixo. Para rotacionar, recrie a sessão inteira: cookies novos, identidade nova, coerente do começo ao fim |
| **SCR-2** | 🟡 Médio | `Content-Type: application/json` em requisição **GET**. GET não tem corpo — navegador nenhum envia isso. Junto com a ausência dos `Sec-CH-UA` que qualquer Chrome recente manda (e que o seu UA afirma ser), o conjunto é internamente inconsistente | Remover o `Content-Type`. Referência de verdade: copiar a requisição real do DevTools como cURL e comparar header por header |
| **SCR-3** | 🟡 Médio | `fake_useragent` instancia no `__init__` e pode buscar dados na rede — o boot depende de um terceiro. Pior: devolve UAs de qualquer navegador e versão, inclusive combinações improváveis que destoam dos seus headers | Lista fixa de 4–5 **perfis completos e coerentes** (UA + Sec-CH-UA + Accept-Language combinando), escolhendo um perfil inteiro por sessão. Menos dependências, mais realista, testável |
| **SCR-4** | 🟡 Médio | **O retry do Discord ignora 429 e o `Retry-After`.** 3 tentativas com 3s fixos — e no `except` nem dorme, então as três saem quase instantaneamente. O Discord limita webhooks de forma agressiva | Respeitar `Retry-After` no 429, backoff exponencial no resto, `sleep` também no `except`. O `HTTPAdapter` que você já configurou no scraper serve aqui |
| **SCR-5** | 🟢 Baixo | Cadência real: 45–75 req/h, sem parar, todos os dias — o README descreve operação bem mais leve. E `@everyone` em todo alerta é o caminho mais rápido para silenciarem o canal | Cargo mencionável opt-in em vez de `@everyone`. Documentar a base da taxa escolhida — mesmo que a resposta seja "o robots.txt permite e o volume é irrelevante", **ter pensado nisso é o que se espera** |

---

# PARTE II — Auditoria 2 (achados novos)

## BUG — Novos defeitos

### BUG-12 🔴 Crítico — O `cleanup.py` nunca roda na versão Docker

O `CMD` da imagem é `["python", "main.py"]`. Não há cron, nem `supervisord`, nem segundo processo, nem agendador dentro do código. **A rotina de retenção que você escreveu é código morto no deploy atual.** O README documenta `0 0 * * * python cleanup.py`, mas isso pressupõe um cron *do host* que o container não tem e que o Dockerfile não instala.

Consequência: o banco cresce indefinidamente dentro de um volume que (por INF-1) nem existe. Você tem retenção implementada e retenção zero na prática.

**Correção:** trazer a limpeza para dentro do processo — um agendador simples no laço principal ("se passou meia-noite desde a última limpeza, limpe") elimina o segundo ponto de deploy. Isso também resolve o BUG-14 de graça, porque deixa de existir um segundo processo escrevendo no banco.

### BUG-13 🟠 Alto — Alerta e persistência não são atômicos: alertas somem em silêncio

Em `service.py:62-69` a ordem é: `INSERT` → `commit` → `send_message`. Se as 3 tentativas do `send_message` falharem, a função retorna `None` e **ninguém fica sabendo**. Mas o banco já foi atualizado — então na próxima iteração `last_amount` já é o valor novo, a diferença é zero, e **aquele lote de produtos nunca mais será notificado.**

É o pior tipo de falha para um sistema de alerta: ele falha exatamente na única coisa que justifica existir, e falha em silêncio.

**Correção — padrão *outbox*:** persistir o evento com `notified = 0`, tentar notificar, marcar `notified = 1` no sucesso. No começo de cada ciclo, reprocessar os pendentes. Duas colunas e ~10 linhas transformam entrega "melhor esforço" em entrega garantida.

### BUG-14 🟠 Alto — Nada impede duas instâncias simultâneas

Não há lock, PID file, nem checagem de instância única. Os cenários são reais: o container sobe enquanto o cron do host ainda está ativo; um `docker run` é disparado duas vezes; o `cleanup.py` roda concorrente ao `main.py`. Resultado: **alertas duplicados** e duas conexões disputando o SQLite com `timeout=7` — o WAL segura leitura concorrente, mas dois escritores em rajada produzem `database is locked`, que hoje seria engolido pelo `except Exception` genérico do `rn_service`.

**Correção:** lock de arquivo exclusivo (`fcntl.flock` no Linux) adquirido no boot, com mensagem clara e saída imediata se já houver instância. Barato e elimina uma classe inteira de bug fantasma.

### BUG-15 🟡 Médio — Sem sanity check: um valor absurdo vira `@everyone`

`validate_data` rejeita `None` e negativos, e para por aí. Se o alvo mudar o contrato da API e o campo `recordsFiltered` passar a significar o catálogo inteiro, o bot calcula `50000 - 480 = 49520` e dispara **"@everyone 🚨 acabou de cair 49520 PRODUTO(S)"**. O mesmo vale para o caminho oposto: um `0` legítimo de manutenção do site vira uma "queda" gravada como verdade.

**Correção:** um limite de plausibilidade (`MAX_DELTA_PLAUSIVEL`) — variações acima dele não viram alerta no canal público; viram alerta de *anomalia* no canal de log, que é a informação realmente acionável ("o alvo mudou alguma coisa"). Conecta diretamente com OBS-4.

### BUG-16 🟡 Médio — O orçamento de tempo do ciclo não fecha

Somando o pior caso de um ciclo: `sleep` interno de 1,5–3,5s + `Retry(total=3, backoff_factor=2)` (≈ 0s + 4s + 8s de espera) + `timeout=10` por tentativa = **até ~40s dentro de um ciclo cujo intervalo é 45–75s**. Somando as até 3 tentativas do `send_message` com 3s entre elas, o ciclo pode ultrapassar o intervalo. Sob instabilidade do alvo, os ciclos deixam de ser periódicos e a cadência real vira imprevisível.

**Correção:** definir um *deadline* explícito por ciclo e medir a duração real, reportando-a no heartbeat (liga com OBS-5). Um sistema periódico que não mede o próprio tempo de ciclo não sabe se está periódico.

### BUG-17 🟡 Médio — Falha do alvo não muda a cadência

O `delay` é `random.uniform(45, 75)` incondicionalmente. Se o alvo passar a devolver 403 ou 503 permanentemente, o bot continua batendo ~60 vezes por hora, para sempre, contra um servidor que já o rejeitou. Isso transforma uma falha temporária em bloqueio permanente de IP, e é o oposto do comportamento "stealth" que o resto do código busca.

**Correção:** backoff exponencial com teto no laço principal, contado por falhas consecutivas e zerado no primeiro sucesso. O contador já é necessário para OBS-5 — é o mesmo estado servindo a dois propósitos.

### BUG-18 🟢 Baixo — `send_message` não informa se conseguiu enviar

A função retorna `None` no sucesso, `None` ao esgotar as tentativas e `None` na exceção. O chamador não tem como distinguir. É a raiz mecânica do BUG-13 e impede qualquer métrica de entrega.

**Correção:** retornar `bool` (ou levantar `NotificationError`) e fazer o chamador reagir.

---

## DAT — Modelagem e retenção de dados *(categoria nova)*

### DAT-1 🟠 Alto — O banco só registra mudanças, então "nada aconteceu" e "o bot está morto" são indistinguíveis

A tabela só recebe `INSERT` quando o valor muda. Isso significa que **não existe nenhum registro de que o bot rodou.** Você não consegue responder: quantos ciclos rodaram ontem? qual a taxa de sucesso? quando foi a última coleta bem-sucedida? o bot ficou parado entre 3h e 7h?

E sem essa resposta, o `HEALTHCHECK` proposto no INF-6 ("escreveu no banco nos últimos N minutos") **não pode ser implementado** — um bot saudável em um dia sem novidade não escreve nada e seria marcado como morto.

**Correção:** separar dois conceitos que hoje estão fundidos em uma tabela só:

- **`runs`** — uma linha por ciclo: `started_at`, `status`, `latency_ms`, `observed_amount`, `error`. É a fonte de verdade da saúde do sistema.
- **`events`** — uma linha por mudança detectada: `observed_at`, `previous`, `current`, `delta`, `notified`. É a fonte de verdade do negócio.

Custo: ~1.400 linhas/dia em `runs`, algo como 100 KB/dia. Trivial para SQLite e transforma o sistema de "cego" em "auditável".

### DAT-2 🟠 Alto — `date TEXT` com granularidade de dia joga fora a informação mais valiosa

O `strftime("%Y-%m-%d")` descarta a hora. Mas para um bot cujo propósito é avisar quando produtos entram no ar, **a hora do dia é a informação de maior valor do sistema** — é o que permite responder "o alvo publica sempre por volta das 10h de terça". Você está coletando essa informação a cada minuto e descartando-a antes de gravar.

**Correção:** `observed_at TEXT NOT NULL` em ISO-8601 UTC com offset (`2026-08-26T14:32:07+00:00`), convertendo para America/São_Paulo só na exibição. Resolve BUG-7 na origem.

### DAT-3 🟡 Médio — A tabela `products` não guarda produtos

Ela guarda uma contagem. Um leitor novo abre o schema, vê `products(id, amount, date)` e assume que `amount` é preço ou estoque **de um produto**. O nome custa uma pergunta a cada pessoa que encosta no código — e ocupa o nome que a tabela de verdade vai querer usar se um dia você guardar os itens (PRD-1).

**Correção:** `snapshots` ou `observations`. Renomear agora, na reescrita, custa uma migração; renomear depois custa uma migração e uma janela de deploy.

### DAT-4 🟡 Médio — Sem índice, e o `DELETE` da limpeza é full scan

`DELETE FROM products WHERE date < ...` percorre a tabela inteira. Com 40 linhas isso é irrelevante; com o `runs` do DAT-1 (~1.400 linhas/dia, ~500 mil/ano) deixa de ser. Índice em `observed_at` é obrigatório assim que o volume subir — e o momento de criá-lo é junto com a tabela, não depois do problema.

### DAT-5 🟡 Médio — Retenção de 6 dias é número mágico e destrói o histórico

`date("now", "-6 days")` não está documentado em lugar nenhum e conflita com todo o valor descrito no DAT-2: você não pode identificar padrão semanal de publicação com 6 dias de janela. E depois do DAT-1 o mesmo `DELETE` apagaria também o histórico de saúde.

**Correção:** retenção em dois níveis — descartar o **detalhe** (`runs`) depois de N dias, mas **agregar antes de descartar** (contagem por hora, taxa de sucesso, latência p95) em uma tabela de resumo que nunca é apagada. Kilobytes por mês, histórico permanente.

### DAT-6 🟡 Médio — Sem backup

O banco é o único estado do sistema — se ele sumir, o bot volta ao "primeiro boot" e perde a linha de base de comparação. Não há cópia, nem local nem remota. Combinado com INF-1 (banco em camada efêmera) e BUG-12 (nenhum job agendado roda), a probabilidade de perda total não é hipotética.

**Correção:** `VACUUM INTO 'backup-YYYY-MM-DD.db'` — atômico, consistente, uma linha de SQL, sem parar o bot — com rotação de N cópias no mesmo agendador do BUG-12.

### DAT-7 🟢 Baixo — `VACUUM` completo a cada limpeza

`VACUUM` reescreve o banco inteiro sob lock exclusivo. Com o volume atual é imperceptível; depois do DAT-1, não. E ele só é acionado quando houve deleção, o que o torna imprevisível.

**Correção:** `PRAGMA auto_vacuum = INCREMENTAL` + `incremental_vacuum` na limpeza, reservando o `VACUUM` completo para uma cadência mensal.

### DAT-8 🟢 Baixo — PRAGMAs incompletos para o modo WAL

`PRAGMA journal_mode=WAL` é executado a cada conexão (ele é persistente no arquivo — bastaria uma vez), mas faltam os dois que realmente importam junto dele: `synchronous=NORMAL` (com WAL é seguro e reduz muito o fsync) e `busy_timeout` (o `timeout=7` do `connect` cobre parte dos casos, mas explicitar é mais claro e se aplica de forma uniforme).

---

## REL — Confiabilidade e operação *(categoria nova)*

### REL-1 🟠 Alto — O heartbeat não detecta a falha mais provável: o bot morrer

O `[HEALTHBEAT]` é enviado **pelo próprio bot**. Se o processo cair, o container for morto pelo OOM killer, ou o host reiniciar, o sinal não é um alerta — é **silêncio**. E silêncio é exatamente o que ninguém percebe. O sistema é capaz de reportar todos os problemas menos o único que o desliga por completo.

**Correção — *dead-man's switch*:** um `GET` a cada ciclo para um serviço externo (healthchecks.io, Cronitor, ou um endpoint próprio) configurado para **alertar pela ausência do ping**. Inverte a lógica: quem avisa passa a ser um terceiro que continua vivo quando você não está. Gratuito nos planos básicos, 3 linhas de código, e é o item de maior retorno por linha desta auditoria inteira.

### REL-2 🟠 Alto — Sem política de restart

Nem `--restart unless-stopped`, nem unidade systemd, nem compose. Qualquer exceção que escape do `try/except` do `rn_service` — ou qualquer erro no próprio `while True`, que não tem proteção nenhuma — encerra o processo e o monitoramento simplesmente para até alguém notar. Combinado com REL-1, "alguém notar" pode levar dias.

**Correção:** `restart: unless-stopped` no compose **e** um `try/except` de último recurso em volta do corpo do laço, para que um erro em um ciclo não mate o processo. As duas coisas, não uma.

### REL-3 🟡 Médio — Sem `docker-compose.yml`

Volume, `env_file`, política de restart, limite de tamanho de log e limites de memória hoje dependem de alguém lembrar da linha de comando correta — e essa linha não está documentada em lugar nenhum (INF-1). Um deploy que só existe na memória de quem o fez não é um deploy, é uma lembrança.

**Correção:** um `docker-compose.yml` de ~20 linhas vira a documentação executável do deploy inteiro, incluindo `logging: options: max-size` que resolve OBS-3 no nível do runtime.

### REL-4 🟡 Médio — Imagem base não fixada por digest

`FROM python:3.13-slim` aponta para uma tag móvel. O build de hoje e o de daqui a um mês produzem imagens diferentes, e uma regressão vinda da base é indistinguível de uma regressão sua.

**Correção:** `FROM python:3.13-slim@sha256:...` com atualização deliberada (Dependabot/Renovate abre o PR).

### REL-5 🟡 Médio — Sem `run_id` correlacionando as linhas de um mesmo ciclo

Com ~1.400 ciclos por dia escrevendo no mesmo log, reconstituir "o que aconteceu naquele ciclo específico" significa cruzar timestamps a olho. Nenhuma linha de log carrega identidade do ciclo.

**Correção:** um `run_id` curto gerado no início do ciclo e injetado em todas as linhas via `logging.LoggerAdapter` ou `contextvars`. É o que torna o log pesquisável em vez de apenas legível.

### REL-6 🟢 Baixo — Sem limites de recursos no container

Nenhum `mem_limit` / `cpus`. Um vazamento de memória (a `Session` persistente acumula cookies indefinidamente) derruba o host inteiro em vez de só o container — e sem limite, o OOM killer escolhe a vítima, que pode não ser o bot.

---

## SEC — Segurança *(categoria nova)*

### SEC-1 🟠 Alto — Webhooks são credenciais de escrita sem escopo, sem expiração e sem plano de rotação

A URL do webhook do Discord **é** a credencial: quem a tiver posta no seu canal como o bot, para sempre, sem autenticação adicional. Elas estão em um `.env` de texto puro no servidor, sem rotação, e não há registro de quando foram criadas. O `.env` não está no git (correto), mas o `.env` está em uma pasta do **OneDrive** — ou seja, sincronizado para a nuvem e para qualquer máquina com a mesma conta.

**Correção:** documentar o procedimento de rotação, tratar o `.env` como material sensível fora de pasta sincronizada em produção, e considerar segredos gerenciados (Docker secrets) no deploy.

### SEC-2 🟡 Médio — Sem redação de segredos no log

`log.warning(f"[FINAL NETWORK ERROR] - {error}")` — uma `RequestException` do `requests` **inclui a URL completa** na mensagem. No scraper isso vaza os parâmetros do alvo; no notifier (`send_message`, cujo `except` também loga a exceção) isso vaza **o token do webhook** para o arquivo de log — e, com OBS-1 resolvido, para o stdout do container e para qualquer coletor de logs.

**Correção:** um filtro de logging que reescreve padrões conhecidos (`discord.com/api/webhooks/\d+/\S+` → `[REDACTED]`) antes da linha ser emitida. Um segredo em log é um segredo vazado, porque logs são copiados para lugares onde ninguém pensa em segredos.

### SEC-3 🟡 Médio — Sem varredura de vulnerabilidades

Nenhum `pip-audit` nas dependências, nenhum `trivy` na imagem. `fake-useragent` (que faz I/O de rede no boot, SCR-3) e a base `slim` entram sem verificação. Duas linhas no CI do ENG-3.

### SEC-4 🟢 Baixo — Nada documenta a legitimidade da coleta

Não há registro de `robots.txt` verificado, de ToS do alvo, nem justificativa para a taxa escolhida. Para um projeto de scraping, **essa é a primeira pergunta que um entrevistador faz** — e a resposta "não pensei nisso" desqualifica o resto do trabalho técnico. Um parágrafo no README que diga qual endpoint público é consultado, em que taxa e por quê muda o enquadramento inteiro do projeto.

---

## ENG — Engenharia (novos)

### ENG-7 🟠 Alto — O projeto não é um pacote instalável

`src/` é um nome genérico que não pode ser importado sem ambiguidade (dezenas de projetos têm um `src`), não há `pyproject.toml`, `__main__.py`, nem entrypoint declarado. Isso significa: não dá para `pip install .`, não dá para rodar de outro diretório, e o `sys.path` funciona hoje por acidente de estar sempre executando da raiz — o mesmo acidente que produz o BUG-5.

**Correção:** `scrapingbot/` como nome do pacote, `pyproject.toml` com `[project.scripts]`, e execução via `python -m scrapingbot`. Depois disso o caminho do banco deixa de depender do cwd por construção, não por correção.

### ENG-8 🟠 Alto — O tempo não é injetável, então metade dos testes fica impossível

`time.sleep`, `time.time`, `datetime.now` e `random.uniform` são chamados diretamente nos módulos. Todo comportamento interessante do sistema é **temporal** — "alerta a cada 15 ciclos", "limpa depois de 6 dias", "faz backoff crescente" — e nenhum deles pode ser testado sem esperar de verdade ou sem monkeypatch frágil.

**Correção:** um `Clock` (`now()`, `sleep()`) injetado no construtor, com uma implementação real e uma falsa controlada pelo teste. É a diferença entre uma suíte que roda em 0,2s e uma que ninguém executa.

### ENG-9 🟡 Médio — Números mágicos espalhados por seis arquivos

`> 2` (limiar de alerta), `15` (heartbeat, em dois lugares), `45–75` (intervalo), `1.5–3.5` (delay interno), `6 days` (retenção), `timeout=10`, `timeout=7`, `TRY=3`, `total=3`, `backoff_factor=2`. **Dez decisões de comportamento**, nenhuma nomeada, nenhuma documentada, nenhuma ajustável sem editar código e reconstruir a imagem.

**Correção:** todas viram campos do objeto de configuração do INF-5, com default no código e override por variável de ambiente. Ajustar o limiar de alerta deixa de ser um deploy.

### ENG-10 🟡 Médio — Sem `LICENSE`, `CHANGELOG` nem `.editorconfig`

Repositório público sem licença significa que, juridicamente, ninguém pode usar, copiar ou contribuir — o padrão é "todos os direitos reservados". Para um projeto de portfólio, é o oposto da intenção.

### ENG-11 🟡 Médio — `Project.txt` é caderno de rascunho versionado

Ele marca o item 6 ("Dia de funcionamento — Terça, Quinta, Domingo, 8 às 19") com ✓, e esse comportamento **não existe no código** (ARQ-8). Um documento de requisitos que afirma como concluído algo que nunca foi implementado é ativamente pior que a ausência dele.

**Correção:** virar `docs/` de verdade (decisões, arquitetura) ou sair do repositório. As notas de estudo do Dockerfile (INF-4) vão para o mesmo lugar.

### ENG-12 🟡 Médio — Fluxo de git não conta história nenhuma

14 commits direto no `main`, mensagens como "Atualizando", "Scraper", "Requirements.txt". Nenhuma branch, nenhum PR, nenhuma referência ao *porquê* de cada mudança. Para um projeto de portfólio, **o histórico do git é lido** — é a única evidência disponível de como você trabalha quando ninguém está olhando.

**Correção:** branch por mudança, PR mesmo trabalhando sozinho (é onde o CI do ENG-3 roda antes do merge), e conventional commits (`fix:`, `feat:`, `refactor:`). A reescrita é a oportunidade natural: cada onda do roteiro vira uma branch.

### ENG-13 🟢 Baixo — Sem CD nem versionamento de imagem

O build é manual, a imagem não tem tag de versão, e não há registry. Não existe forma de responder "qual versão está rodando em produção?" nem de voltar para a anterior.

**Correção:** o mesmo workflow do ENG-3 publica em `ghcr.io` com tag de versão e `latest` a cada tag do git.

---

## PRD — Evolução do produto *(não são defeitos — são o próximo nível)*

| ID | Ideia | Por que vale |
|---|---|---|
| **PRD-1** | **Multi-alvo.** Um `monitors.yaml` com N alvos, cada um com URL, limiar, cadência e canal de destino | É a diferença entre um script e um produto. Também força a arquitetura certa: se dois alvos cabem, o acoplamento foi resolvido de verdade |
| **PRD-2** | **Notificação rica.** Embed do Discord com cor por tipo de evento, timestamp, valor anterior → novo, e link direto para a página | Custa 15 linhas e é a parte do sistema que outra pessoa realmente vê. Hoje é uma string com `@everyone` (SCR-5) |
| **PRD-3** | **Relatório.** Nada no sistema lê o banco. Um comando `stats` (ou uma página estática gerada) com histórico, horários de pico de publicação e taxa de sucesso | Dá propósito aos dados do DAT-1/DAT-2. E "o bot descobriu que o alvo publica às terças de manhã" é um resultado, não um log |
| **PRD-4** | **Múltiplos canais** (Telegram, e-mail) atrás de uma interface `Notifier` | A abstração já quase existe — `send_message(mensagem, canal)` está a um passo de virar um protocolo. Depois do ARQ-1 é quase de graça |
| **PRD-5** | **Proxies / rotação de saída**, se e quando a taxa justificar | Só faz sentido **depois** de SCR-1/SCR-2/SCR-3 — trocar de IP mantendo um fingerprint inconsistente não esconde nada |
| **PRD-6** | **Hash do payload bruto** gravado a cada coleta | Detecta mudança de contrato da API *antes* que ela quebre o parse. Quando o hash da estrutura muda mas o valor não, você tem aviso prévio em vez de post-mortem |

---

# PARTE III — Arquitetura-alvo da reescrita

## Direção das dependências

O erro estrutural de hoje é que **as setas apontam para dentro e para os lados ao mesmo tempo**: o scraper importa o notifier, o service escreve SQL, todo mundo lê o `.env` sozinho. A regra da reescrita é uma só — **o núcleo não importa nada de infraestrutura**.

```
                    ┌──────────────┐
                    │   __main__   │  composition root: monta tudo e injeta
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  scheduler   │  laço, backoff, sinais, lock, deadline
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   service    │  ← REGRA DE NEGÓCIO PURA (sem I/O)
                    └──┬───┬───┬───┘     testável com fakes, 100% coberta
                       │   │   │
          ┌────────────┘   │   └────────────┐
          │                │                │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
   │  Fetcher    │  │ Repository  │  │  Notifier   │   ← interfaces (Protocol)
   ├─────────────┤  ├─────────────┤  ├─────────────┤
   │ HttpFetcher │  │SqliteRepo   │  │DiscordNotif │   ← implementações
   │ FakeFetcher │  │ InMemoryRepo│  │ FakeNotifier│   ← usadas nos testes
   └─────────────┘  └─────────────┘  └─────────────┘
```

O teste mais valioso do projeto — "subiu 3 produtos, então notifica **uma vez** e persiste" — passa a ser 5 linhas, sem rede, sem banco, sem Discord, rodando em milissegundos. Hoje ele é impossível de escrever.

## Layout proposto

```
scrapingbot/
├── pyproject.toml              # deps diretas + ruff + mypy + pytest    ENG-4, ENG-7
├── uv.lock                     # lock separado das deps declaradas      ENG-4
├── docker-compose.yml          # volume, restart, env_file, log limits  REL-2, REL-3
├── Dockerfile                  # base por digest, HEALTHCHECK           REL-4, INF-6
├── .env.example                # sincronizado e comentado               INF-2
├── LICENSE · CHANGELOG.md      #                                        ENG-10
├── docs/
│   ├── MELHORIAS.md            # este documento
│   ├── decisoes.md             # ADRs: por que SQLite, por que o limiar ENG-11
│   └── operacao.md             # deploy, rotação de webhook, backup     SEC-1, DAT-6
├── src/scrapingbot/
│   ├── __main__.py             # python -m scrapingbot                  ENG-7
│   ├── config.py               # dataclass frozen, validada no boot     INF-5, ARQ-3, ENG-9
│   ├── clock.py                # Clock injetável                        ENG-8
│   ├── scheduler.py            # laço, backoff, SIGTERM, lock, dead-man ARQ-6, BUG-14/17, REL-1
│   ├── service.py              # regra pura — nenhum import de I/O      ARQ-1, ARQ-2
│   ├── models.py               # Snapshot, Event, RunResult
│   ├── errors.py               # ScraperError, UpstreamUnavailable, …   OBS-4
│   ├── fetch/
│   │   ├── protocol.py
│   │   └── http.py             # perfis de browser coerentes            SCR-1, SCR-2, SCR-3
│   ├── storage/
│   │   ├── protocol.py
│   │   ├── sqlite.py           # transação no context manager           BUG-10, DAT-8
│   │   ├── migrations.py       # PRAGMA user_version                    ENG-5
│   │   └── maintenance.py      # retenção + agregação + backup          BUG-12, DAT-5/6/7
│   ├── notify/
│   │   ├── protocol.py
│   │   └── discord.py          # embeds, Retry-After, outbox            PRD-2, SCR-4, BUG-13/18
│   └── observability/
│       ├── logging.py          # stdout, run_id, redação                OBS-1/2, REL-5, SEC-2
│       └── heartbeat.py        # falhas consecutivas, métricas          OBS-5, ARQ-5
└── tests/
    ├── conftest.py             # fakes de Fetcher / Repo / Notifier / Clock
    ├── test_service.py         # ★ o teste que justifica a reescrita
    ├── test_fetch.py           # fixtures reais: 200, 429, timeout, JSON quebrado
    ├── test_storage.py         # migrações, retenção, outbox
    └── test_notify.py          # 429 com Retry-After, falha total
```

## Decisões técnicas sugeridas

| Área | Hoje | Proposta | Motivo |
|---|---|---|---|
| Dependências | `requirements.txt` (UTF-16, `pip freeze`) | `pyproject.toml` + `uv` | Separa decisão de consequência; `uv` é ordens de magnitude mais rápido no CI |
| HTTP | `requests` | Manter `requests` | Trocar por `httpx`/async só se PRD-1 exigir concorrência real. 1 req/min não justifica |
| Banco | SQLite + SQL cru | SQLite + repositório | SQLite está **certo** para este volume. O problema nunca foi o banco |
| Validação | `int()` + checagem manual | `pydantic` no payload da resposta | Erro nomeado e imediato quando o alvo muda o contrato (OBS-4, PRD-6) |
| Agendamento | `while True` + `sleep` | Laço próprio com `Event.wait()` | `APScheduler` é peso desnecessário; o `Event.wait()` resolve ARQ-6 de graça |
| Testes | — | `pytest` + `responses` + fakes | `responses` cobre o HTTP; os fakes cobrem o resto |
| Qualidade | — | `ruff` + `mypy` + `pre-commit` | Uma ferramenta para lint+format, tipos apertando gradualmente |

---

# PARTE IV — Roteiro de execução

A ordem importa mais que a lista. **Refatorar antes de ter testes é exatamente como se quebra um sistema que funcionava.**

### Onda 0 · Parar o sangramento *(antes de qualquer reescrita)*
Correções pontuais no código atual, cada uma em um commit isolado. Risco quase zero, maior retorno imediato. Faça isso mesmo que a reescrita demore — são os itens que fazem o sistema atual funcionar de verdade enquanto o novo não chega.

`BUG-1` · `BUG-2` · `BUG-3` · `BUG-4` · `BUG-5` · `BUG-9` · `INF-2` · `INF-3` · `OBS-1` · `SEC-2`

### Onda 1 · Rede de segurança
Ferramentas e esqueleto do novo pacote **antes** de mover lógica. Aqui você ainda não muda comportamento — só ganha a capacidade de perceber quando quebrou algo.

`ENG-7` (pacote instalável) · `ENG-2` (ruff/mypy/pre-commit) · `ENG-4` (pyproject+lock) · `ENG-3` (CI) · `ENG-12` (branches e PRs) · `ENG-10` · `ENG-1` *parcial* (validação e parse — o que o código atual já permite testar)

### Onda 2 · Endireitar as dependências
O coração da mudança de nível. Config centralizada, repositório separado da regra, scraper que não sabe o que é Discord, clock injetável. **Depois desta onda o teste da regra de negócio passa a ser possível** — e é o mais valioso do projeto.

`INF-5` · `ARQ-1` · `ARQ-2` · `ARQ-3` · `ARQ-4` · `ENG-8` (clock) · `ENG-9` (config) · `OBS-4` (exceções) · `BUG-8` · `BUG-10` · `BUG-18` · `ENG-1` *(completar — inclusive `test_service.py`)*

### Onda 3 · Dados e entrega confiável
Com a regra isolada e testada, corrigir o que o sistema **grava** e o que ele **garante entregar**. É a onda que transforma "melhor esforço" em sistema confiável.

`DAT-1` (runs + events) · `DAT-2` (timestamp completo) · `DAT-3` · `DAT-4` · `ENG-5` (migrações) · `BUG-13` (outbox) · `BUG-7` (timezone) · `BUG-15` (sanity check) · `SCR-4` (Retry-After) · `PRD-2` (embeds)

### Onda 4 · Operação sem supervisão
O que faz o sistema sobreviver meses sozinho. Cada item aqui responde a uma pergunta que só aparece às 3h da manhã.

`REL-1` (**dead-man's switch — maior retorno por linha da auditoria**) · `REL-2` · `REL-3` · `REL-4` · `REL-5` · `REL-6` · `INF-1` · `INF-6` (healthcheck) · `BUG-12` (limpeza interna) · `BUG-14` (lock) · `BUG-16` · `BUG-17` (backoff) · `ARQ-6` (SIGTERM) · `ARQ-7` · `OBS-2` · `OBS-3` · `OBS-5` · `DAT-5` · `DAT-6` (backup) · `DAT-7` · `DAT-8` · `SEC-1` · `SEC-3` · `ENG-13` (CD)

### Onda 5 · Acabamento e stealth coerente
`SCR-1` (UA por sessão) · `SCR-2` · `SCR-3` (perfis coerentes) · `SCR-5` · `BUG-6` (Accept-Encoding) · `BUG-11` · `INF-4` · `ARQ-5` · `ARQ-8` (README ↔ código) · `ENG-6` · `ENG-11` · `SEC-4` (documentar legitimidade)

### Onda 6 · Produto
`PRD-1` (multi-alvo) · `PRD-3` (relatório) · `PRD-4` (multi-canal) · `PRD-6` (hash de payload) · `PRD-5` (proxies, se justificar)

---

## O que já está certo e não deve ser desfeito

Separação em camadas (a intenção está correta, só a direção das setas precisa mudar) · retry com backoff no scraper · context manager de conexão · WAL habilitado · usuário não-root no container · `.env` fora do versionamento · `.dockerignore` existente · `PYTHONDONTWRITEBYTECODE`/`PYTHONUNBUFFERED` · a decisão de usar SQLite, que continua sendo a escolha certa para este volume.

---

*Auditoria 1: 41 pontos · Auditoria 2: +38 pontos · Total: 79 · Base: commit `71ab8f1`*
