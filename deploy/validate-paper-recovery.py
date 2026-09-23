"""Run one new research scan and verify the paper account before promotion.

Does not retry historical orders or submit orders. The normal scheduler starts
paper execution at its next exchange-calendar window after installation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from stock_watch_worker.broker_reconciliation import capture_and_reconcile_broker
from stock_watch_worker.collectors import AlpacaScanCollector
from stock_watch_worker.database import connect
from stock_watch_worker.deployment_readiness import check_deployment_readiness
from stock_watch_worker.dispatcher import latest_universe_snapshot_id
from stock_watch_worker.market_calendar import utc_iso
from stock_watch_worker.observability import OperationMonitor, monitor_cli_operation
from stock_watch_worker.providers.alpaca import AlpacaCredentials, AlpacaMarketDataClient, AlpacaPaperTradingClient
from stock_watch_worker.scan_data import load_scan_inputs
from stock_watch_worker.scan_executor import execute_scan
from stock_watch_worker.strategy_promotion import promote_strategy_to_paper


def validate(database: Path, operation: OperationMonitor) -> None:
    connection = connect(database)
    scan_id = f"scan-recovery-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    try:
        readiness = check_deployment_readiness(connection, strategy_id="sp500-long-v0")
        if not readiness.ready:
            raise RuntimeError(f"Research configuration is not ready: {json.dumps(readiness.checks)}")
        # Hard gate: this validation scan must be incapable of creating orders.
        strategy = connection.execute("SELECT status FROM strategy_versions WHERE id='sp500-long-v0'").fetchone()
        if strategy is None or strategy["status"] != "development":
            raise RuntimeError("Recovery requires the unchanged development strategy")
        snapshot_id = latest_universe_snapshot_id(connection, universe="sp500", effective_at=utc_iso(now))
        with connection:
            connection.execute("""INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type, scheduled_for,
                data_cutoff, status, started_at) VALUES (?, 'sp500-long-v0', ?, 'manual', ?, ?, 'running', ?)""",
                (scan_id, snapshot_id, utc_iso(now), utc_iso(now), utc_iso(now)))
        credentials = AlpacaCredentials.from_environment()
        paper = AlpacaPaperTradingClient(credentials)
        operation.progress(0, 3, "Collecting fresh prices and news for the recovery scan")
        collection = AlpacaScanCollector(AlpacaMarketDataClient(credentials), paper).collect_scan(connection, scan_run_id=scan_id)
        operation.progress(1, 3, "Scoring the recovery scan in development mode")
        inputs = load_scan_inputs(connection, scan_run_id=scan_id, news_coverage_complete=collection.news_coverage_complete)
        result = execute_scan(connection, inputs=inputs, now=datetime.now(timezone.utc), broker=None)
        if result.status != "succeeded" or result.candidates_scored < 450 or result.signals_created < 1:
            raise RuntimeError(f"Recovery scan did not pass: {json.dumps(asdict(result))}")
        reconciliation = capture_and_reconcile_broker(connection, broker=paper, captured_at=datetime.now(timezone.utc))
        if reconciliation.status != "matched":
            raise RuntimeError(f"Paper account reconciliation is {reconciliation.status}; activation stopped")
        operation.progress(2, 3, "Research scan passed; enabling the reviewed paper strategy")
        promotion = promote_strategy_to_paper(connection, source_strategy_id="sp500-long-v0",
            paper_strategy_id="sp500-long-paper-v1", confirmation="sp500-long-paper-v1")
        operation.result("Recovery scan passed; paper strategy ready for scheduled execution",
            scan_id=scan_id, candidates=result.candidates_scored, signals=result.signals_created,
            qualified=result.qualified_signals, paper_strategy=promotion.paper_strategy_id)
        print(json.dumps({"scan_id": scan_id, "status": "validated", "candidates": result.candidates_scored,
                          "signals": result.signals_created, "qualified": result.qualified_signals}), flush=True)
    except Exception as error:
        with connection:
            connection.execute("UPDATE scan_runs SET status='failed', error=?, completed_at=? WHERE id=? AND status != 'succeeded'",
                (str(error)[:2000], utc_iso(datetime.now(timezone.utc)), scan_id))
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    args = argparse.Namespace(database=Path('/var/lib/stock-watch/stock-watch.db'), command='repair-paper')
    with monitor_cli_operation(args) as operation:
        validate(args.database, operation)
