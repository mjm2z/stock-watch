from __future__ import annotations

import unittest

from stock_watch_worker.cli import _parse_aware_datetime, build_parser


class CliTests(unittest.TestCase):
    def test_universe_sync_has_fail_closed_defaults(self) -> None:
        args = build_parser().parse_args(
            ["sync-universe", "--database", "/tmp/stock-watch.db"]
        )

        self.assertEqual(args.universe, "sp500")
        self.assertEqual(args.minimum_members, 450)
        self.assertEqual(args.maximum_members, 550)
        self.assertEqual(args.minimum_cik_coverage, 0.95)
        self.assertEqual(args.maximum_symbol_churn, 0.10)

    def test_manual_universe_import_can_be_readiness_gated(self) -> None:
        args = build_parser().parse_args(
            [
                "import-universe",
                "--database",
                "/tmp/stock-watch.db",
                "--csv",
                "/tmp/sp500.csv",
                "--effective-at",
                "2026-08-27",
                "--source",
                "fixture",
                "--minimum-members",
                "450",
                "--maximum-members",
                "550",
                "--minimum-cik-coverage",
                "0.95",
            ]
        )

        self.assertEqual(args.minimum_members, 450)
        self.assertEqual(args.maximum_members, 550)
        self.assertEqual(args.minimum_cik_coverage, 0.95)

    def test_deployment_check_has_fail_closed_coverage_defaults(self) -> None:
        args = build_parser().parse_args(
            ["deployment-check", "--database", "/tmp/stock-watch.db"]
        )

        self.assertEqual(args.strategy_id, "sp500-long-v0")
        self.assertEqual(args.minimum_universe_members, 450)
        self.assertEqual(args.minimum_asset_coverage, 0.95)
        self.assertEqual(args.minimum_cik_coverage, 0.95)

    def test_paper_promotion_requires_explicit_repeated_version_id(self) -> None:
        args = build_parser().parse_args(
            [
                "promote-strategy",
                "--database",
                "/tmp/stock-watch.db",
                "--paper-strategy-id",
                "sp500-long-paper-v1",
                "--confirm-paper-trading",
                "sp500-long-paper-v1",
            ]
        )

        self.assertEqual(args.source_strategy_id, "sp500-long-v0")
        self.assertEqual(args.paper_strategy_id, "sp500-long-paper-v1")
        self.assertEqual(args.confirm_paper_trading, "sp500-long-paper-v1")

    def test_dispatch_parser_has_safe_defaults(self) -> None:
        args = build_parser().parse_args(
            ["dispatch-once", "--database", "/tmp/stock-watch.db"]
        )

        self.assertEqual(args.strategy_id, "sp500-long-v0")
        self.assertEqual(args.universe, "sp500")
        self.assertEqual(args.grace_minutes, 20)

    def test_dispatch_now_requires_explicit_timezone(self) -> None:
        self.assertEqual(
            _parse_aware_datetime("2026-08-20T14:00:00Z").isoformat(),
            "2026-08-20T14:00:00+00:00",
        )
        with self.assertRaisesRegex(ValueError, "timezone"):
            _parse_aware_datetime("2026-08-20T14:00:00")

    def test_refresh_assets_parser_accepts_explicit_snapshot(self) -> None:
        args = build_parser().parse_args(
            [
                "refresh-assets",
                "--database",
                "/tmp/stock-watch.db",
                "--snapshot-id",
                "7",
            ]
        )

        self.assertEqual(args.snapshot_id, 7)
        self.assertEqual(args.universe, "sp500")

    def test_work_once_requires_durable_raw_data_path(self) -> None:
        args = build_parser().parse_args(
            [
                "work-once",
                "--database",
                "/tmp/stock-watch.db",
                "--data-path",
                "/tmp/stock-watch-data",
                "--worker-id",
                "test-worker",
            ]
        )

        self.assertEqual(args.worker_id, "test-worker")
        self.assertEqual(str(args.data_path), "/tmp/stock-watch-data")

    def test_fundamental_refresh_defaults_to_daily_cache(self) -> None:
        args = build_parser().parse_args(
            [
                "refresh-fundamentals",
                "--database",
                "/tmp/stock-watch.db",
                "--data-path",
                "/tmp/stock-watch-data",
            ]
        )

        self.assertEqual(args.maximum_age_hours, 24)
        self.assertIsNone(args.snapshot_id)

    def test_backup_defaults_to_two_weeks_of_retention(self) -> None:
        args = build_parser().parse_args(
            [
                "backup",
                "--database",
                "/tmp/stock-watch.db",
                "--destination",
                "/tmp/stock-watch-backups",
            ]
        )

        self.assertEqual(args.keep, 14)

    def test_paper_maintenance_has_bounded_calendar_and_cost_defaults(self) -> None:
        args = build_parser().parse_args(
            [
                "maintain-paper",
                "--database",
                "/tmp/stock-watch.db",
                "--data-path",
                "/tmp/stock-watch-data",
            ]
        )

        self.assertEqual(args.calendar_lookahead_days, 220)
        self.assertEqual(args.round_trip_cost_bps, 10.0)

    def test_backtest_requires_explicit_dataset_and_universe_snapshot(self) -> None:
        args = build_parser().parse_args(
            [
                "run-backtest",
                "--database",
                "/tmp/stock-watch.db",
                "--dataset",
                "/tmp/backtest.json",
                "--universe-snapshot-id",
                "7",
            ]
        )

        self.assertEqual(args.strategy_id, "sp500-long-v0")
        self.assertEqual(args.universe_snapshot_id, 7)
        self.assertEqual(args.round_trip_cost_bps, 10.0)
        self.assertEqual(args.minimum_validation_trades, 20)
        self.assertEqual(args.minimum_reliability_trades, 30)

    def test_historical_backfill_defaults_to_adjusted_iex_daily_bars(self) -> None:
        args = build_parser().parse_args(
            [
                "backfill-bars",
                "--database",
                "/tmp/stock-watch.db",
                "--data-path",
                "/tmp/stock-watch-data",
                "--universe-snapshot-id",
                "7",
                "--start",
                "2020-01-01",
                "--end",
                "2025-12-31",
            ]
        )

        self.assertEqual(args.feed, "iex")
        self.assertEqual(args.symbol_chunk_size, 100)
        self.assertEqual(args.start.isoformat(), "2020-01-01")
        self.assertFalse(args.point_in_time_universe)

    def test_universe_history_import_defaults(self) -> None:
        args = build_parser().parse_args(
            [
                "import-universe-history",
                "--database",
                "/tmp/worker.db",
                "--csv",
                "/tmp/history.csv",
                "--source",
                "fixture",
            ]
        )

        self.assertEqual(args.universe, "sp500")
        self.assertFalse(args.survivorship_biased)

    def test_historical_news_backfill_has_bounded_defaults(self) -> None:
        args = build_parser().parse_args(
            [
                "backfill-news",
                "--database",
                "/tmp/worker.db",
                "--data-path",
                "/tmp/data",
                "--universe-snapshot-id",
                "7",
                "--start",
                "2020-01-01",
                "--end",
                "2020-12-31",
            ]
        )

        self.assertEqual(args.symbol_chunk_size, 50)
        self.assertEqual(args.window_days, 7)
        self.assertFalse(args.point_in_time_universe)

    def test_historical_calendar_backfill_has_bounded_default(self) -> None:
        args = build_parser().parse_args(
            [
                "backfill-calendar",
                "--database",
                "/tmp/worker.db",
                "--data-path",
                "/tmp/data",
                "--start",
                "2020-01-01",
                "--end",
                "2020-12-31",
            ]
        )

        self.assertEqual(args.window_days, 366)

    def test_historical_dataset_builder_has_bounded_research_defaults(self) -> None:
        args = build_parser().parse_args(
            [
                "build-backtest-dataset",
                "--database",
                "/tmp/stock-watch.db",
                "--output",
                "/tmp/backtest.json",
                "--universe-snapshot-id",
                "7",
                "--start",
                "2020-01-01",
                "--end",
                "2024-12-31",
            ]
        )

        self.assertEqual(args.signal_stride_sessions, 5)
        self.assertEqual(args.history_sessions, 260)
        self.assertEqual(args.maximum_signals, 1_000_000)
        self.assertFalse(args.point_in_time_universe)
        self.assertIsNone(args.historical_news_ingestion_id)
        self.assertIsNone(args.historical_calendar_ingestion_id)
        self.assertEqual(args.news_lookback_days, 3)


if __name__ == "__main__":
    unittest.main()
