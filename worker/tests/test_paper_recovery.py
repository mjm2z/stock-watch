from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from stock_watch_worker.database import apply_migrations, connect, register_strategy
from stock_watch_worker.config import load_strategy
from stock_watch_worker.observability import OperationMonitor

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("paper_recovery", ROOT / "deploy/validate-paper-recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class PaperRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "test.db"
        connection = connect(self.path)
        apply_migrations(connection)
        register_strategy(connection, load_strategy(ROOT / "worker/config/strategy-v0.json"))
        connection.execute("""INSERT INTO universe_snapshots(id, universe, effective_at, source, content_sha256)
            VALUES (1, 'sp500', '2026-01-01', 'test', 'test')""")
        connection.commit()
        connection.close()
        self.operation = Mock(spec=OperationMonitor)

    def tearDown(self):
        self.directory.cleanup()

    def run_recovery(self, scan_status="succeeded", reconciliation="matched"):
        result = SimpleNamespace(status=scan_status, candidates_scored=503, signals_created=2012, qualified_signals=0)
        with (
            patch.object(recovery, "check_deployment_readiness", return_value=SimpleNamespace(ready=True)),
            patch.object(recovery.AlpacaCredentials, "from_environment", return_value=object()),
            patch.object(recovery, "AlpacaPaperTradingClient"),
            patch.object(recovery, "AlpacaMarketDataClient"),
            patch.object(recovery, "AlpacaScanCollector") as collector,
            patch.object(recovery, "load_scan_inputs", return_value=object()),
            patch.object(recovery, "execute_scan", return_value=result) as execute,
            patch.object(recovery, "capture_and_reconcile_broker", return_value=SimpleNamespace(status=reconciliation)),
            patch.object(recovery, "asdict", return_value={"status": scan_status}),
        ):
            collector.return_value.collect_scan.return_value.news_coverage_complete = True
            recovery.validate(self.path, self.operation)
            self.assertIsNone(execute.call_args.kwargs["broker"])

    def test_success_promotes_without_submitting_or_replaying_orders(self):
        self.run_recovery()
        with connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT status FROM strategy_versions WHERE id='sp500-long-paper-v1'").fetchone()[0], "paper")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0], 0)

    def test_failed_scan_does_not_promote(self):
        with self.assertRaisesRegex(RuntimeError, "did not pass"):
            self.run_recovery(scan_status="partial")
        self.assert_not_promoted()

    def test_broker_drift_does_not_promote(self):
        with self.assertRaisesRegex(RuntimeError, "activation stopped"):
            self.run_recovery(reconciliation="drift")
        self.assert_not_promoted()

    def assert_not_promoted(self):
        with connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM strategy_versions WHERE status='paper'").fetchone()[0], 0)
