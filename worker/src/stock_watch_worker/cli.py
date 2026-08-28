"""Small operational CLI for the worker foundation."""

from __future__ import annotations

import argparse
import socket
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from .backup import create_sqlite_backup
from .backtest_runner import load_backtest_dataset, run_backtest
from .broker_reconciliation import capture_and_reconcile_broker
from .config import load_strategy
from .capture import JsonResponseCapture
from .collectors import AlpacaScanCollector
from .database import apply_migrations, connect, register_strategy
from .dispatcher import dispatch_due_scans, latest_universe_snapshot_id
from .deployment_readiness import check_deployment_readiness, readiness_json
from .forward_outcomes import evaluate_forward_outcomes
from .fundamental_refresh import refresh_company_facts
from .historical_backfill import backfill_historical_bars
from .historical_calendar import backfill_historical_calendar
from .historical_dataset import (
    build_historical_backtest_dataset,
    write_historical_backtest_dataset,
)
from .historical_news import backfill_historical_news
from .ingestion import refresh_asset_metadata
from .market_calendar import due_scan_windows, utc_iso
from .observability import OperationMonitor, monitor_cli_operation
from .jobs import recover_stale_jobs
from .paper_lifecycle import PaperLifecycleResult, reconcile_paper_lifecycle
from .portfolio_snapshots import record_portfolio_snapshot
from .providers.alpaca import (
    AlpacaCredentials,
    AlpacaMarketDataClient,
    AlpacaPaperTradingClient,
)
from .providers.sec import SecClient
from .storage import ContentAddressedStore
from .strategy_promotion import promote_strategy_to_paper
from .universe import (
    import_universe_snapshot_if_changed,
    import_universe_snapshot,
    read_members_csv,
    read_members_history_csv,
)
from .universe_sync import sync_universe_from_latest_source, validate_universe_members
from .worker_runtime import process_next_job


SOURCE_DEFAULT_STRATEGY = (
    Path(__file__).resolve().parents[2] / "config" / "strategy-v0.json"
)
PACKAGED_DEFAULT_STRATEGY = Path(__file__).resolve().with_name("strategy-v0.json")
DEFAULT_STRATEGY = (
    SOURCE_DEFAULT_STRATEGY
    if SOURCE_DEFAULT_STRATEGY.exists()
    else PACKAGED_DEFAULT_STRATEGY
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stock-watch-worker")
    commands = parser.add_subparsers(dest="command", required=True)

    init_db = commands.add_parser("init-db", help="initialize or migrate SQLite")
    init_db.add_argument("--database", type=Path, required=True)
    init_db.add_argument("--strategy", type=Path, default=DEFAULT_STRATEGY)

    promote = commands.add_parser(
        "promote-strategy",
        help="clone a reviewed strategy into a new immutable paper version",
    )
    promote.add_argument("--database", type=Path, required=True)
    promote.add_argument("--source-strategy-id", default="sp500-long-v0")
    promote.add_argument("--paper-strategy-id", required=True)
    promote.add_argument("--paper-strategy-name")
    promote.add_argument(
        "--confirm-paper-trading",
        required=True,
        metavar="PAPER_STRATEGY_ID",
        help="must exactly repeat --paper-strategy-id",
    )

    readiness = commands.add_parser(
        "deployment-check",
        help="verify strategy, universe, CIK, and asset readiness",
    )
    readiness.add_argument("--database", type=Path, required=True)
    readiness.add_argument("--strategy-id", default="sp500-long-v0")
    readiness.add_argument("--minimum-universe-members", type=int, default=450)
    readiness.add_argument("--minimum-asset-coverage", type=float, default=0.95)
    readiness.add_argument("--minimum-cik-coverage", type=float, default=0.95)

    import_universe = commands.add_parser(
        "import-universe", help="import a versioned universe CSV snapshot"
    )
    import_universe.add_argument("--database", type=Path, required=True)
    import_universe.add_argument("--csv", type=Path, required=True)
    import_universe.add_argument("--effective-at", required=True)
    import_universe.add_argument("--source", required=True)
    import_universe.add_argument("--source-url")
    import_universe.add_argument("--survivorship-biased", action="store_true")
    import_universe.add_argument("--minimum-members", type=int, default=1)
    import_universe.add_argument("--maximum-members", type=int, default=1_000_000)
    import_universe.add_argument("--minimum-cik-coverage", type=float, default=0)

    import_history = commands.add_parser(
        "import-universe-history",
        help="import long-form point-in-time universe membership snapshots",
    )
    import_history.add_argument("--database", type=Path, required=True)
    import_history.add_argument("--csv", type=Path, required=True)
    import_history.add_argument("--universe", default="sp500")
    import_history.add_argument("--source", required=True)
    import_history.add_argument("--source-url")
    import_history.add_argument("--survivorship-biased", action="store_true")

    sync_universe = commands.add_parser(
        "sync-universe",
        help="safely synchronize a universe from its approved HTTPS CSV source",
    )
    sync_universe.add_argument("--database", type=Path, required=True)
    sync_universe.add_argument("--universe", default="sp500")
    sync_universe.add_argument("--minimum-members", type=int, default=450)
    sync_universe.add_argument("--maximum-members", type=int, default=550)
    sync_universe.add_argument("--minimum-cik-coverage", type=float, default=0.95)
    sync_universe.add_argument("--maximum-symbol-churn", type=float, default=0.10)
    sync_universe.add_argument(
        "--now", help="aware ISO timestamp; defaults to current UTC"
    )

    dispatch = commands.add_parser(
        "dispatch-once", help="enqueue any currently due market scan"
    )
    dispatch.add_argument("--database", type=Path, required=True)
    dispatch.add_argument("--strategy-id", default="sp500-long-v0")
    dispatch.add_argument("--universe", default="sp500")
    dispatch.add_argument("--now", help="aware ISO timestamp; defaults to current UTC")
    dispatch.add_argument("--grace-minutes", type=int, default=20)

    refresh_assets = commands.add_parser(
        "refresh-assets", help="refresh Alpaca paper eligibility for universe members"
    )
    refresh_assets.add_argument("--database", type=Path, required=True)
    refresh_assets.add_argument("--snapshot-id", type=int)
    refresh_assets.add_argument("--universe", default="sp500")

    refresh_fundamentals = commands.add_parser(
        "refresh-fundamentals",
        help="refresh stale SEC CompanyFacts for universe members",
    )
    refresh_fundamentals.add_argument("--database", type=Path, required=True)
    refresh_fundamentals.add_argument("--data-path", type=Path, required=True)
    refresh_fundamentals.add_argument("--snapshot-id", type=int)
    refresh_fundamentals.add_argument("--universe", default="sp500")
    refresh_fundamentals.add_argument("--maximum-age-hours", type=float, default=24)

    work = commands.add_parser(
        "work-once", help="claim and process at most one durable worker job"
    )
    work.add_argument("--database", type=Path, required=True)
    work.add_argument("--data-path", type=Path, required=True)
    work.add_argument("--worker-id", default=socket.gethostname())
    work.add_argument("--now", help="aware ISO timestamp; defaults to current UTC")

    maintain = commands.add_parser(
        "maintain-paper",
        help="reconcile paper lots and persist newly mature signal outcomes",
    )
    maintain.add_argument("--database", type=Path, required=True)
    maintain.add_argument("--data-path", type=Path, required=True)
    maintain.add_argument("--now", help="aware ISO timestamp; defaults to current UTC")
    maintain.add_argument("--calendar-lookahead-days", type=int, default=220)
    maintain.add_argument("--round-trip-cost-bps", type=float, default=10.0)

    backtest = commands.add_parser(
        "run-backtest",
        help="run and persist a versioned close-signal walk-forward backtest",
    )
    backtest.add_argument("--database", type=Path, required=True)
    backtest.add_argument("--dataset", type=Path, required=True)
    backtest.add_argument("--strategy-id", default="sp500-long-v0")
    backtest.add_argument("--universe-snapshot-id", type=int, required=True)
    backtest.add_argument("--round-trip-cost-bps", type=float, default=10.0)
    backtest.add_argument("--minimum-validation-trades", type=int, default=20)
    backtest.add_argument("--minimum-reliability-trades", type=int, default=30)
    backtest.add_argument("--now", help="aware ISO timestamp; defaults to current UTC")

    historical_bars = commands.add_parser(
        "backfill-bars",
        help="backfill versioned adjusted daily bars for a universe and SPY",
    )
    historical_bars.add_argument("--database", type=Path, required=True)
    historical_bars.add_argument("--data-path", type=Path, required=True)
    historical_bars.add_argument("--universe-snapshot-id", type=int, required=True)
    historical_bars.add_argument("--start", type=date.fromisoformat, required=True)
    historical_bars.add_argument("--end", type=date.fromisoformat, required=True)
    historical_bars.add_argument("--symbol-chunk-size", type=int, default=100)
    historical_bars.add_argument(
        "--feed", choices=("iex", "sip", "delayed_sip"), default="iex"
    )
    historical_bars.add_argument("--point-in-time-universe", action="store_true")

    historical_calendar = commands.add_parser(
        "backfill-calendar",
        help="backfill versioned US-equity exchange sessions",
    )
    historical_calendar.add_argument("--database", type=Path, required=True)
    historical_calendar.add_argument("--data-path", type=Path, required=True)
    historical_calendar.add_argument("--start", type=date.fromisoformat, required=True)
    historical_calendar.add_argument("--end", type=date.fromisoformat, required=True)
    historical_calendar.add_argument("--window-days", type=int, default=366)

    historical_news = commands.add_parser(
        "backfill-news",
        help="backfill versioned historical news for a universe",
    )
    historical_news.add_argument("--database", type=Path, required=True)
    historical_news.add_argument("--data-path", type=Path, required=True)
    historical_news.add_argument("--universe-snapshot-id", type=int, required=True)
    historical_news.add_argument("--start", type=date.fromisoformat, required=True)
    historical_news.add_argument("--end", type=date.fromisoformat, required=True)
    historical_news.add_argument("--symbol-chunk-size", type=int, default=50)
    historical_news.add_argument("--window-days", type=int, default=7)
    historical_news.add_argument("--point-in-time-universe", action="store_true")

    build_dataset = commands.add_parser(
        "build-backtest-dataset",
        help="build a point-in-time scored close-signal manifest from stored data",
    )
    build_dataset.add_argument("--database", type=Path, required=True)
    build_dataset.add_argument("--output", type=Path, required=True)
    build_dataset.add_argument("--strategy-id", default="sp500-long-v0")
    build_dataset.add_argument("--universe-snapshot-id", type=int, required=True)
    build_dataset.add_argument("--start", type=date.fromisoformat, required=True)
    build_dataset.add_argument("--end", type=date.fromisoformat, required=True)
    build_dataset.add_argument("--signal-stride-sessions", type=int, default=5)
    build_dataset.add_argument("--history-sessions", type=int, default=260)
    build_dataset.add_argument("--maximum-signals", type=int, default=1_000_000)
    build_dataset.add_argument("--point-in-time-universe", action="store_true")
    build_dataset.add_argument("--historical-news-ingestion-id", type=int)
    build_dataset.add_argument("--historical-calendar-ingestion-id", type=int)
    build_dataset.add_argument("--news-lookback-days", type=int, default=3)

    backup = commands.add_parser(
        "backup", help="create and verify a retention-bounded SQLite backup"
    )
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--destination", type=Path, required=True)
    backup.add_argument("--keep", type=int, default=14)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with monitor_cli_operation(args) as operation:
        exit_status = _run_command(args, operation)
        if exit_status != 0:
            operation.fail(
                RuntimeError(
                    f"{args.command} completed with non-zero status {exit_status}"
                )
            )
        return exit_status


def _run_command(args: argparse.Namespace, operation: OperationMonitor) -> int:
    if args.command == "init-db":
        args.database.parent.mkdir(parents=True, exist_ok=True)
        connection = connect(args.database)
        try:
            applied = apply_migrations(connection)
            registered = register_strategy(connection, load_strategy(args.strategy))
        finally:
            connection.close()
        if applied:
            print(f"applied migrations: {', '.join(applied)}")
        else:
            print("database is current")
        print("strategy registered" if registered else "strategy already registered")
        return 0
    if args.command == "promote-strategy":
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = promote_strategy_to_paper(
                connection,
                source_strategy_id=args.source_strategy_id,
                paper_strategy_id=args.paper_strategy_id,
                paper_strategy_name=args.paper_strategy_name,
                confirmation=args.confirm_paper_trading,
            )
        finally:
            connection.close()
        state = "created" if result.created else "already existed"
        print(
            f"paper strategy {result.paper_strategy_id} {state}: "
            f"source={result.source_strategy_id} "
            f"sha256={result.paper_strategy_sha256} "
            f"promoted_at={result.promoted_at}"
        )
        return 0
    if args.command == "deployment-check":
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = check_deployment_readiness(
                connection,
                strategy_id=args.strategy_id,
                minimum_universe_members=args.minimum_universe_members,
                minimum_asset_coverage=args.minimum_asset_coverage,
                minimum_cik_coverage=args.minimum_cik_coverage,
            )
        finally:
            connection.close()
        print(readiness_json(result))
        return 0 if result.ready else 2
    if args.command == "import-universe":
        members = read_members_csv(args.csv)
        validate_universe_members(
            members,
            minimum_members=args.minimum_members,
            maximum_members=args.maximum_members,
            minimum_cik_coverage=args.minimum_cik_coverage,
        )
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = import_universe_snapshot_if_changed(
                connection,
                members,
                universe="sp500",
                effective_at=args.effective_at,
                source=args.source,
                source_url=args.source_url,
                survivorship_biased=args.survivorship_biased,
            )
        finally:
            connection.close()
        state = "already existed" if result.already_existed else "created"
        print(
            f"snapshot {result.snapshot_id} {state}: "
            f"{result.member_count} members, sha256={result.content_sha256}"
        )
        return 0
    if args.command == "import-universe-history":
        snapshots = read_members_history_csv(args.csv)
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            results = [
                import_universe_snapshot(
                    connection,
                    snapshot.members,
                    universe=args.universe,
                    effective_at=snapshot.effective_at,
                    source=args.source,
                    source_url=args.source_url,
                    survivorship_biased=args.survivorship_biased,
                )
                for snapshot in snapshots
            ]
        finally:
            connection.close()
        print(
            f"snapshots={len(results)} created="
            f"{sum(not result.already_existed for result in results)} "
            f"members={sum(result.member_count for result in results)}"
        )
        return 0
    if args.command == "sync-universe":
        now = _parse_aware_datetime(args.now) if args.now else datetime.now(timezone.utc)
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = sync_universe_from_latest_source(
                connection,
                universe=args.universe,
                effective_at=utc_iso(now),
                minimum_members=args.minimum_members,
                maximum_members=args.maximum_members,
                minimum_cik_coverage=args.minimum_cik_coverage,
                maximum_symbol_churn=args.maximum_symbol_churn,
            )
        finally:
            connection.close()
        state = "unchanged" if result.import_result.already_existed else "created"
        print(
            f"snapshot={result.import_result.snapshot_id} state={state} "
            f"members={result.import_result.member_count} "
            f"cik_coverage={result.cik_coverage:.3f} "
            f"added={len(result.added_symbols)} removed={len(result.removed_symbols)}"
        )
        operation.result(
            f"universe synchronization {state}",
            snapshot_id=result.import_result.snapshot_id,
            state=state,
            members=result.import_result.member_count,
            cik_coverage=result.cik_coverage,
            added_symbols=result.added_symbols,
            removed_symbols=result.removed_symbols,
        )
        return 0
    if args.command == "refresh-assets":
        now = datetime.now(timezone.utc)
        broker = AlpacaPaperTradingClient(AlpacaCredentials.from_environment())
        assets = broker.get_assets()
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            snapshot_id = args.snapshot_id or latest_universe_snapshot_id(
                connection,
                universe=args.universe,
                effective_at=utc_iso(now),
            )
            result = refresh_asset_metadata(
                connection,
                assets,
                universe_snapshot_id=snapshot_id,
            )
        finally:
            connection.close()
        print(
            f"snapshot={snapshot_id} updated={result.updated} "
            f"unchanged={result.unchanged} missing={len(result.missing_symbols)}"
        )
        operation.result(
            "Alpaca asset eligibility refresh completed",
            snapshot_id=snapshot_id,
            updated=result.updated,
            unchanged=result.unchanged,
            missing_symbols=result.missing_symbols,
        )
        return 0
    if args.command == "refresh-fundamentals":
        if args.maximum_age_hours <= 0:
            raise ValueError("maximum-age-hours must be positive")
        now = datetime.now(timezone.utc)
        capture = JsonResponseCapture(
            ContentAddressedStore(args.data_path),
            provider="sec",
        )
        sec = SecClient.from_environment(response_observer=capture)
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            snapshot_id = args.snapshot_id or latest_universe_snapshot_id(
                connection,
                universe=args.universe,
                effective_at=utc_iso(now),
            )
            result = refresh_company_facts(
                connection,
                sec=sec,
                universe_snapshot_id=snapshot_id,
                now=now,
                maximum_age=timedelta(hours=args.maximum_age_hours),
                progress=operation.progress,
            )
        finally:
            connection.close()
        print(
            f"snapshot={snapshot_id} refreshed={result.refreshed} "
            f"fresh={result.skipped_fresh} missing_cik={len(result.missing_cik)} "
            f"unavailable={len(result.unavailable)} raw_captures={len(capture.captures)}"
        )
        operation.result(
            "SEC CompanyFacts refresh completed",
            snapshot_id=snapshot_id,
            refreshed=result.refreshed,
            fresh=result.skipped_fresh,
            missing_cik=len(result.missing_cik),
            unavailable=len(result.unavailable),
            raw_captures=len(capture.captures),
        )
        return 0
    if args.command == "dispatch-once":
        now = _parse_aware_datetime(args.now) if args.now else datetime.now(timezone.utc)
        if args.grace_minutes <= 0:
            raise ValueError("grace-minutes must be positive")
        market_date = now.astimezone(ZoneInfo("America/New_York")).date()
        broker = AlpacaPaperTradingClient(AlpacaCredentials.from_environment())
        sessions = broker.get_market_calendar(start=market_date, end=market_date)
        due = due_scan_windows(
            now,
            sessions,
            grace_period=timedelta(minutes=args.grace_minutes),
        )
        if not due:
            print(f"no scan due at {utc_iso(now)}")
            operation.discard_on_success()
            return 0
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            snapshot_id = latest_universe_snapshot_id(
                connection,
                universe=args.universe,
                effective_at=utc_iso(now),
            )
            result = dispatch_due_scans(
                connection,
                now=now,
                sessions=sessions,
                strategy_version_id=args.strategy_id,
                universe_snapshot_id=snapshot_id,
                grace_period=timedelta(minutes=args.grace_minutes),
            )
        finally:
            connection.close()
        print(
            f"due={result.due_windows} scans_created={result.scans_created} "
            f"jobs_created={result.jobs_created}"
        )
        operation.result(
            "due market scans dispatched",
            due_windows=result.due_windows,
            scans_created=result.scans_created,
            jobs_created=result.jobs_created,
        )
        return 0
    if args.command == "work-once":
        now = _parse_aware_datetime(args.now) if args.now else datetime.now(timezone.utc)
        credentials = AlpacaCredentials.from_environment()
        capture = JsonResponseCapture(
            ContentAddressedStore(args.data_path),
            provider="alpaca",
        )
        market_data = AlpacaMarketDataClient(
            credentials,
            response_observer=capture,
        )
        paper_trading = AlpacaPaperTradingClient(
            credentials,
            response_observer=capture,
        )
        collector = AlpacaScanCollector(market_data, paper_trading)
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            recovered = recover_stale_jobs(
                connection,
                stale_before=now - timedelta(minutes=15),
            )
            result = process_next_job(
                connection,
                worker_id=args.worker_id,
                now=now,
                collector=collector,
                broker=paper_trading,
                broker_snapshot_provider=paper_trading,
            )
        finally:
            connection.close()
        print(
            f"state={result.state} job={result.job_id or '-'} "
            f"scan={result.scan_run_id or '-'} recovered={recovered.requeued} "
            f"expired={recovered.failed} raw_captures={len(capture.captures)}"
        )
        operation.result(
            f"worker completed with state={result.state}",
            state=result.state,
            job_id=result.job_id,
            scan_run_id=result.scan_run_id,
            recovered=recovered.requeued,
            expired=recovered.failed,
            raw_captures=len(capture.captures),
        )
        if result.error is not None:
            operation.fail(result.error)
        if result.state == "idle" and recovered.requeued == 0 and recovered.failed == 0:
            operation.discard_on_success()
        return 0
    if args.command == "maintain-paper":
        if args.calendar_lookahead_days < 1:
            raise ValueError("calendar-lookahead-days must be positive")
        now = _parse_aware_datetime(args.now) if args.now else datetime.now(timezone.utc)
        capture = JsonResponseCapture(
            ContentAddressedStore(args.data_path),
            provider="alpaca-paper",
        )
        broker = AlpacaPaperTradingClient(
            AlpacaCredentials.from_environment(),
            response_observer=capture,
        )
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            outcomes = evaluate_forward_outcomes(
                connection,
                observed_at=now,
                round_trip_cost_bps=args.round_trip_cost_bps,
            )
            active = connection.execute(
                """
                SELECT COUNT(*) AS count, MIN(opened_at) AS earliest_opened
                FROM paper_trade_lots
                WHERE status IN ('pending', 'open', 'closing')
                """
            ).fetchone()
            lifecycle = PaperLifecycleResult(0, 0, 0, 0, 0)
            if int(active["count"]):
                market_date = now.astimezone(ZoneInfo("America/New_York")).date()
                earliest = (
                    _parse_aware_datetime(str(active["earliest_opened"])).astimezone(
                        ZoneInfo("America/New_York")
                    ).date()
                    if active["earliest_opened"]
                    else market_date
                )
                sessions = broker.get_market_calendar(
                    start=earliest,
                    end=market_date + timedelta(days=args.calendar_lookahead_days),
                )
                lifecycle = reconcile_paper_lifecycle(
                    connection,
                    broker=broker,
                    sessions=sessions,
                    now=now,
                )
            reconciliation = capture_and_reconcile_broker(
                connection,
                broker=broker,
                captured_at=now,
            )
            snapshot = record_portfolio_snapshot(connection, observed_at=now)
        finally:
            connection.close()
        print(
            f"entries_reconciled={lifecycle.entries_reconciled} "
            f"targets_updated={lifecycle.targets_updated} "
            f"exit_intents_created={lifecycle.exit_intents_created} "
            f"exits_reconciled={lifecycle.exits_reconciled} "
            f"lots_closed={lifecycle.lots_closed} "
            f"broker_reconciliation={reconciliation.status} "
            f"broker_discrepancies={len(reconciliation.discrepancies)} "
            f"broker_activities={reconciliation.activities_inserted} "
            f"outcomes_completed={outcomes.completed} "
            f"outcomes_pending={outcomes.pending_history} "
            f"outcomes_missing={outcomes.missing_history} "
            f"snapshot_inserted={int(snapshot.inserted)} "
            f"equity={snapshot.equity:.4f} "
            f"spy_value={snapshot.spy_value if snapshot.spy_value is not None else '-'} "
            f"raw_captures={len(capture.captures)}"
        )
        operation.result(
            "paper lifecycle maintenance completed",
            entries_reconciled=lifecycle.entries_reconciled,
            targets_updated=lifecycle.targets_updated,
            exit_intents_created=lifecycle.exit_intents_created,
            exits_reconciled=lifecycle.exits_reconciled,
            lots_closed=lifecycle.lots_closed,
            broker_reconciliation=reconciliation.status,
            broker_discrepancies=len(reconciliation.discrepancies),
            outcomes_completed=outcomes.completed,
            outcomes_pending=outcomes.pending_history,
            outcomes_missing=outcomes.missing_history,
            equity=snapshot.equity,
            spy_value=snapshot.spy_value,
            raw_captures=len(capture.captures),
        )
        return 0
    if args.command == "run-backtest":
        now = _parse_aware_datetime(args.now) if args.now else datetime.now(timezone.utc)
        dataset = load_backtest_dataset(args.dataset)
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = run_backtest(
                connection,
                dataset=dataset,
                strategy_version_id=args.strategy_id,
                universe_snapshot_id=args.universe_snapshot_id,
                round_trip_cost_bps=args.round_trip_cost_bps,
                minimum_validation_trades=args.minimum_validation_trades,
                minimum_reliability_trades=args.minimum_reliability_trades,
                now=now,
            )
        finally:
            connection.close()
        print(
            f"run={result.run_id} status={result.status} "
            f"trades={result.trades} rejections={result.rejections} "
            f"splits={result.splits} inserted={int(result.inserted)} "
            f"dataset_sha256={dataset.content_sha256}"
        )
        return 0
    if args.command == "backfill-bars":
        credentials = AlpacaCredentials.from_environment()
        capture = JsonResponseCapture(
            ContentAddressedStore(args.data_path),
            provider="alpaca",
        )
        market_data = AlpacaMarketDataClient(
            credentials,
            response_observer=capture,
        )
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = backfill_historical_bars(
                connection,
                provider=market_data,
                universe_snapshot_id=args.universe_snapshot_id,
                start=args.start,
                end=args.end,
                symbol_chunk_size=args.symbol_chunk_size,
                feed=args.feed,
                point_in_time_universe=args.point_in_time_universe,
            )
        finally:
            connection.close()
        print(
            f"ingestion={result.ingestion_id} symbols={result.symbols} "
            f"requests={result.logical_requests} observed={result.bars_observed} "
            f"inserted={result.bars_inserted} unchanged={result.bars_unchanged} "
            f"existing={int(result.already_succeeded)} "
            f"raw_captures={len(capture.captures)}"
        )
        return 0
    if args.command == "backfill-calendar":
        capture = JsonResponseCapture(
            ContentAddressedStore(args.data_path),
            provider="alpaca-paper",
        )
        broker = AlpacaPaperTradingClient(
            AlpacaCredentials.from_environment(),
            response_observer=capture,
        )
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = backfill_historical_calendar(
                connection,
                provider=broker,
                start=args.start,
                end=args.end,
                window_days=args.window_days,
            )
        finally:
            connection.close()
        print(
            f"ingestion={result.ingestion_id} requests={result.logical_requests} "
            f"sessions={result.sessions_observed} inserted={result.sessions_inserted} "
            f"unchanged={result.sessions_unchanged} "
            f"reused={int(result.already_succeeded)} raw_captures={len(capture.captures)}"
        )
        return 0
    if args.command == "backfill-news":
        credentials = AlpacaCredentials.from_environment()
        capture = JsonResponseCapture(
            ContentAddressedStore(args.data_path),
            provider="alpaca",
        )
        market_data = AlpacaMarketDataClient(
            credentials,
            response_observer=capture,
        )
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = backfill_historical_news(
                connection,
                provider=market_data,
                universe_snapshot_id=args.universe_snapshot_id,
                start=args.start,
                end=args.end,
                symbol_chunk_size=args.symbol_chunk_size,
                window_days=args.window_days,
                point_in_time_universe=args.point_in_time_universe,
            )
        finally:
            connection.close()
        print(
            f"ingestion={result.ingestion_id} symbols={result.symbols} "
            f"requests={result.logical_requests} observed={result.articles_observed} "
            f"inserted={result.articles_inserted} unchanged={result.articles_unchanged} "
            f"unknown_symbols={len(result.unknown_symbols)} "
            f"reused={int(result.already_succeeded)} raw_captures={len(capture.captures)}"
        )
        return 0
    if args.command == "build-backtest-dataset":
        connection = connect(args.database)
        try:
            apply_migrations(connection)
            result = build_historical_backtest_dataset(
                connection,
                strategy_version_id=args.strategy_id,
                universe_snapshot_id=args.universe_snapshot_id,
                start=args.start,
                end=args.end,
                signal_stride_sessions=args.signal_stride_sessions,
                history_sessions=args.history_sessions,
                maximum_signals=args.maximum_signals,
                point_in_time_universe=args.point_in_time_universe,
                historical_news_ingestion_id=args.historical_news_ingestion_id,
                historical_calendar_ingestion_id=args.historical_calendar_ingestion_id,
                news_lookback_days=args.news_lookback_days,
            )
        finally:
            connection.close()
        bytes_written = write_historical_backtest_dataset(args.output, result)
        print(
            f"output={args.output} bytes={bytes_written} "
            f"sessions={result.stats.sessions_evaluated} "
            f"instruments={result.stats.instruments} "
            f"scored={result.stats.scored_symbol_sessions} "
            f"signals={result.stats.signals} "
            f"qualified={result.stats.qualified_signals} "
            f"skipped_history={result.stats.skipped_insufficient_history} "
            f"news_observations={result.stats.news_observations}"
        )
        return 0
    if args.command == "backup":
        result = create_sqlite_backup(
            args.database,
            args.destination,
            keep=args.keep,
        )
        print(f"backup={result.path} removed={len(result.removed)}")
        operation.result(
            "verified SQLite backup completed",
            backup_path=result.path,
            removed=len(result.removed),
        )
        return 0
    return 2


def _parse_aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include a timezone")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
