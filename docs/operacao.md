# Operação

Como colocar no ar, o que fazer quando algo quebra, e como migrar da v1.

---

## 1. Migração da v1 — faça nesta ordem

A v1 e a v2 **não podem rodar ao mesmo tempo**: as duas escreveriam no mesmo
canal do Discord e você receberia alertas duplicados.

```bash
# 1. Parar a v1 (no servidor)
docker stop <container-antigo>        # ou pkill -f main.py, se estava em cron
crontab -l                            # confira se há entradas de main.py/cleanup.py
# comente as linhas de cron antes de seguir

# 2. Atualizar o .env
#    Os nomes novos são DISCORD_ALERT_WEBHOOK e DISCORD_LOG_WEBHOOK.
#    Os antigos (SCRAPINGBOT / LOGGINGSBOT) continuam funcionando por
#    compatibilidade, mas renomeie: o alias vai sair numa versão futura.
cp .env.example .env.novo
#    ... copie os valores do .env antigo para o novo e revise as opcionais

# 3. Subir e conferir a configuração ANTES de coletar qualquer coisa
docker compose build
docker compose run --rm scrapingbot config

# 4. Diagnóstico contra o alvo real (não escreve nada, não notifica)
docker compose run --rm scrapingbot doctor -n 8

# 5. Um ciclo de teste sem tocar no Discord
docker compose run --rm scrapingbot once --dry-run

# 6. No ar
docker compose up -d
docker compose logs -f
```

### Importando o histórico antigo

O `BUG-5` deixou **dois** bancos no repositório, e o que tem histórico de
verdade não é o que o Docker usava:

| Arquivo | Linhas | O que é |
|---|---|---|
| `DataBase.db` (raiz) | 36 | O histórico real — criado quando o bot rodava fora do container |
| `data/DataBase.db` | 2 | O que o container criou, praticamente vazio |

Nenhum dos dois foi apagado por esta reescrita. Para trazer o histórico:

```bash
python -m scrapingbot import-legacy DataBase.db
```

> A v1 gravava apenas `YYYY-MM-DD`, sem hora. As linhas importadas ficam com
> `12:00 UTC` — um marcador honesto de "hora desconhecida", em vez de fingir
> precisão que o dado não tem.

Depois de confirmar (`python -m scrapingbot stats -d 365`), os dois arquivos
antigos podem ser arquivados fora do repositório.

---

## 2. Comandos do dia a dia

```bash
python -m scrapingbot run                    # laço principal (padrão)
python -m scrapingbot once --dry-run         # um ciclo, sem notificar
python -m scrapingbot doctor -n 8            # é o bot, o cache ou bloqueio?
python -m scrapingbot stats -d 30            # relatório dos últimos 30 dias
python -m scrapingbot maintenance            # retenção + backup sob demanda
python -m scrapingbot healthcheck            # exit 0 se coletou há < 10 min
python -m scrapingbot config                 # config efetiva, sem segredos
```

Dentro do compose, prefixe com `docker compose exec scrapingbot`.

---

## 3. Diagnóstico — "a notificação está atrasando"

Esta é a queixa que originou a reescrita. Há três causas possíveis e o
`doctor` distingue as três:

```bash
docker compose exec scrapingbot python -m scrapingbot doctor -n 8
```

| O que o doctor mostra | Causa | O que fazer |
|---|---|---|
| Hash **muda** entre coletas, latência normal | O alvo entrega dado fresco. O atraso era da **regra de negócio** (`if difference > 2`) | Já corrigido. Confirme com `stats` que os eventos de delta 1 e 2 agora aparecem |
| Hash **congelado** + `Age` crescendo | Você lê **cache de borda** do CDN | Confira no DevTools qual parâmetro anti-cache o front-end usa e ajuste `CACHE_BUSTER_PARAM`; em último caso, `NO_CACHE_HEADERS=1` |
| Hash congelado, **sem** headers de cache | Ou o catálogo está mesmo parado, ou servem uma resposta fixa para você | Abra a página no navegador e compare com o valor que o bot recebe |
| `403` / `429` | Você foi barrado | `pip install "scrapingbot[stealth]"` + `FETCH_BACKEND=auto` — ver [`stealth.md §3`](stealth.md) |

O bot também avisa sozinho no canal de log:

- **"Bot sem coletar"** — 5 ciclos consecutivos falharam (dispara uma vez e cala
  até recuperar, para não silenciarem o canal);
- **"Resposta do alvo congelada"** — 30 respostas byte a byte idênticas;
- **"Formato da resposta mudou"** — o campo esperado sumiu do JSON. **Este é o
  mais grave**: significa que o bot está cego.

---

## 4. Monitoramento externo (dead-man's switch)

O heartbeat do Discord é enviado **pelo próprio bot**. Se o processo cair, o
container for morto pelo OOM killer ou o host reiniciar, o sinal não é um
alerta — é **silêncio**, que é exatamente o que ninguém percebe.

Inverta a lógica:

1. Crie um check em [healthchecks.io](https://healthchecks.io) (grátis) com
   período de 5 min e grace de 15 min.
2. `DEADMAN_URL=https://hc-ping.com/<uuid>` no `.env`.
3. O bot pinga a cada coleta **bem-sucedida** — não a cada ciclo. Um bot que
   roda mas não coleta nada não deve parecer saudável.

Três linhas de código, e é o item de maior retorno da auditoria inteira.

---

## 5. Backup e retenção

Automático, uma vez por dia, dentro do próprio laço (`BUG-12`):

- `VACUUM INTO data/backups/scrapingbot-AAAA-MM-DD.db` — atômico, consistente,
  sem parar o bot. Mantém `BACKUP_KEEP` cópias (padrão 7).
- `runs` com mais de `RETENTION_DAYS` (30) são **agregados** em `run_hourly`
  antes de serem apagados — o detalhe some, a série histórica fica.
- `events` já entregues ficam `EVENTS_RETENTION_DAYS` (730). **Eventos
  pendentes nunca são apagados**: são a fila de entrega.
- `PRAGMA incremental_vacuum` na limpeza; `VACUUM` completo no máximo uma vez
  por mês.

**Os backups vivem no mesmo volume do banco.** Para proteção real contra perda
do host, copie para fora periodicamente:

```bash
docker compose cp scrapingbot:/app/data/backups ./backups-locais
```

---

## 6. Rotação de credenciais — `SEC-1`

A URL do webhook **é** a credencial: quem a tiver posta no seu canal como o
bot, para sempre, sem autenticação adicional.

**Rotação (faça a cada ~6 meses, ou imediatamente após qualquer suspeita):**

1. Discord → Editar Canal → Integrações → Webhooks → **Criar novo**.
2. Atualize o `.env` com a URL nova.
3. `docker compose up -d` (recria o container com o novo env).
4. Confirme que chegou mensagem no canal.
5. **Só então** apague o webhook antigo no Discord.

> ⚠️ **O `.env` está numa pasta do OneDrive.** Isso significa que a credencial
> está sincronizada para a nuvem e para toda máquina logada na mesma conta. Em
> produção, o `.env` deve ficar **fora de pasta sincronizada** — e o ideal é
> Docker secrets ou o gerenciador de segredos do provedor.

**Se um webhook vazar:** apague-o no Discord *primeiro* (isso o invalida na
hora), depois crie o novo. Não há como "revogar parcialmente".

---

## 7. Instância única — `BUG-14`

O bot adquire um lock exclusivo (`LOCK_PATH`) no boot. Uma segunda instância
encerra imediatamente com mensagem clara, em vez de duplicar alertas e disputar
o SQLite.

Se o bot recusar subir dizendo "já existe outra instância" e você tiver certeza
de que não há:

```bash
docker compose ps               # confirme que nada está rodando
docker compose exec scrapingbot rm /app/data/scrapingbot.lock
```

---

## 8. Checklist antes de publicar o repositório

- [ ] `.env` **não** está versionado (confirme com `git ls-files | grep env`)
- [ ] Webhooks rotacionados depois de qualquer compartilhamento de tela
- [ ] `docs/stealth.md §6` (legitimidade) preenchido com `robots.txt` e ToS
- [ ] `DEADMAN_URL` configurado
- [ ] Base do Docker fixada por digest (`REL-4` — ver comentário no Dockerfile)
