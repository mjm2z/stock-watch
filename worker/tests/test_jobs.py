from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.jobs import (
    claim_next_job,
    complete_job,
    fail_job,
    heartbeat_job,
    recover_stale_jobs,
)


UTC = timezone.utc


class JobQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.now = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)

    def tearDown(self) -> None:
        self.connection.close()

    def _insert_job(self, job_id: str, scheduled_for: str, *, attempt: int = 0) -> None:
        self.connection.execute(
            """
            INSERT INTO job_runs(
                id, job_type, idempotency_key, scheduled_for,
                available_at, status, attempt
            ) VALUES (?, 'scan', ?, ?, ?, 'queued', ?)
            """,
            (job_id, job_id, scheduled_for, scheduled_for, attempt),
        )
        self.connection.commit()

    def test_claims_only_due_job_and_completes_with_lease_owner(self) -> None:
        self._insert_job("future", "2026-08-20T15:00:00Z")
        self._insert_job("due", "2026-08-20T13:00:00Z")

        job = claim_next_job(self.connection, worker_id="worker-a", now=self.now)

        self.assertEqual(job.id if job else None, "due")
        self.assertEqual(job.attempt if job else None, 1)
        heartbeat_job(
            self.connection,
            job_id="due",
            worker_id="worker-a",
            now=self.now + timedelta(minutes=1),
        )
        with self.assertRaisesRegex(ValueError, "leased"):
            complete_job(
                self.connection,
                job_id="due",
                worker_id="worker-b",
                now=self.now,
            )
        complete_job(
            self.connection,
            job_id="due",
            worker_id="worker-a",
            now=self.now + timedelta(minutes=2),
        )
        self.assertEqual(
            self.connection.execute("SELECT status FROM job_runs WHERE id = 'due'").fetchone()[0],
            "succeeded",
        )

    def test_retry_is_delayed_and_attempts_are_bounded(self) -> None:
        self._insert_job("retry", "2026-08-20T13:00:00Z")
        claim_next_job(self.connection, worker_id="worker-a", now=self.now)

        state = fail_job(
            self.connection,
            job_id="retry",
            worker_id="worker-a",
            now=self.now,
            error="temporary provider error",
            retry_at=self.now + timedelta(minutes=5),
            max_attempts=2,
        )

        self.assertEqual(state, "queued")
        self.assertIsNone(
            claim_next_job(
                self.connection,
                worker_id="worker-a",
                now=self.now + timedelta(minutes=4),
            )
        )
        second = claim_next_job(
            self.connection,
            worker_id="worker-a",
            now=self.now + timedelta(minutes=5),
        )
        self.assertEqual(second.attempt if second else None, 2)
        state = fail_job(
            self.connection,
            job_id="retry",
            worker_id="worker-a",
            now=self.now + timedelta(minutes=5),
            error="still failing",
            retry_at=self.now + timedelta(minutes=10),
            max_attempts=2,
        )
        self.assertEqual(state, "failed")

    def test_recovers_stale_leases_or_fails_exhausted_jobs(self) -> None:
        for job_id, attempt in (("recover", 0), ("exhausted", 2)):
            self._insert_job(job_id, "2026-08-20T12:00:00Z", attempt=attempt)
            claim_next_job(self.connection, worker_id=job_id, now=self.now)
        result = recover_stale_jobs(
            self.connection,
            stale_before=self.now + timedelta(minutes=10),
            max_attempts=3,
        )

        self.assertEqual((result.requeued, result.failed), (1, 1))
        statuses = dict(self.connection.execute("SELECT id, status FROM job_runs"))
        self.assertEqual(statuses["recover"], "queued")
        self.assertEqual(statuses["exhausted"], "failed")

    def test_invalid_metadata_does_not_strand_job_in_running_state(self) -> None:
        self.connection.execute(
            """
            INSERT INTO job_runs(
                id, job_type, idempotency_key, scheduled_for,
                available_at, status, metadata_json
            ) VALUES (
                'bad-metadata', 'scan', 'bad-metadata',
                '2026-08-20T13:00:00Z', '2026-08-20T13:00:00Z',
                'queued', '[]'
            )
            """
        )
        self.connection.commit()

        with self.assertRaisesRegex(ValueError, "JSON object"):
            claim_next_job(self.connection, worker_id="worker-a", now=self.now)

        status = self.connection.execute(
            "SELECT status FROM job_runs WHERE id = 'bad-metadata'"
        ).fetchone()[0]
        self.assertEqual(status, "queued")


if __name__ == "__main__":
    unittest.main()
