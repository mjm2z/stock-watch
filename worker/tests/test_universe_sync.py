from __future__ import annotations

import sqlite3
import unittest

from fakes import FakeTransport
from stock_watch_worker.database import MIGRATIONS_DIR, apply_migrations
from stock_watch_worker.http import HttpResponse
from stock_watch_worker.universe import UniverseMember, import_universe_snapshot
from stock_watch_worker.universe_sync import (
    sync_universe_from_latest_source,
    sync_universe_from_url,
)


SOURCE_URL = "https://source.example/sp500.csv"


def csv_response(symbols: list[str], *, with_ciks: bool = True) -> HttpResponse:
    rows = ["Symbol,Security,CIK"]
    for index, symbol in enumerate(symbols, start=1):
        cik = str(index) if with_ciks else ""
        rows.append(f"{symbol},{symbol} Corp,{cik}")
    return HttpResponse(
        status=200,
        headers={"Content-Type": "text/csv"},
        body=("\n".join(rows) + "\n").encode(),
    )


class UniverseSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(self.connection, MIGRATIONS_DIR)
        self.symbols = [f"S{index:03d}" for index in range(500)]
        import_universe_snapshot(
            self.connection,
            [
                UniverseMember(symbol, f"{symbol} Corp", cik=str(index + 1))
                for index, symbol in enumerate(self.symbols)
            ],
            universe="sp500",
            effective_at="2026-08-26T09:30:00Z",
            source="approved fixture",
            source_url=SOURCE_URL,
        )

    def tearDown(self) -> None:
        self.connection.close()

    def test_unchanged_download_reuses_latest_snapshot(self) -> None:
        transport = FakeTransport(csv_response(self.symbols))

        result = sync_universe_from_latest_source(
            self.connection,
            universe="sp500",
            effective_at="2026-08-27T09:30:00Z",
            transport=transport,
        )

        self.assertTrue(result.import_result.already_existed)
        self.assertEqual(result.import_result.member_count, 500)
        self.assertEqual(result.added_symbols, ())
        self.assertEqual(result.removed_symbols, ())
        self.assertEqual(transport.requests[0].url, SOURCE_URL)

    def test_valid_change_creates_a_new_snapshot(self) -> None:
        changed = [*self.symbols[:-1], "NEW"]

        result = sync_universe_from_latest_source(
            self.connection,
            universe="sp500",
            effective_at="2026-08-27T09:30:00Z",
            transport=FakeTransport(csv_response(changed)),
        )

        self.assertFalse(result.import_result.already_existed)
        self.assertEqual(result.added_symbols, ("NEW",))
        self.assertEqual(result.removed_symbols, ("S499",))
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM universe_snapshots"
            ).fetchone()[0],
            2,
        )

    def test_rejects_insecure_url_low_cik_coverage_and_large_churn(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            sync_universe_from_url(
                self.connection,
                universe="sp500",
                effective_at="2026-08-27",
                source="fixture",
                source_url="http://source.example/sp500.csv",
                transport=FakeTransport(csv_response(self.symbols)),
            )
        with self.assertRaisesRegex(ValueError, "CIK coverage"):
            sync_universe_from_latest_source(
                self.connection,
                universe="sp500",
                effective_at="2026-08-27",
                transport=FakeTransport(csv_response(self.symbols, with_ciks=False)),
            )
        replacements = [f"N{index:03d}" for index in range(100)]
        with self.assertRaisesRegex(ValueError, "symbol churn"):
            sync_universe_from_latest_source(
                self.connection,
                universe="sp500",
                effective_at="2026-08-27",
                transport=FakeTransport(
                    csv_response([*self.symbols[:400], *replacements])
                ),
            )

    def test_http_and_member_count_fail_without_writing(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
            sync_universe_from_latest_source(
                self.connection,
                universe="sp500",
                effective_at="2026-08-27",
                transport=FakeTransport(HttpResponse(503, {}, b"unavailable")),
            )
        with self.assertRaisesRegex(ValueError, "member count"):
            sync_universe_from_latest_source(
                self.connection,
                universe="sp500",
                effective_at="2026-08-27",
                transport=FakeTransport(csv_response(self.symbols[:10])),
            )
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM universe_snapshots"
            ).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
