# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).
Versionamento: [SemVer](https://semver.org/lang/pt-BR/).

## [2.0.0] - 2026-08-31

Reescrita completa a partir da auditoria de 79 pontos (`docs/MELHORIAS.md`).

### Corrigido -- o que causava o atraso na notificacao

- **Aumentos de 1 ou 2 itens nao eram notificados nem persistidos.** O
  `if difference > 2` guardava a notificacao *e* o `INSERT`, entao o banco
  ficava defasado e o alerta so saia apos acumular 3. Persistir e notificar
  agora sao decisoes independentes, e o limiar e configuravel. (BUG-8)
- **Alertas sumiam em silencio** quando o Discord falhava: o banco ja tinha
  sido atualizado, entao aquele lote nunca mais seria notificado. Agora ha
  outbox: o evento so sai da fila quando a entrega e confirmada. (BUG-13, BUG-18)
- `requirements.txt` estava em UTF-16 -- a imagem nao subia numa maquina
  limpa. (BUG-1)
- Removido o pacote `logging==0.4.9.6` do PyPI, que nao e a stdlib. (BUG-2)
- `cleanup.py` executava `DELETE` + `VACUUM` ao ser importado. (BUG-3)
- `send_message` sem timeout podia congelar o laco para sempre. (BUG-4)
- Caminho do banco dependia do `cwd`, criando bancos orfaos. (BUG-5)
- `Accept-Encoding` anunciava `br`/`zstd` sem as bibliotecas instaladas. (BUG-6)
- `datetime.now()` sem fuso gravava a data do dia seguinte a noite. (BUG-7)
- Log era apagado a cada reinicio, sem rotacao. (BUG-9)
- Transacao sem `rollback` explicito. (BUG-10)
- A rotina de limpeza era codigo morto no deploy Docker. (BUG-12)
- Nada impedia duas instancias simultaneas. (BUG-14)
- Sem sanity check, um valor absurdo viraria `@everyone`. (BUG-15)
- Falha do alvo nao mudava a cadencia: o bot insistia ate ser bloqueado. (BUG-17)

### Adicionado

- Pacote instalavel `scrapingbot` com CLI: `run`, `once`, `doctor`, `stats`,
  `maintenance`, `healthcheck`, `import-legacy`, `config`. (ENG-7)
- `doctor`: diagnostica se o atraso vem do bot, do cache do alvo ou de
  bloqueio, comparando hash do payload e headers `Age`/`x-cache`. (novo)
- 111 testes com fakes de Fetcher/Repository/Notifier/Clock. (ENG-1, ENG-8)
- CI com ruff, mypy, pytest, build da imagem, pip-audit e trivy. (ENG-3, SEC-3)
- Tabelas `runs`, `events`, `snapshots` e `run_hourly`; migracoes versionadas
  por `PRAGMA user_version`. (DAT-1..DAT-5, ENG-5)
- Backup `VACUUM INTO` com rotacao. (DAT-6)
- Dead-man's switch, `docker-compose.yml`, `HEALTHCHECK`, limites de recurso,
  desligamento gracioso. (REL-1..REL-6, ARQ-6, INF-6)
- Redacao de segredos no log. (SEC-2)
- Deteccao de resposta congelada do alvo. (novo)
- Backend opcional `curl_cffi` para fingerprint TLS/HTTP2 de Chrome. (novo)

### Alterado

- Arquitetura em portas e adaptadores: o nucleo nao importa infraestrutura.
  (ARQ-1, ARQ-2)
- Configuracao unica validada no boot; nenhum numero magico no codigo.
  (INF-5, ARQ-3, ENG-9)
- Perfis de navegador coerentes, um por sessao, trocados junto com os cookies.
  (SCR-1, SCR-2, SCR-3)
- `@everyone` substituido por mencao opt-in. (SCR-5)
- Notificacoes viraram embeds com valor anterior, novo e link. (PRD-2)

### Removido

- `main.py`, `cleanup.py` e `src/*.py` da v1 (preservados no historico do git).
- Dependencias `logging`, `pytz`, `six`, `fake-useragent`.
