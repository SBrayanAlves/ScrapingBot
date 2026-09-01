# Stealth — o que foi feito, o que falta, e por quê

> **Premissa:** este bot consulta um endpoint **público** de uma loja online,
> o mesmo que o navegador de qualquer visitante chama ao abrir a categoria, a
> ~60 requisições por hora. O objetivo aqui não é burlar autenticação nem
> contornar proteção paga — é **não parecer anômalo**, o que é uma exigência
> técnica de qualquer cliente HTTP bem-comportado. Ver [`SEC-4`](#legitimidade).

---

## 1. O erro conceitual da v1

A v1 tinha uma seção "Estratégia Anti-Detecção" no README, com quatro itens.
Três deles **aumentavam** a chance de detecção.

| O que a v1 fazia | Por que era pior que não fazer nada |
|---|---|
| Sorteava um User-Agent novo **a cada requisição** | A `Session` era a mesma: mesmos cookies, mesmo IP. Do lado do servidor: uma sessão única que troca de navegador **e de sistema operacional** a cada 60 segundos, para sempre. Nenhum usuário real faz isso — **o padrão foi criado pela tentativa de escondê-lo** |
| `fake_useragent` devolvendo qualquer navegador | Chrome, Safari, Firefox, versões antigas, mobile — combinações improváveis, e sem nenhum dos `Sec-CH-UA` que todo Chrome moderno envia. O UA dizia "Chrome 120"; os headers diziam "não sou Chrome" |
| `Content-Type: application/json` em um **GET** | GET não tem corpo. Navegador nenhum envia isso. É um header que só aparece em cliente programático |
| `Cache-Control: no-cache` + `Pragma: no-cache` em toda requisição | Um navegador só manda isso em *reload forçado* (Ctrl+F5). Em toda requisição, é assinatura de automação |
| Delay uniforme de 45–75s, 24 horas por dia, todo dia | Um humano não navega em intervalo uniforme por 24h. Mas veja a seção 4: isto é o **menos** importante da lista |

A regra que organiza tudo isso: **incoerência é mais detectável que
uniformidade.** Um cliente que sempre se apresenta como o mesmo Chrome, com
headers todos consistentes, chama menos atenção que um que muda de identidade
sem nunca ficar coerente.

---

## 2. O que foi implementado

### 2.1 Identidade como pacote fechado — `fetch/profiles.py`

Cinco perfis completos e coerentes. Cada um define, em conjunto:
User-Agent · `sec-ch-ua` · `sec-ch-ua-platform` · `sec-ch-ua-mobile` ·
`Accept-Language` · `Priority`.

- **Um perfil por sessão**, fixo do começo ao fim.
- Para rotacionar, a sessão **inteira** é recriada: cookies novos, perfil novo,
  aquecimento novo. Identidade nova de ponta a ponta, ou nenhuma mudança.
- O perfil Firefox **não** envia client hints — porque Firefox real não envia.
  Mandar `Sec-CH-UA` junto com UA de Firefox seria a mesma incoerência de antes,
  só que mais sofisticada.

Configurável por `SESSION_MAX_CYCLES` (padrão 40 ciclos ≈ 40 minutos).

### 2.2 Headers na ordem certa

A **ordem** dos headers faz parte do fingerprint HTTP — bibliotecas diferentes
emitem ordens diferentes. `requests` preserva a ordem de inserção do dict, então
construir na ordem do Chrome sai de graça. Também foram removidos os headers
que denunciavam automação (`Content-Type` em GET, `no-cache` por padrão).

### 2.3 Aquecimento coerente — `SCR-8`

A v1 fazia um `GET` na página antes da API — **com headers de XHR**, o que é uma
combinação que não existe. Agora o aquecimento usa headers de navegação de
verdade (`Sec-Fetch-Dest: document`, `Accept: text/html…`,
`Upgrade-Insecure-Requests`), seguido de uma pausa curta antes do XHR — que é o
tempo que um navegador leva para renderizar e disparar o `fetch`.

Isso também é o que colhe os cookies de sessão/anti-bot que a API espera.

### 2.4 Cadência que reage — `BUG-17`

O ponto mais importante desta lista para *não ser bloqueado*: a v1 batia
45–75 vezes por hora **incondicionalmente**. Se o alvo passasse a responder 403,
ela continuaria batendo, para sempre, contra quem já a tinha rejeitado — o jeito
mais rápido de transformar um bloqueio temporário em permanente.

Agora: backoff exponencial (60s → 120s → 240s… até 30 min) contado por falhas
consecutivas, com jitter de ±20%, zerado no primeiro sucesso. E `Retry-After` é
respeitado quando o alvo o envia.

### 2.5 Janela de operação no código — `ARQ-8`

`ACTIVE_DAYS` / `ACTIVE_HOUR_START` / `ACTIVE_HOUR_END`. O README prometia
terça, quinta e domingo das 8h às 19h; o código rodava 24/7 a quase 3× a
frequência documentada. Agora a janela é obedecida pelo processo — o container
nunca viu o cron do host.

### 2.6 Instrumentação para *medir* detecção — novo

Não estava na auditoria e é o que responde à sua pergunta. Toda coleta registra:

- `payload_hash` — SHA-256 dos 16 primeiros bytes hex do corpo bruto;
- `cache_age` — header `Age`: segundos que a resposta passou no CDN;
- `cache_status` — `x-cache` / `cf-cache-status` / `x-vtex-cache`;
- `latency_ms` — sobe bem antes de um alvo começar a recusar tráfego;
- `http_status`.

E o `HealthTracker` dispara um alerta quando N respostas **byte a byte
idênticas** chegam seguidas (`STALE_ALERT_THRESHOLD`, padrão 30). Isso não prova
bloqueio — mas é o único sinal observável de que parou de chegar dado fresco.

---

## 3. O maior vetor de detecção, que a auditoria não citou

**Headers são a camada mais visível e a menos decisiva.**

Um WAF moderno (Cloudflare, Akamai, DataDome, PerimeterX) casa três coisas:

| Camada | O que o Chrome faz | O que `requests` faz |
|---|---|---|
| **TLS (JA3/JA4)** | Ordem própria de cipher suites, extensões GREASE, ALPN `h2,http/1.1` | Ordem do OpenSSL, sem GREASE — uma assinatura que grita "Python" |
| **HTTP/2** | Fala h2, com tabela de `SETTINGS` e ordem de pseudo-headers próprias | Fala **HTTP/1.1**. Um "Chrome 133" que não fala h2 em 2026 não existe |
| **Headers** | Coerentes com os dois acima | Agora coerentes — mas só nesta camada |

Ou seja: por mais perfeito que fique o `User-Agent`, o handshake entrega. É
**gratuito** para o servidor conferir e praticamente impossível de falsificar
com `requests`.

### A solução: backend `curl_cffi`

```bash
pip install "scrapingbot[stealth]"
# .env
FETCH_BACKEND=auto        # usa curl_cffi quando disponível
```

`curl_cffi` usa um libcurl compilado com o perfil TLS do Chrome
(`impersonate="chrome"`), o que alinha JA3/JA4 **e** HTTP/2 com o UA anunciado.
O `HttpFetcher` já tem o backend implementado atrás da mesma interface: com o
pacote instalado, `auto` o escolhe; sem ele, cai para `requests` e **avisa no
log** que o fingerprint é o do Python.

> Não coloquei `curl_cffi` como dependência obrigatória porque ele traz binário
> próprio e nem toda plataforma tem wheel. A escolha fica sua — mas se houver
> suspeita real de bloqueio, é aqui que está o ganho.

---

## 4. Ordem de importância (se você só puder fazer três coisas)

1. **Corrigir o `> 2`** — já feito. É a causa mais provável da queixa do
   cliente, e não tem nada a ver com detecção.
2. **`curl_cffi`** — se houver 403/429 de verdade, é o que resolve.
3. **Backoff ao falhar** — já feito. É o que impede um bloqueio temporário de
   virar permanente.

O que **não** vale a pena agora:

- **Proxies rotativos.** Trocar de IP mantendo fingerprint inconsistente não
  esconde nada — só multiplica o custo. Só faz sentido *depois* do curl_cffi, e
  só se a taxa justificar. (`PRD-5`)
- **Selenium/Playwright.** Ordens de magnitude mais caro em CPU e RAM para
  1 req/min, e um navegador headless tem o próprio conjunto de tells. Se o
  endpoint JSON responde, usar navegador é regressão.
- **Randomizar mais os headers.** Mais aleatoriedade = mais incoerência. O
  caminho é o oposto.

---

## 5. Como validar contra o alvo real

O gabarito não está neste arquivo — está no DevTools do site:

1. Abra a página do alvo no Chrome, aba **Network**, filtro **Fetch/XHR**.
2. Ache a requisição que o front-end faz para o mesmo endpoint.
3. Botão direito → **Copy → Copy as cURL**.
4. Compare **header por header** com o que `fetch/profiles.py` monta.
   Diferenças são a sua lista de tarefas.
5. Confira também qual parâmetro anti-cache o front usa (se usar) e ajuste
   `CACHE_BUSTER_PARAM` — o `_=timestamp` é uma convenção do jQuery, e pode não
   ser o que este site espera.

Depois:

```bash
python -m scrapingbot doctor -n 8
```

Ele faz 8 coletas seguidas e diz, com base no hash e nos headers de cache, se o
alvo está entregando dado fresco, se você está lendo cache de borda, ou se está
sendo recusado.

---

## 6. Legitimidade da coleta {#legitimidade}

`SEC-4` — para um projeto de scraping, esta é a primeira pergunta que um
entrevistador (ou um advogado) faz. **Preencha antes de publicar o repositório:**

- [ ] **Endpoint consultado:** API pública de busca de catálogo, a mesma que o
      front-end do site chama ao carregar a página de categoria. Sem
      autenticação, sem contornar paywall, sem acessar dado privado.
- [ ] **Taxa:** ~60 requisições/hora (1/min), com backoff ao primeiro sinal de
      recusa. Para comparação, um único visitante navegando pela categoria
      dispara facilmente dezenas de chamadas ao mesmo endpoint em minutos.
- [ ] **`robots.txt`:** *verificar e anotar aqui a data e o conteúdo relevante.*
- [ ] **Termos de uso do alvo:** *verificar e anotar aqui.*
- [ ] **Dado coletado:** apenas uma **contagem agregada** (`recordsFiltered`).
      Nenhum dado pessoal, nenhum conteúdo, nada revendido ou republicado.
- [ ] **Uso:** notificação privada em um canal do Discord do próprio cliente.

Ter pensado nisso — e ter escrito — é o que separa "projeto de scraping" de
"projeto de scraping responsável". A resposta pode até ser "o robots.txt permite
e o volume é irrelevante"; o que não pode é a resposta ser "não pensei nisso".
