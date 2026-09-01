# Entendendo a v2 — guia para quem escreveu a v1

Este arquivo existe por um motivo simples: **você escreveu a v1 à mão e precisa
conseguir mexer na v2.** Código que o dono não entende não é uma melhoria, é um
problema novo.

A boa notícia: **a v2 faz exatamente a mesma coisa que a v1, do mesmo jeito.**
O que mudou foi *quem cria o quê* e *o que fica registrado*. Nenhuma ideia nova
de negócio entrou aqui.

---

## 1. Para onde foram as 2.233 linhas

Você tinha 331. Vamos ser honestos sobre a conta:

| Bloco | Linhas | Existia na v1? |
|---|---:|---|
| A lógica que você já tinha (coletar, comparar, gravar, notificar, repetir) | ~450 | ✅ sim, em 331 linhas — cresceu ~35% |
| Comandos novos de terminal (`doctor`, `stats`, `healthcheck`, `import-legacy`) | ~300 | ❌ não existiam |
| Configuração validada (`config.py`) | ~180 | ❌ era `os.getenv` espalhado |
| Migrações + backup + retenção do banco | ~280 | ⚠️ o `cleanup.py` tinha 42 linhas e nunca rodava no Docker |
| Perfis de navegador (stealth) | ~140 | ⚠️ eram 12 linhas de headers fixos |
| Log com `run_id` e redação de segredo | ~90 | ❌ era um `basicConfig` |
| Trava de instância única, relógio injetável, tipos de erro | ~200 | ❌ não existiam |
| "Contratos" (`protocol.py` × 3) | ~90 | ❌ conceito novo — explicado na seção 3 |
| Modelos de dados (`models.py`) | ~60 | ❌ eram tuplas soltas do SQL |

**Ou seja:** a sua lógica não inchou 7x. Ela cresceu ~35%. O resto são
funcionalidades que **não existiam** — a maioria pedida pela auditoria que
você mesmo encomendou.

---

## 2. O fluxo é o mesmo. Sério.

### O que você escreveu

```
main.py            →  while True: bot.rn_service(); sleep(45~75s)
service.rn_service →  1. data = scraper.catch_data()
                      2. valida
                      3. SELECT último valor no banco
                      4. compara
                      5. se subiu: INSERT + send_message()
```

### O que a v2 faz

```
scheduler.py       →  while not desligando: service.run_once(); espera(45~75s)
service.run_once   →  1. observacao = fetcher.fetch()
                      2. valida
                      3. anterior = repo.last_snapshot()
                      4. decide(anterior, valor)   ← a comparação, isolada
                      5. repo.save_snapshot() + notifier.send()
```

**Cinco passos, na mesma ordem, com os mesmos nomes de conceito.** `scraper`
virou `fetcher`, `db` virou `repo`, `send_message` virou `notifier.send`. Se
você entendia a v1, você já entende 80% da v2.

As duas diferenças que valem a pena, e o porquê:

**(a) O passo 5 agora sempre grava.** Na sua versão, o `INSERT` estava *dentro*
do `if difference > 2`. Então quando entrava 1 produto, você não notificava
**e também não gravava** — e o banco ficava para trás. Na v2 grava sempre, e o
limiar decide só se manda mensagem. Foi essa a causa do atraso do cliente.

**(b) A comparação virou uma função separada chamada `decide`.** Ela recebe
"valor antigo" e "valor novo" e devolve o que aconteceu. Não toca em banco, não
toca em rede. Por isso dá para testá-la em 3 linhas — era impossível na v1,
porque a comparação estava grudada no SQL.

---

## 3. A única ideia nova que você precisa entender

Chama-se **injeção de dependência**. O nome é feio, a ideia é banal.

### Como você fez (e não tem nada de errado nisso)

```python
class ScrapingBot:
    def __init__(self):
        self.db = DataBaseManager()      # a classe CRIA o que ela usa
        self.scraper = ScraperClient()
```

O `ScrapingBot` fabrica seu próprio banco e seu próprio scraper.

### Como está agora

```python
class MonitorService:
    def __init__(self, *, fetcher, repository, notifier, clock):
        self.fetcher = fetcher           # a classe RECEBE o que ela usa
        self.repo = repository
        self.notifier = notifier
```

Ela não fabrica nada. Alguém entrega pronto.

### Por que isso importa (o motivo é 100% prático)

Com a v1, para testar "se subir 3 produtos, notifica" você precisaria de:
internet, o site alvo no ar, um banco de verdade e um webhook válido do Discord.
Na prática: **impossível de testar**, que é exatamente por que a v1 não tinha
teste nenhum.

Com a v2, o teste é literalmente isto:

```python
def test_subiu_tres_notifica_uma_vez_e_persiste():
    service, repo, notifier = build([100, 103])   # entrego um scraper FALSO
    service.run_once("r1")                        # que devolve 100, depois 103
    service.run_once("r2")

    assert len(notifier.public) == 1              # mandou 1 mensagem
    assert "3 PRODUTOS" in notifier.public[0].title
```

Sem internet, sem banco, sem Discord. Roda em milissegundos. É esse o único
motivo de o `MonitorService` receber as coisas em vez de criá-las.

### E quem cria as coisas de verdade, então?

Um arquivo só: **`__main__.py`**. Ele é o "montador". Lê a configuração, cria o
fetcher de verdade, o banco de verdade, o Discord de verdade, e entrega tudo
para o service:

```python
service = MonitorService(
    fetcher=_build_fetcher(settings),      # HttpFetcher de verdade
    repository=repo,                       # SqliteRepository de verdade
    notifier=notifier,                     # DiscordNotifier de verdade
    clock=SystemClock(),
)
```

**Se você quiser saber "quem é quem" na v2, abra `__main__.py`.** É o mapa.

---

## 4. E o que é esse tal de `protocol.py`?

Você vai ver três arquivos chamados `protocol.py`. Eles não fazem nada — são
**listas de assinaturas**, tipo um contrato:

```python
# storage/protocol.py
class Repository(Protocol):
    def last_snapshot(self) -> Snapshot | None: ...
    def save_snapshot(self, snapshot: Snapshot) -> Snapshot: ...
```

Isso diz: *"qualquer coisa que sirva de banco neste projeto tem que ter esses
métodos"*. O `SqliteRepository` (banco de verdade) tem. O `InMemoryRepository`
(o falso dos testes) também tem. Por isso os dois são intercambiáveis.

**É documentação que o computador confere.** Se você adicionar um método no
banco de verdade e esquecer do falso, o `mypy` avisa antes de rodar.

> Se isso ainda parecer abstrato demais: você pode ignorar os `protocol.py` por
> completo enquanto estiver só mexendo na lógica. Eles nunca executam nada.

---

## 5. Os 24 arquivos, em 4 bairros

Não decore. Só saiba em que bairro procurar.

### 🧠 O cérebro — a regra de negócio
| Arquivo | O que faz |
|---|---|
| **`service.py`** | ⭐ A sua `rn_service`. Coleta → compara → grava → notifica |
| **`scheduler.py`** | ⭐ O seu `main.py`. O `while True`, o sleep, o backoff |
| `models.py` | Os "formatos" dos dados (`Snapshot`, `Event`, `RunResult`) |
| `errors.py` | Os tipos de erro. Serve para distinguir "site fora do ar" de "site mudou o JSON" |

### 🌐 A coleta — o seu `scraper.py`
| Arquivo | O que faz |
|---|---|
| **`fetch/http.py`** | ⭐ Faz o GET e extrai o número do JSON |
| `fetch/profiles.py` | Os headers de navegador (stealth) |
| `fetch/protocol.py` | O contrato (não executa) |

### 💾 O banco — o seu `database.py`
| Arquivo | O que faz |
|---|---|
| **`storage/sqlite.py`** | ⭐ Todo o SQL do projeto está aqui e em nenhum outro lugar |
| `storage/migrations.py` | Cria/atualiza as tabelas |
| `storage/maintenance.py` | O seu `cleanup.py` + backup |
| `storage/protocol.py` | O contrato (não executa) |

### 📢 O aviso e o resto
| Arquivo | O que faz |
|---|---|
| **`notify/discord.py`** | ⭐ O seu `notifier.py` |
| `config.py` | Lê o `.env` e valida. **Todo ajuste de comportamento passa aqui** |
| `__main__.py` | Monta tudo + os comandos de terminal |
| `clock.py` | Relógio trocável (para os testes não esperarem 60s de verdade) |
| `lock.py` | Impede duas instâncias rodando juntas |
| `observability/*` | Log e contadores de saúde |

---

## 6. Roteiro de leitura — 30 minutos, 4 arquivos

Faça nesta ordem. **Não leia o resto ainda.**

1. **`service.py`, só a função `decide`** (~45 linhas). É a sua regra de
   comparação, isolada. Se entendeu ela, entendeu o coração.
2. **`service.py`, a função `run_once`** (~80 linhas). É a sua `rn_service`.
   Compare lado a lado com a antiga em `git show 71ab8f1:src/service.py`.
3. **`tests/test_service.py`** (~170 linhas). **Leia isto como se fosse
   documentação.** Cada teste é uma frase: "quando X acontece, o bot faz Y".
   É a explicação mais rápida do comportamento inteiro do sistema.
4. **`__main__.py`, só a seção `# montagem`** (~60 linhas). É onde as peças
   reais são criadas e conectadas.

Comando útil para comparar com o seu código antigo a qualquer momento:

```bash
git show 71ab8f1:src/service.py     # a sua versão
git show 71ab8f1:src/scraper.py
git show 71ab8f1:main.py
```

O código que você escreveu não sumiu — está inteiro no histórico.

---

## 7. Receitas — como mexer nas coisas prováveis

### "Quero mudar de quantos em quantos produtos ele avisa"
`.env` → `ALERT_THRESHOLD=3`. Não mexe em código, não reconstrói imagem.

### "Quero mudar o intervalo entre as consultas"
`.env` → `INTERVAL_MIN_S` / `INTERVAL_MAX_S`.

### "Quero mudar o texto da mensagem do Discord"
`service.py`, função `_render`, bloco `if event.kind is EventKind.INCREASE`.
É só um texto — mexa à vontade.

### "O site mudou e o número está em outro lugar do JSON"
`fetch/http.py`, primeira linha de código do arquivo:
```python
_AMOUNT_PATH = ("data", "productSearch", "recordsFiltered")
```
Troque pelo caminho novo. Só isso.

### "Quero guardar mais um dado no banco"
Três passos, nesta ordem:
1. `storage/migrations.py` → adicione uma função `_v4_alguma_coisa` e coloque na
   lista `MIGRATIONS`;
2. `models.py` → adicione o campo no dataclass;
3. `storage/sqlite.py` → inclua no `INSERT` e no `SELECT`.

### "Quero saber se está funcionando agora"
```bash
python -m scrapingbot once --dry-run   # 1 ciclo, não manda nada pro Discord
python -m scrapingbot stats            # o que ele coletou
python -m scrapingbot doctor -n 5      # o site está entregando dado novo?
```

### "Mexi em algo, será que quebrei?"
```bash
pytest
```
1 segundo. Se ficar verde, você não quebrou nada do que estava coberto.
**Esse é o valor real dos testes**: liberdade para mexer sem medo.

---

## 8. O que você pode ignorar sem culpa

Sinceramente, não precisa entender agora — e talvez nunca:

- `clock.py` — só existe para os testes não esperarem tempo real
- `lock.py` — trava de arquivo, mexe com `fcntl`/`msvcrt` do sistema operacional
- `observability/logging.py` — configuração de log
- os três `protocol.py` — não executam nada
- `storage/maintenance.py` — roda sozinho uma vez por dia
- `fetch/profiles.py` — é 90% tabela de headers copiada de navegador

Isso é ~700 das 2.233 linhas. **Um terço do projeto você pode tratar como
"encanamento que já funciona"** e só olhar quando der problema.

---

## 9. Glossário dos termos estranhos

| Termo | Em português claro |
|---|---|
| **Protocol** | Lista de métodos que uma classe precisa ter. Um contrato |
| **Injeção de dependência** | Receber as coisas prontas em vez de criá-las |
| **dataclass** | Classe que só guarda dados. Evita escrever `__init__` na mão |
| **frozen=True** | Depois de criado, não muda mais. Evita bug bobo |
| **Outbox** | Grava o alerta como "pendente" e só marca "enviado" quando o Discord confirma. Assim nenhum alerta se perde |
| **Migração** | Script que atualiza a estrutura das tabelas sem perder dados |
| **Fake / stub** | Versão de mentira usada só no teste (ex.: um scraper que devolve `[100, 103]` em vez de acessar a internet) |
| **Fixture** | Dado de exemplo pronto para o teste usar |
| **Backoff** | Esperar cada vez mais depois de cada falha, em vez de insistir no mesmo ritmo |
| **Composition root** | O único lugar que monta tudo. Aqui é o `__main__.py` |

---

## 10. Uma coisa importante

A v1 não era ruim. Ela **funcionou em produção por meses**, com estrutura em
camadas, retry com backoff, context manager, WAL ligado e usuário não-root no
container. Isso não é código de iniciante.

O que a auditoria encontrou não foram erros de quem não sabe programar — foram
os problemas que **só aparecem quando um sistema roda sozinho por muito tempo**:
o alerta que some em silêncio, o banco que não registra que o bot está vivo, a
retenção que nunca executa. São aprendizados de operação, não de sintaxe.

E o bug que causou a queixa do cliente — o `INSERT` dentro do `if` — é o tipo de
coisa que passa por qualquer revisão até o dia em que um teste de 3 linhas o
pega. Agora existe esse teste.

Se algo aqui ainda não fizer sentido, o caminho mais rápido é abrir o arquivo,
olhar o comentário no topo (todos têm) e comparar com o equivalente antigo via
`git show 71ab8f1:<arquivo>`.
