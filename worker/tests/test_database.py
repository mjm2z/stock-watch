from __future__ import annotations

import sqlite3
import tempfile
import shutil
from pathlib import Path
import unittest

from stock_watch_worker.database import (
    INSTALLED_MIGRATIONS_DIR,
    MIGRATIONS_DIR,
    SOURCE_MIGRATIONS_DIR,
    apply_migrations,
)


class DatabaseMigrationTests(unittest.TestCase):
    def test_source_and_installed_migration_locations_are_defined(self) -> None:
        self.assertEqual(MIGRATIONS_DIR, SOURCE_MIGRATIONS_DIR)
        self.assertEqual(
            INSTALLED_MIGRATIONS_DIR.parts[-3:],
            ("share", "stock-watch-worker", "migrations"),
        )

    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def tearDown(self) -> None:
        self.connection.close()

    def test_initial_migration_creates_core_tables(self) -> None:
        applied = apply_migrations(self.connection, MIGRATIONS_DIR)
        self.assertEqual(
            applied,
            [
                "001_initial",
                "002_backtests",
                "003_job_leases",
                "004_company_facts",
                "005_paper_exits",
                "006_portfolio_attribution",
                "007_broker_reconciliation",
                "008_market_sessions",
                "009_observability",
                "010_market_data_revisions",
                "011_outcome_freshness",
                "012_shared_research",
                "013_assessment_controls",
                "014_news_revisions",
                "015_exit_timing", "016_systems", "017_bitcoin_automation", "018_workspace", "019_research_control", "020_correctness",
            ],
        )

        tables = {
            row["name"]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(
            {
                "strategy_versions",
                "scan_runs",
                "signals",
                "paper_orders",
                "paper_trade_lots",
                "paper_exit_orders",
                "paper_exit_fills",
                "signal_outcomes",
                "job_runs",
                "backtest_runs",
                "backtest_splits",
                "backtest_trades",
                "backtest_rejections",
                "company_fact_documents",
                "broker_account_snapshots",
                "broker_position_snapshots",
                "broker_account_activities",
                "broker_reconciliations",
                "market_sessions",
                "operation_runs",
                "operation_events",
            }.issubset(tables)
        )

    def test_failed_migration_rolls_back_ddl_and_version_stamp(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'001_broken.sql').write_text('CREATE TABLE partial(id INTEGER); INVALID SQL;')
            with self.assertRaises(sqlite3.OperationalError):
                apply_migrations(self.connection,directory)
        self.assertIsNone(self.connection.execute("SELECT 1 FROM sqlite_master WHERE name='partial'").fetchone())
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0],0)

    def test_news_upgrade_preserves_original_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            for source in MIGRATIONS_DIR.glob('*.sql'):
                if source.name < '014':
                    shutil.copy(source,Path(directory)/source.name)
            apply_migrations(self.connection,directory)
        self.connection.execute("INSERT INTO instruments(id,symbol) VALUES (1,'AAPL')")
        self.connection.execute("INSERT INTO news_articles(id,provider,published_at,updated_at,headline,content_hash) VALUES ('alpaca:1','alpaca','2026-01-01T12:00:00Z','2026-01-01T13:00:00Z','Original','hash')")
        self.connection.execute("INSERT INTO news_instruments(news_id,instrument_id,sentiment,sentiment_model) VALUES ('alpaca:1',1,.5,'lexicon-v0')")
        self.connection.commit()
        apply_migrations(self.connection,MIGRATIONS_DIR)
        self.assertEqual(self.connection.execute("SELECT headline FROM news_articles").fetchone()[0],'Original')
        row=self.connection.execute("SELECT available_at,first_observed_at FROM news_revisions").fetchone()
        self.assertEqual(tuple(row),('2026-01-01T13:00:00Z',None))
        self.assertEqual(self.connection.execute("SELECT sentiment FROM news_revision_instruments").fetchone()[0],.5)
        self.assertEqual(apply_migrations(self.connection,MIGRATIONS_DIR),[])

    def test_backtest_split_boundaries_must_be_chronological(self) -> None:
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'development', '{}', 'hash', CURRENT_TIMESTAMP, NULL)"
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-01-01', 'test', 'snapshot-hash')
            """
        )
        self.connection.execute(
            """
            INSERT INTO backtest_runs(
                id, strategy_version_id, universe_snapshot_id,
                dataset_version, dataset_sha256, feature_set_version,
                status, survivorship_biased, round_trip_cost_bps
            ) VALUES (
                'run-1', 'strategy-v0', 1,
                'bars-v1', 'dataset-hash', 'features-v0',
                'running', 1, 10
            )
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO backtest_splits(
                    backtest_run_id, split_index,
                    train_start, train_end, validation_start, validation_end,
                    test_start, test_end
                ) VALUES (
                    'run-1', 0,
                    '2025-01-01', '2025-12-31',
                    '2025-12-01', '2026-01-31',
                    '2026-02-01', '2026-03-31'
                )
                """
            )

    def test_migrations_are_idempotent(self) -> None:
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.assertEqual(apply_migrations(self.connection, MIGRATIONS_DIR), [])

    def test_020_preserves_populated_stock_and_bitcoin_ownership(self):
        import importlib.util
        installer = Path(__file__).resolve().parents[2] / 'deploy/install-reviewed-release.py'
        spec = importlib.util.spec_from_file_location('release_preservation', installer)
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory() as directory:
            for source in MIGRATIONS_DIR.glob('*.sql'):
                if source.name < '020':
                    shutil.copy(source, Path(directory) / source.name)
            apply_migrations(self.connection, directory)
        self._seed_trade_dependencies()
        self.connection.executescript("""
            UPDATE paper_orders SET status='partially_filled' WHERE id='order-1';
            INSERT INTO paper_fills(id,order_id,filled_at,quantity,price,notional_usd)
              VALUES ('fill','order-1','2026-01-02T15:00:00Z',.04,100,4);
            INSERT INTO paper_trade_lots(id,signal_id,strategy_version_id,instrument_id,
              horizon_trading_days,entry_order_id,status,entry_notional_usd,entry_quantity,entry_price)
              VALUES ('lot','signal-1','strategy-v0',1,21,'order-1','open',10,.04,100);
            INSERT INTO btc_accounts(id,initial_cash,cash,created_at)
              VALUES ('separate-paper','300','100','2026-01-01T00:00:00Z');
            INSERT INTO system_versions(id,asset,template,config_json,config_sha256,created_at)
              VALUES ('manual-v1','bitcoin','trend','{}','retained-v1-hash','2026-01-01T00:00:00Z'),
                     ('automatic-v1','bitcoin','trend','{}','retained-auto-hash','2026-01-01T00:00:00Z');
            INSERT INTO btc_allocations(version_id,account_id,budget,cash,quantity,high_water,approved_at,started_at)
              VALUES ('manual-v1','separate-paper','100','60','.4','100','2026-01-01','2026-01-01'),
                     ('automatic-v1','separate-paper','100','100','0','100','2026-01-01','2026-01-01');
            INSERT INTO btc_enrollments(version_id,enrolled_at,approved_at)
              VALUES ('manual-v1','2026-01-01','2026-01-01'),('automatic-v1','2026-01-01','2026-01-01');
            INSERT INTO btc_evaluations(id,version_id,cutoff,due_at,expires_at,created_at)
              VALUES ('evaluation','manual-v1','2026-01-01','2026-01-01','2026-02-01','2026-01-01');
            INSERT INTO btc_qualifications(version_id,evaluation_id,status,reason,checked_at,next_review_at)
              VALUES ('manual-v1','evaluation','qualified','Observed forward evidence','2026-01-01','2026-02-01');
            INSERT INTO btc_orders(id,version_id,account_id,side,quantity,reserved_cash,filled_qty,
              filled_notional,status,reference_price,created_at,updated_at,reason)
              VALUES ('uncertain','automatic-v1','separate-paper','buy','.5','50','0','0',
                      'unknown','100','2026-01-01','2026-01-01','Uncertain submit retains reservation'),
                     ('partial','manual-v1','separate-paper','buy','.5','10','.4','40',
                      'partially_filled','100','2026-01-01','2026-01-01','Partial fill');
            INSERT INTO btc_fills VALUES ('btc-fill','partial','2026-01-01','.4','40');
            INSERT INTO btc_fees VALUES ('fee','separate-paper','partial','{}','attributed','2026-01-01');
            INSERT INTO btc_fee_allocations VALUES ('fee','partial','.1','0','observed');
            INSERT INTO discovery_batches(id,created_at,updated_at) VALUES ('batch','2026-01-01','2026-01-01');
            INSERT INTO discovery_trials(id,batch_id,version_id,asset,policy_id,budget,status,created_at)
              VALUES ('trial','batch','automatic-v1','bitcoin',1,'100','completed','2026-01-01');
            INSERT INTO paper_authorizations VALUES ('automatic-v1','trial',1,'2026-01-01','100','separate-paper','active');
        """)
        before = release.authority(self.connection)
        self.assertEqual(apply_migrations(self.connection, MIGRATIONS_DIR), ['020_correctness'])
        self.assertEqual(before, release.authority(self.connection, before))
        self.assertEqual(apply_migrations(self.connection, MIGRATIONS_DIR), [])
        self.assertEqual(self.connection.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM paper_authorizations').fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT reserved_cash FROM btc_orders WHERE id='uncertain'").fetchone()[0], '50')

    def test_partial_unique_index_prevents_duplicate_open_lots(self) -> None:
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self._seed_trade_dependencies()

        self.connection.execute(
            """
            INSERT INTO paper_trade_lots(
                id, signal_id, strategy_version_id, instrument_id,
                horizon_trading_days, entry_order_id, status,
                entry_notional_usd
            ) VALUES ('lot-1', 'signal-1', 'strategy-v0', 1, 21, 'order-1', 'open', 10)
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """
                INSERT INTO paper_trade_lots(
                    id, signal_id, strategy_version_id, instrument_id,
                    horizon_trading_days, entry_order_id, status,
                    entry_notional_usd
                ) VALUES ('lot-2', 'signal-2', 'strategy-v0', 1, 21, 'order-2', 'pending', 10)
                """
            )

    def _seed_trade_dependencies(self) -> None:
        self.connection.execute(
            "INSERT INTO strategy_versions VALUES "
            "('strategy-v0', 'test', 'development', '{}', 'hash', CURRENT_TIMESTAMP, NULL)"
        )
        self.connection.execute(
            "INSERT INTO instruments(id, symbol) VALUES (1, 'AAPL')"
        )
        self.connection.execute(
            """
            INSERT INTO universe_snapshots(
                id, universe, effective_at, source, content_sha256
            ) VALUES (1, 'sp500', '2026-01-02', 'test', 'snapshot-hash')
            """
        )
        self.connection.execute(
            """
            INSERT INTO feature_snapshots(
                id, instrument_id, as_of, feature_set_version,
                features_json, data_completeness
            ) VALUES (1, 1, '2026-01-02T14:45:00Z', 'features-v0', '{}', 100)
            """
        )
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-1', 'strategy-v0', 1, 'open',
                '2026-01-02T14:45:00Z', '2026-01-02T14:45:00Z', 'succeeded'
            )
            """
        )
        self.connection.execute(
            """
            INSERT INTO scan_runs(
                id, strategy_version_id, universe_snapshot_id, scan_type,
                scheduled_for, data_cutoff, status
            ) VALUES (
                'scan-2', 'strategy-v0', 1, 'close',
                '2026-01-02T21:15:00Z', '2026-01-02T21:15:00Z', 'succeeded'
            )
            """
        )
        for signal_id, scan_id, horizon in (
            ("signal-1", "scan-1", 21),
            ("signal-2", "scan-2", 21),
        ):
            self.connection.execute(
                """
                INSERT INTO signals(
                    id, scan_run_id, strategy_version_id, instrument_id,
                    feature_snapshot_id, horizon_trading_days, as_of,
                    opportunity_score, data_completeness, risk_level,
                    decision, explanation
                ) VALUES (?, ?, 'strategy-v0', 1, 1, ?,
                    '2026-01-02T14:45:00Z', 85, 100, 'low',
                    'qualified', 'test')
                """,
                (signal_id, scan_id, horizon),
            )
        for order_id, signal_id in (("order-1", "signal-1"), ("order-2", "signal-2")):
            self.connection.execute(
                """
                INSERT INTO paper_orders(
                    id, signal_id, client_order_id, side, order_type,
                    time_in_force, notional_usd, status
                ) VALUES (?, ?, ?, 'buy', 'market', 'day', 10, 'pending')
                """,
                (order_id, signal_id, f"client-{order_id}"),
            )


if __name__ == "__main__":
    unittest.main()
