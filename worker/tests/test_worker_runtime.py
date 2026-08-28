from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.http import ProviderError
from stock_watch_worker.scan_executor import ScanExecutionResult
from stock_watch_worker.worker_runtime import CollectionResult, process_next_job


NOW = datetime(2026, 8, 20, 20, 16, tzinfo=timezone.utc)


class FakeCollector:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def collect_scan(
        self, connection: sqlite3.Connection, *, scan_run_id: str
    ) -> CollectionResult:
        self.calls.append(scan_run_id)
        return CollectionResult(news_coverage_complete=True)


def _scan_result(status: str) -> ScanExecutionResult:
    return ScanExecutionResult(
        scan_run_id="scan-1",
        status=status,
        candidates_total=1,
        candidates_scored=1,
        candidate_failures=int(status == "partial"),
        signals_created=4,
        signals_existing=0,
        qualified_signals=4,
        order_intents_created=0,
        order_intents_rejected=0,
        broker_orders_reconciled=0,
    )


class WorkerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        apply_migrations(self.connection, MIGRATIONS_DIR)

    def tearDown(self) -> None:
        self.connection.close()

    def test_idle_when_no_job_is_due(self) -> None:
        result = process_next_job(
            self.connection, worker_id="worker-a", now=NOW
        )
        self.assertEqual(result.state, "idle")

    def test_collects_executes_and_completes_scan_job(self) -> None:
        self._insert_job()
        collector = FakeCollector()
        with (
            patch("stock_watch_worker.worker_runtime.load_scan_inputs", return_value=object()) as load,
            patch(
                "stock_watch_worker.worker_runtime.execute_scan",
                return_value=_scan_result("succeeded"),
            ),
        ):
            result = process_next_job(
                self.connection,
                worker_id="worker-a",
                now=NOW,
                collector=collector,
            )

        self.assertEqual(result.state, "succeeded")
        self.assertEqual(collector.calls, ["scan-1"])
        self.assertTrue(load.call_args.kwargs["news_coverage_complete"])
        self.assertEqual(self._job_status(), "succeeded")

    def test_partial_scan_is_delayed_for_idempotent_retry(self) -> None:
        self._insert_job()
        with (
            patch("stock_watch_worker.worker_runtime.load_scan_inputs", return_value=object()),
            patch(
                "stock_watch_worker.worker_runtime.execute_scan",
                return_value=_scan_result("partial"),
            ),
        ):
            result = process_next_job(
                self.connection, worker_id="worker-a", now=NOW
            )

        self.assertEqual(result.state, "queued")
        row = self.connection.execute(
            "SELECT status, available_at FROM job_runs WHERE id = 'job-1'"
        ).fetchone()
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["available_at"], "2026-08-20T20:21:00Z")

    def test_paper_scan_reconciles_broker_before_execution(self) -> None:
        self._insert_scan("paper")
        self._insert_job()
        events: list[str] = []
        with (
            patch(
                "stock_watch_worker.worker_runtime.capture_and_reconcile_broker",
                side_effect=lambda *_args, **_kwargs: events.append("reconcile"),
            ) as reconcile,
            patch(
                "stock_watch_worker.worker_runtime.load_scan_inputs",
                return_value=object(),
            ),
            patch(
                "stock_watch_worker.worker_runtime.execute_scan",
                side_effect=lambda *_args, **_kwargs: (
                    events.append("execute") or _scan_result("succeeded")
                ),
            ),
        ):
            result = process_next_job(
                self.connection,
                worker_id="worker-a",
                now=NOW,
                broker_snapshot_provider=object(),  # type: ignore[arg-type]
            )

        self.assertEqual(result.state, "succeeded")
        self.assertEqual(events, ["reconcile", "execute"])
        self.assertEqual(reconcile.call_args.kwargs["captured_at"], NOW)

    def test_nonretryable_provider_failure_fails_job(self) -> None:
        self._insert_job()
        with patch(
            "stock_watch_worker.worker_runtime.load_scan_inputs",
            side_effect=ProviderError(
                "alpaca", 401, "invalid credentials", retryable=False
            ),
        ):
            result = process_next_job(
                self.connection, worker_id="worker-a", now=NOW
            )

        self.assertEqual(result.state, "failed")
        self.assertIsInstance(result.error, ProviderError)
        self.assertEqual(self._job_status(), "failed")

    def test_rejects_unknown_job_type_without_retry(self) -> None:
        self._insert_job(job_type="unknown")
        result = process_next_job(
            self.connection, worker_id="worker-a", now=NOW
        )
        self.assertEqual(result.state, "failed")
        self.assertEqual(self._job_status(), "failed")

    def _insert_job(self, job_type: str = "scan") -> None:
        self.connection.execute(
            """
            INSERT INTO job_runs(
                id, job_type, idempotency_key, scheduled_for,
                available_at, status, metadata_json
            ) VALUES (
                'job-1', ?, 'job-1', '2026-08-20T20:15:00Z',
                '2026-08-20T20:15:00Z', 'queued', ?
            )
            """,
            (job_type, json.dumps({"scan_run_id": "scan-1"})),
        )
        self.connection.commit()

    def _insert_scan(self, strategy_status: str) -> None:
        self.connection.execute(
            """
            INSERT INTO strategy_versions(
                id, name, status, config_json, config_sha256
            ) VALUES ('strategy-v0', 'fixture', ?, '{}', 'strategy-hash')
            """,
            (strategy_status,),
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-08-20', 'fixture', 'snapshot-hash')
            """
        )
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-1', 'strategy-v0', 1, 'close',
                '2026-08-20T20:15:00Z', '2026-08-20T20:15:00Z', 'queued'
            )
            """
        )

    def _job_status(self) -> str:
        return str(
            self.connection.execute(
                "SELECT status FROM job_runs WHERE id = 'job-1'"
            ).fetchone()[0]
        )


if __name__ == "__main__":
    unittest.main()
