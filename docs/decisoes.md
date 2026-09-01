# Decisões de arquitetura (ADRs)

Registro curto do **porquê**. Um repositório que só mostra o *o quê* obriga
todo leitor futuro — inclusive você daqui a seis meses — a redescobrir o
raciocínio por tentativa e erro.

---

## ADR-1 · Portas e adaptadores, não camadas por nome

**Contexto.** A v1 tinha `scraper.py`, `database.py`, `service.py`,
`notifier.py` — a intenção de separar estava certa. Mas as setas apontavam para
todos os lados: o scraper importava o notifier e mandava mensagem sozinho; o
service escrevia SQL cru; três módulos liam o `.env` por conta própria.

**Decisão.** O núcleo (`service.py`) depende de três `Protocol` — `Fetcher`,
`Repository`, `Notifier`. As implementações concretas são injetadas em
`__main__.py`, o único arquivo que conhece todas as peças.

**Consequência.** O teste "subiu 3 produtos → notifica uma vez e persiste" roda
em milissegundos, sem rede, banco ou webhook. Na v1 ele era **impossível de
escrever** — e código difícil de testar é código mal acoplado visto de outro
ângulo.

---

## ADR-2 · SQLite continua sendo a escolha certa

**Contexto.** Tentação natural numa reescrita: trocar por Postgres.

**Decisão.** Fica SQLite.

**Por quê.** ~1.400 escritas/dia, um único escritor, um único host, sem
consulta concorrente. Postgres traria um segundo container, uma segunda coisa
para monitorar e um segundo jeito de o deploy falhar — para resolver um
problema que não existe. O problema nunca foi o banco; era o SQL cru espalhado
pela regra de negócio (ADR-1) e o schema que só guardava mudanças (ADR-4).

**Quando reconsiderar.** Múltiplos alvos com escrita concorrente (`PRD-1`), ou
necessidade de consulta a partir de outro processo/máquina.

---

## ADR-3 · Laço próprio com `Event.wait()`, não APScheduler nem cron

**Decisão.** `while not shutdown.is_set(): ... clock.wait(shutdown, delay)`.

**Por quê.** Resolve três coisas de uma vez e sem dependência: cadência
aleatória, desligamento gracioso (o `Event` acorda no SIGTERM em vez de esperar
o `sleep` terminar) e backoff. APScheduler seria peso desnecessário.

**Sobre o cron.** A v1 documentava `0 0 * * * python cleanup.py` — um cron **do
host**, que o container não tem e que o Dockerfile não instalava. A rotina de
retenção era código morto no deploy real. Agora a manutenção é uma tarefa do
próprio laço: um processo, um ponto de deploy.

---

## ADR-4 · Três tabelas, não uma

**Contexto.** `products(id, amount, date)` só recebia `INSERT` quando o valor
mudava, e só guardava a data.

**Decisão.**

| Tabela | Uma linha por | Responde |
|---|---|---|
| `snapshots` | observação | qual era o valor às 14h32 de terça? |
| `events` | mudança detectada | o alerta foi entregue? quando? |
| `runs` | **ciclo** | o bot rodou? quantas vezes? com que latência? |
| `run_hourly` | hora (agregado) | como estava a saúde há 8 meses? |

**Por quê.** Sem `runs`, "nada aconteceu" e "o bot morreu" são indistinguíveis
no banco — e o `HEALTHCHECK` do container não tem em que se basear, porque um
bot saudável em um dia sem novidade não escreveria nada.

Sem o timestamp completo, a informação **mais valiosa do sistema** é
descartada: para um bot cujo propósito é avisar quando produtos entram no ar, a
hora do dia é o que permite responder *"o alvo publica sempre por volta das 10h
de terça"*. A v1 coletava isso a cada minuto e jogava fora antes de gravar.

**Custo.** ~1.400 linhas/dia ≈ 100 KB/dia. Trivial, e o `run_hourly` mantém a
série histórica permanente por kilobytes/mês.

---

## ADR-5 · Outbox para a entrega

**Contexto.** A ordem na v1 era `INSERT` → `commit` → `send_message`. Se o
Discord falhasse, ninguém ficava sabendo — mas o banco já tinha o valor novo,
então na iteração seguinte a diferença era zero e **aquele lote nunca mais
seria notificado**.

**Decisão.** O evento nasce com `notified = 0`. Só depois de o Discord
confirmar é que vira `notified = 1`. Todo ciclo começa reprocessando a fila.

**Por quê.** É o pior tipo de falha possível para um sistema de alerta: falhar
exatamente na única coisa que justifica sua existência, e falhar em silêncio.
Duas colunas e ~10 linhas transformam entrega "melhor esforço" em garantida.

---

## ADR-6 · `alert_threshold = 1` por padrão

**Contexto.** A v1 tinha `if difference > 2`, sem explicação, guardando a
notificação **e** o `INSERT`.

**Decisão.** Persistir e notificar são decisões independentes. **Todo** valor
observado é gravado; o limiar decide apenas se alguém é acordado. Padrão 1,
configurável por `ALERT_THRESHOLD`.

**Por quê.** Se o alvo publica de um em um, o `> 2` fazia o alerta só disparar
depois de três publicações — e como o valor menor nem era persistido, o
descompasso acumulava. É a explicação mais provável para a queixa de
"notificação atrasando". Quem quiser menos ruído sobe o limiar por variável de
ambiente, sem tocar em código.

---

## ADR-7 · Validação de payload à mão, sem Pydantic

**Contexto.** A auditoria sugeriu Pydantic para validar a resposta.

**Decisão.** `_extract_amount()` percorre o caminho esperado e levanta
`UnexpectedPayload` nomeando **exatamente** onde quebrou e que chaves vieram.

**Por quê.** Extraímos **um campo** de um JSON. Pydantic é uma dependência de
peso considerável para isso, e a mensagem de erro artesanal aqui é mais útil
para diagnóstico (`quebrou em 'data.productSearch'; o que veio: ['errors']`) do
que a de um `ValidationError` genérico. Se o payload virar um objeto rico
(`PRD-1`, guardar os produtos), a decisão se inverte.

---

## ADR-8 · `curl_cffi` opcional, não obrigatório

Ver [`stealth.md §3`](stealth.md). Resumo: o fingerprint TLS/HTTP2 é o vetor de
detecção que headers não cobrem, e `curl_cffi` é a resposta — mas ele traz
binário próprio e nem toda plataforma tem wheel. Fica atrás da mesma interface
`Fetcher`, ativado por `FETCH_BACKEND`, com aviso no log quando indisponível.

---

## Apêndice · Notas de estudo sobre Docker

Movidas do Dockerfile (`INF-4`), onde poluíam um arquivo de produção. Um
Dockerfile descreve o que a imagem **é**, não o que o autor estava aprendendo.

**`EXPOSE`** é só documentação: declara qual porta a aplicação usa dentro do
container. Não abre nada — quem publica é o `-p host:container` do `docker run`
ou o `ports:` do compose. Este projeto não é servidor, então não há porta a
expor; o `EXPOSE $PORT` da v1 expandia para vazio.

**`ARG`** parametriza o **build** (`docker build --build-arg X=1`); **`ENV`**
define variável no **runtime**. `ARG` não sobrevive ao `docker run`.

**Multi-stage** existe para que as ferramentas de compilação (aqui, o `gcc` que
`brotli` e `zstandard` precisam) fiquem no estágio de build e não entrem na
imagem final.
