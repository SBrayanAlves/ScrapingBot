"""Composition root: monta tudo, injeta e sai do caminho.  ENG-7

Este e o unico arquivo que conhece todas as pecas ao mesmo tempo. Nenhum outro
modulo instancia nada de infraestrutura -- e o que torna os testes possiveis.

    python -m scrapingbot run          # laco principal
    python -m scrapingbot once         # um ciclo, sem laco
    python -m scrapingbot doctor       # diagnostico: e o bot ou e o alvo?
    python -m scrapingbot stats        # relatorio do que foi coletado
    python -m scrapingbot maintenance  # limpeza/backup sob demanda
    python -m scrapingbot healthcheck  # usado pelo HEALTHCHECK do container
    python -m scrapingbot import-legacy DataBase.db
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .clock import SystemClock
from .config import Settings, load_settings
from .errors import AlreadyRunningError, ConfigError, ScrapingBotError
from .fetch.http import HttpFetcher
from .lock import InstanceLock
from .models import FetchResult
from .notify.discord import DiscordNotifier, NullNotifier
from .notify.protocol import Notifier
from .observability.heartbeat import HealthTracker
from .observability.logging import new_run_id, setup_logging
from .scheduler import Scheduler
from .service import MonitorService, Thresholds
from .storage.maintenance import Maintenance
from .storage.sqlite import SqliteRepository

log = logging.getLogger("scrapingbot")


# ------------------------------------------------------------------ montagem
def _build_notifier(settings: Settings, *, dry_run: bool) -> Notifier:
    if dry_run:
        return NullNotifier()
    return DiscordNotifier(
        alert_webhook=settings.alert_webhook,
        log_webhook=settings.log_webhook,
        clock=SystemClock(),
        mention=settings.alert_mention,
        timeout_s=settings.notify_timeout_s,
        retries=settings.notify_retries,
    )


def _build_fetcher(settings: Settings) -> HttpFetcher:
    return HttpFetcher(
        target_url=settings.target_url,
        page_url=settings.page_url,
        referer=settings.referer,
        clock=SystemClock(),
        timeout_s=settings.http_timeout_s,
        retries=settings.http_retries,
        backoff_factor=settings.http_backoff_factor,
        warmup=settings.warmup_enabled,
        session_max_cycles=settings.session_max_cycles,
        prefetch_delay=(settings.prefetch_delay_min_s, settings.prefetch_delay_max_s),
        backend=settings.fetch_backend,
        cache_buster_param=settings.cache_buster_param,
        no_cache_headers=settings.no_cache_headers,
    )


def _build_repo(settings: Settings) -> SqliteRepository:
    repo = SqliteRepository(settings.db_path)
    repo.setup()
    return repo


def _build_service(
    settings: Settings, repo: SqliteRepository, notifier: Notifier, fetcher: HttpFetcher
) -> MonitorService:
    return MonitorService(
        fetcher=fetcher,
        repository=repo,
        notifier=notifier,
        clock=SystemClock(),
        thresholds=Thresholds(
            alert_delta=settings.alert_threshold,
            max_plausible_delta=settings.max_plausible_delta,
            max_plausible_amount=settings.max_plausible_amount,
        ),
        page_url=settings.page_url,
    )


# ------------------------------------------------------------------ comandos
def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    repo = _build_repo(settings)
    fetcher = _build_fetcher(settings)
    notifier = _build_notifier(settings, dry_run=args.dry_run)
    service = _build_service(settings, repo, notifier, fetcher)

    scheduler = Scheduler(
        service=service,
        settings=settings,
        clock=SystemClock(),
        notifier=notifier,
        maintenance=Maintenance(
            repo,
            retention_days=settings.retention_days,
            events_retention_days=settings.events_retention_days,
            backup_dir=settings.backup_dir,
            backup_keep=settings.backup_keep,
        ),
        health=HealthTracker(
            heartbeat_every=settings.heartbeat_every,
            failure_alert_threshold=settings.failure_alert_threshold,
            stale_alert_threshold=settings.stale_alert_threshold,
        ),
    )
    scheduler.install_signal_handlers()

    lock = InstanceLock(settings.lock_path)
    try:
        lock.acquire()
    except AlreadyRunningError as exc:
        log.error("%s", exc)
        return 2

    try:
        scheduler.run_forever(max_cycles=args.max_cycles)
    finally:
        lock.release()
        fetcher.close()
    return 0


def cmd_once(settings: Settings, args: argparse.Namespace) -> int:
    repo = _build_repo(settings)
    fetcher = _build_fetcher(settings)
    notifier = _build_notifier(settings, dry_run=args.dry_run)
    service = _build_service(settings, repo, notifier, fetcher)
    try:
        result = service.run_once(new_run_id())
    finally:
        fetcher.close()

    print(
        f"status={result.status.value} valor={result.observed_amount} "
        f"duracao={result.duration_ms}ms cache_age={result.cache_age} "
        f"eventos={len(result.events)}"
    )
    if result.error:
        print(f"erro: {result.error}")
    return 0 if result.ok else 1


def cmd_doctor(settings: Settings, args: argparse.Namespace) -> int:
    """Responde a pergunta que originou esta reescrita.

    "A notificacao esta atrasando -- e a URL velha, o site nos descobriu, ou e
    bug do bot?" O doctor faz N coletas seguidas e mostra, lado a lado, o que
    mudou: o valor, o hash do corpo e os headers de cache do alvo.

      * hash muda a cada coleta -> o alvo esta entregando dado fresco;
        se mesmo assim o alerta atrasa, o problema e (era) a regra de negocio
      * hash congelado + `Age` crescendo -> voce esta lendo cache de borda
      * 403/429 -> voce foi barrado, e ai stealth importa
    """
    fetcher = _build_fetcher(settings)
    samples: list[FetchResult | None] = []
    print(f"backend={fetcher.backend}  perfil inicial=(sera sorteado)  alvo=<oculto>")
    try:
        for index in range(1, args.samples + 1):
            try:
                observation = fetcher.fetch()
            except ScrapingBotError as exc:
                print(f"[{index}] FALHA {type(exc).__name__}: {exc}")
                samples.append(None)
                continue
            samples.append(observation)
            print(
                f"[{index}] valor={observation.amount:<8} hash={observation.payload_hash} "
                f"latencia={observation.latency_ms:>5}ms  http={observation.http_status} "
                f"Age={observation.cache_age}  cache={observation.cache_status}  "
                f"perfil={observation.profile}"
            )
    finally:
        fetcher.close()

    ok = [s for s in samples if s is not None]
    print("\n--- diagnostico ---")
    if not ok:
        print("Nenhuma coleta funcionou. Veja os erros acima: se for 403/429, o alvo")
        print("esta recusando; se for timeout, e rede. Nao e bug de regra de negocio.")
        return 1

    hashes = {s.payload_hash for s in ok}
    ages = [s.cache_age for s in ok if s.cache_age is not None]
    if len(hashes) == 1 and len(ok) > 1:
        print(f"Corpo IDENTICO nas {len(ok)} coletas (hash {hashes.pop()}).")
        if ages and max(ages) > min(ages):
            print(f"E o header Age subiu de {min(ages)}s para {max(ages)}s: voce esta")
            print("lendo uma resposta em cache. O atraso e da borda do alvo, nao do bot.")
            print("Acao: confira no DevTools qual parametro o front-end usa para furar")
            print("o cache e ajuste CACHE_BUSTER_PARAM; se nao houver, NO_CACHE_HEADERS=1.")
        else:
            print("Sem sinal de cache nos headers. Pode ser que o catalogo esteja")
            print("realmente parado -- compare com a pagina aberta no navegador.")
    else:
        print(f"Corpo mudou entre coletas ({len(hashes)} hashes distintos): o alvo esta")
        print("entregando dado fresco. Se o alerta atrasa mesmo assim, o gargalo era a")
        print("regra de negocio (o antigo `if difference > 2`), ja corrigida.")
    if ages:
        print(f"Age observado: min={min(ages)}s max={max(ages)}s")
    return 0


def cmd_stats(settings: Settings, args: argparse.Namespace) -> int:
    """Relatorio.  PRD-3 -- ate agora nada no sistema LIA o banco."""
    repo = SqliteRepository(settings.db_path)
    since = (datetime.now(UTC) - timedelta(days=args.days)).isoformat()

    with repo.connection() as conn:
        totals = conn.execute(
            "SELECT COUNT(*) AS runs, "
            "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok, "
            "AVG(duration_ms) AS avg_ms, MAX(duration_ms) AS max_ms "
            "FROM runs WHERE started_at >= ?",
            (since,),
        ).fetchone()
        by_status = conn.execute(
            "SELECT status, COUNT(*) AS n FROM runs WHERE started_at >= ? "
            "GROUP BY status ORDER BY n DESC",
            (since,),
        ).fetchall()
        events = conn.execute(
            "SELECT kind, COUNT(*) AS n, SUM(delta) AS total FROM events "
            "WHERE observed_at >= ? GROUP BY kind",
            (since,),
        ).fetchall()
        pending = conn.execute("SELECT COUNT(*) AS n FROM events WHERE notified = 0").fetchone()
        # A informacao de maior valor do sistema, que a v1 jogava fora ao gravar
        # so a data: A QUE HORAS o alvo publica.  DAT-2
        by_hour = conn.execute(
            "SELECT substr(observed_at, 12, 2) AS hora, COUNT(*) AS n, SUM(delta) AS itens "
            "FROM events WHERE kind = 'increase' AND observed_at >= ? "
            "GROUP BY hora ORDER BY itens DESC LIMIT 8",
            (since,),
        ).fetchall()
        last_amount = conn.execute(
            "SELECT amount, observed_at FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()

    runs = totals["runs"] or 0
    print(f"=== ScrapingBot -- ultimos {args.days} dia(s) ===\n")
    if runs == 0:
        print("Nenhum ciclo registrado no periodo.")
        return 0

    rate = (totals["ok"] or 0) / runs
    print(f"Ciclos           : {runs}")
    print(f"Taxa de sucesso  : {rate:.1%}")
    print(f"Duracao media    : {totals['avg_ms']:.0f} ms (pico {totals['max_ms']} ms)")
    if last_amount:
        observed = datetime.fromisoformat(last_amount["observed_at"])
        print(
            f"Ultimo valor     : {last_amount['amount']} "
            f"(em {settings.local(observed):%d/%m %H:%M} horario local)"
        )
    print(f"Fila de entrega  : {pending['n']} evento(s) pendente(s)")

    print("\nPor status:")
    for row in by_status:
        print(f"  {row['status']:<24} {row['n']:>6}")

    print("\nEventos:")
    if not events:
        print("  nenhum")
    for row in events:
        print(f"  {row['kind']:<24} {row['n']:>6}  (itens: {row['total']})")

    if by_hour:
        print("\nHorarios de publicacao (UTC) -- onde o alvo mais solta produto:")
        for row in by_hour:
            bar = "#" * min(40, int(row["itens"] or 0))
            print(f"  {row['hora']}h  {row['itens']:>5} itens em {row['n']:>3} eventos  {bar}")
    return 0


def cmd_maintenance(settings: Settings, _args: argparse.Namespace) -> int:
    repo = _build_repo(settings)
    maintenance = Maintenance(
        repo,
        retention_days=settings.retention_days,
        events_retention_days=settings.events_retention_days,
        backup_dir=settings.backup_dir,
        backup_keep=settings.backup_keep,
    )
    report = maintenance.run()
    print(report.describe())
    return 0


def cmd_healthcheck(settings: Settings, args: argparse.Namespace) -> int:
    """Testa vida real, nao "o processo existe".  INF-6

    So e possivel porque `runs` grava TODO ciclo, inclusive os sem novidade --
    um bot saudavel em um dia sem mudanca nao escreveria nada na v1 e seria
    marcado como morto.  DAT-1
    """
    repo = SqliteRepository(settings.db_path)
    try:
        last = repo.last_successful_run_at()
    except Exception as exc:
        print(f"nao foi possivel ler o banco: {exc}", file=sys.stderr)
        return 1
    if last is None:
        print("nenhuma coleta bem-sucedida registrada", file=sys.stderr)
        return 1
    age = (datetime.now(UTC) - last).total_seconds()
    limit = args.max_age_s
    print(f"ultima coleta ha {age:.0f}s (limite {limit}s)")
    return 0 if age <= limit else 1


def cmd_import_legacy(settings: Settings, args: argparse.Namespace) -> int:
    """Traz o historico do banco antigo (`products`) para o schema novo.

    Existe porque o BUG-5 deixou DOIS bancos no repositorio, em lugares
    diferentes, com dados diferentes -- e o que tem historico de verdade nao e
    o que o Docker usava.
    """
    source = Path(args.source)
    if not source.exists():
        print(f"arquivo nao encontrado: {source}", file=sys.stderr)
        return 1

    repo = _build_repo(settings)
    with sqlite3.connect(source) as src:
        src.row_factory = sqlite3.Row
        try:
            rows = src.execute("SELECT amount, date FROM products ORDER BY id").fetchall()
        except sqlite3.Error as exc:
            print(f"{source} nao tem uma tabela `products` legivel: {exc}", file=sys.stderr)
            return 1

    if not rows:
        print("nada a importar")
        return 0

    with repo.connection() as conn:
        conn.executemany(
            "INSERT INTO snapshots (observed_at, amount, payload_hash) VALUES (?, ?, NULL)",
            [(f"{row['date']}T12:00:00+00:00", row["amount"]) for row in rows],
        )
    print(f"{len(rows)} linha(s) importada(s) de {source} para {settings.db_path}")
    print("Obs.: a v1 so gravava a data, sem hora -- as linhas ficaram com 12:00 UTC.")
    return 0


def cmd_config(settings: Settings, _args: argparse.Namespace) -> int:
    print(settings.describe().replace(" ", "\n"))
    return 0


# --------------------------------------------------------------------- cli
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scrapingbot", description=__doc__)
    parser.add_argument("--env-file", help="caminho de um .env alternativo")
    parser.add_argument("--log-level", help="sobrescreve LOG_LEVEL")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="laco principal (padrao)")
    run.add_argument("--dry-run", action="store_true", help="nao envia nada ao Discord")
    run.add_argument("--max-cycles", type=int, default=None, help="para depois de N ciclos")
    run.set_defaults(func=cmd_run)

    once = sub.add_parser("once", help="executa um unico ciclo")
    once.add_argument("--dry-run", action="store_true")
    once.set_defaults(func=cmd_once)

    doctor = sub.add_parser("doctor", help="diagnostico de coleta e cache")
    doctor.add_argument("-n", "--samples", type=int, default=5)
    doctor.set_defaults(func=cmd_doctor)

    stats = sub.add_parser("stats", help="relatorio do historico")
    stats.add_argument("-d", "--days", type=int, default=7)
    stats.set_defaults(func=cmd_stats)

    maintenance = sub.add_parser("maintenance", help="retencao, agregacao e backup")
    maintenance.set_defaults(func=cmd_maintenance)

    health = sub.add_parser("healthcheck", help="exit 0 se coletou recentemente")
    health.add_argument("--max-age-s", type=int, default=600)
    health.set_defaults(func=cmd_healthcheck)

    legacy = sub.add_parser("import-legacy", help="importa um DataBase.db da v1")
    legacy.add_argument("source")
    legacy.set_defaults(func=cmd_import_legacy)

    config = sub.add_parser("config", help="mostra a configuracao efetiva")
    config.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        args = parser.parse_args([*(argv or []), "run"])

    try:
        settings = load_settings(args.env_file)
    except ConfigError as exc:
        # Sem logging configurado ainda -- e proposital: a mensagem precisa
        # chegar ao operador mesmo que o logging seja o que esta quebrado.
        print(f"Erro de configuracao: {exc}", file=sys.stderr)
        return 78  # EX_CONFIG

    setup_logging(
        args.log_level or settings.log_level,
        log_file=settings.log_file,
        max_bytes=settings.log_max_bytes,
        backups=settings.log_backups,
    )

    try:
        return int(args.func(settings, args))
    except KeyboardInterrupt:
        log.info("Interrompido pelo usuario")
        return 130
    except ScrapingBotError as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
