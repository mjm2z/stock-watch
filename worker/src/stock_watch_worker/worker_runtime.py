"""One-job worker runtime connecting leases, collection, scans, and retries."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from .broker_reconciliation import BrokerSnapshotProvider, capture_and_reconcile_broker
from .http import ProviderError
from .jobs import claim_next_job, complete_job, fail_job
from .paper_orders import PaperOrderBroker
from .scan_data import load_scan_inputs
from .scan_executor import ScanExecutionResult, execute_scan


@dataclass(frozen=True, slots=True)
class CollectionResult:
    news_coverage_complete: bool


class ScanCollector(Protocol):
    def collect_scan(
        self, connection: sqlite3.Connection, *, scan_run_id: str
    ) -> CollectionResult: ...


@dataclass(frozen=True, slots=True)
class WorkResult:
    state: str
    job_id: str | None = None
    scan_run_id: str | None = None
    scan_result: ScanExecutionResult | None = None
    error: Exception | None = None


def process_next_job(
    connection: sqlite3.Connection,
    *,
    worker_id: str,
    now: datetime,
    collector: ScanCollector | None = None,
    broker: PaperOrderBroker | None = None,
    broker_snapshot_provider: BrokerSnapshotProvider | None = None,
    retry_delay: timedelta = timedelta(minutes=5),
    max_attempts: int = 3,
) -> WorkResult:
    if retry_delay <= timedelta(0):
        raise ValueError("retry_delay must be positive")
    job = claim_next_job(connection, worker_id=worker_id, now=now)
    if job is None:
        return WorkResult("idle")
    if job.job_type != "scan":
        fail_job(
            connection,
            job_id=job.id,
            worker_id=worker_id,
            now=now,
            error=f"unsupported job type: {job.job_type}",
            max_attempts=max_attempts,
        )
        return WorkResult("failed", job_id=job.id)
    scan_run_id = job.metadata.get("scan_run_id")
    if not isinstance(scan_run_id, str) or not scan_run_id:
        fail_job(
            connection,
            job_id=job.id,
            worker_id=worker_id,
            now=now,
            error="scan job metadata is missing scan_run_id",
            max_attempts=max_attempts,
        )
        return WorkResult("failed", job_id=job.id)

    try:
        collection = (
            collector.collect_scan(connection, scan_run_id=scan_run_id)
            if collector is not None
            else CollectionResult(news_coverage_complete=False)
        )
        if broker_snapshot_provider is not None and _scan_strategy_is_paper(
            connection, scan_run_id
        ):
            capture_and_reconcile_broker(
                connection,
                broker=broker_snapshot_provider,
                captured_at=now,
            )
        inputs = load_scan_inputs(
            connection,
            scan_run_id=scan_run_id,
            news_coverage_complete=collection.news_coverage_complete,
        )
        result = execute_scan(
            connection,
            inputs=inputs,
            now=now,
            broker=broker,
        )
        if result.status == "succeeded":
            complete_job(
                connection,
                job_id=job.id,
                worker_id=worker_id,
                now=now,
            )
            return WorkResult(
                "succeeded",
                job_id=job.id,
                scan_run_id=scan_run_id,
                scan_result=result,
            )
        state = fail_job(
            connection,
            job_id=job.id,
            worker_id=worker_id,
            now=now,
            error="scan completed partially and requires reconciliation",
            retry_at=now + retry_delay,
            max_attempts=max_attempts,
        )
        return WorkResult(
            state,
            job_id=job.id,
            scan_run_id=scan_run_id,
            scan_result=result,
        )
    except Exception as error:
        retryable = not isinstance(error, ProviderError) or error.retryable
        state = fail_job(
            connection,
            job_id=job.id,
            worker_id=worker_id,
            now=now,
            error=str(error),
            retry_at=now + retry_delay if retryable else None,
            max_attempts=max_attempts,
        )
        return WorkResult(
            state,
            job_id=job.id,
            scan_run_id=scan_run_id,
            error=error,
        )


def _scan_strategy_is_paper(
    connection: sqlite3.Connection, scan_run_id: str
) -> bool:
    row = connection.execute(
        """
        SELECT strategy.status
        FROM scan_runs AS scans
        JOIN strategy_versions AS strategy ON strategy.id = scans.strategy_version_id
        WHERE scans.id = ?
        """,
        (scan_run_id,),
    ).fetchone()
    if row is None:
        raise ValueError("scan run does not exist")
    return row["status"] == "paper"
