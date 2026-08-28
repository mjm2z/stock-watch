from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone

from fakes import FakeTransport, json_response
from stock_watch_worker.capture import JsonResponseCapture
from stock_watch_worker.http import ProviderError
from stock_watch_worker.providers.alpaca import (
    AlpacaCredentials,
    AlpacaMarketDataClient,
    AlpacaPaperTradingClient,
)
from stock_watch_worker.storage import ContentAddressedStore


CREDENTIALS = AlpacaCredentials("test-key", "test-secret")


class AlpacaMarketDataTests(unittest.TestCase):
    def test_historical_bars_are_paginated_and_sorted(self) -> None:
        transport = FakeTransport(
            json_response(
                {
                    "bars": {
                        "MSFT": [
                            {
                                "t": "2026-01-03T05:00:00Z",
                                "o": 101,
                                "h": 103,
                                "l": 100,
                                "c": 102,
                                "v": 1000,
                                "n": 50,
                                "vw": 101.5,
                            }
                        ]
                    },
                    "next_page_token": "page-2",
                }
            ),
            json_response(
                {
                    "bars": {
                        "AAPL": [
                            {
                                "t": "2026-01-02T05:00:00Z",
                                "o": 200,
                                "h": 205,
                                "l": 198,
                                "c": 204,
                                "v": 2000,
                            }
                        ]
                    },
                    "next_page_token": None,
                }
            ),
        )
        client = AlpacaMarketDataClient(CREDENTIALS, transport=transport)

        bars = client.get_historical_bars(
            ["msft", "AAPL", "msft"],
            timeframe="1Day",
            start="2026-01-01",
            end="2026-01-04",
        )

        self.assertEqual([bar.symbol for bar in bars], ["AAPL", "MSFT"])
        self.assertEqual(bars[0].close, 204)
        self.assertEqual(len(transport.requests), 2)
        self.assertIn("symbols=MSFT%2CAAPL", transport.requests[0].url)
        self.assertIn("adjustment=all", transport.requests[0].url)
        self.assertIn("feed=iex", transport.requests[0].url)
        self.assertIn("page_token=page-2", transport.requests[1].url)
        self.assertEqual(
            transport.requests[0].headers["APCA-API-KEY-ID"], "test-key"
        )

    def test_news_parses_symbols_and_optional_content(self) -> None:
        transport = FakeTransport(
            json_response(
                {
                    "news": [
                        {
                            "id": 42,
                            "headline": "Example headline",
                            "created_at": "2026-01-02T12:00:00Z",
                            "updated_at": "2026-01-02T12:01:00Z",
                            "source": "Example",
                            "summary": "Summary",
                            "url": "https://example.test/article",
                            "symbols": ["aapl", "MSFT"],
                            "content": "Content",
                        }
                    ],
                    "next_page_token": None,
                }
            )
        )
        client = AlpacaMarketDataClient(CREDENTIALS, transport=transport)

        articles = client.get_news(
            start="2026-01-02T00:00:00Z",
            end="2026-01-03T00:00:00Z",
            symbols=["AAPL"],
            include_content=True,
        )

        self.assertEqual(articles[0].id, 42)
        self.assertEqual(articles[0].symbols, ("AAPL", "MSFT"))
        self.assertIn("include_content=true", transport.requests[0].url)

    def test_snapshot_requests_are_chunked(self) -> None:
        transport = FakeTransport(
            json_response({"AAPL": {"dailyBar": {"c": 200}}}),
            json_response({"MSFT": {"dailyBar": {"c": 400}}}),
        )
        client = AlpacaMarketDataClient(CREDENTIALS, transport=transport)

        snapshots = client.get_snapshots(["AAPL", "MSFT"], chunk_size=1)

        self.assertEqual(set(snapshots), {"AAPL", "MSFT"})
        self.assertEqual(len(transport.requests), 2)

    def test_retryable_provider_error_does_not_expose_credentials(self) -> None:
        transport = FakeTransport(json_response({"message": "slow down"}, status=429))
        client = AlpacaMarketDataClient(CREDENTIALS, transport=transport)

        with self.assertRaises(ProviderError) as raised:
            client.get_snapshots(["AAPL"])

        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("test-secret", str(raised.exception))

    def test_successful_provider_response_is_captured_before_transformation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = JsonResponseCapture(
                ContentAddressedStore(directory),
                provider="alpaca",
                clock=lambda: datetime(2026, 8, 20, tzinfo=timezone.utc),
            )
            transport = FakeTransport(json_response({"AAPL": {"dailyBar": {"c": 200}}}))
            client = AlpacaMarketDataClient(
                CREDENTIALS,
                transport=transport,
                response_observer=capture,
            )

            client.get_snapshots(["AAPL"])

            self.assertEqual(len(capture.captures), 1)
            self.assertTrue(capture.captures[0].path.exists())


class AlpacaPaperTradingTests(unittest.TestCase):
    def test_refuses_live_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "paper endpoint"):
            AlpacaPaperTradingClient(
                CREDENTIALS, base_url="https://api.alpaca.markets"
            )

    def test_submits_narrow_notional_market_buy(self) -> None:
        transport = FakeTransport(json_response({"id": "broker-order-1", "status": "new"}))
        client = AlpacaPaperTradingClient(CREDENTIALS, transport=transport)

        response = client.submit_notional_market_buy(
            symbol="aapl",
            notional_usd=10,
            client_order_id="signal-123",
        )

        self.assertEqual(response["id"], "broker-order-1")
        request = transport.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.url, "https://paper-api.alpaca.markets/v2/orders")
        self.assertEqual(
            json.loads(request.body),
            {
                "symbol": "AAPL",
                "notional": "10.00",
                "side": "buy",
                "type": "market",
                "time_in_force": "day",
                "client_order_id": "signal-123",
            },
        )

    def test_rejects_notional_outside_v1_bounds(self) -> None:
        client = AlpacaPaperTradingClient(CREDENTIALS, transport=FakeTransport())
        for notional in (4.99, 15.01):
            with self.subTest(notional=notional), self.assertRaises(ValueError):
                client.submit_notional_market_buy(
                    symbol="AAPL",
                    notional_usd=notional,
                    client_order_id="signal-123",
                )

    def test_submits_fractional_market_sell(self) -> None:
        transport = FakeTransport(json_response({"id": "broker-exit-1", "status": "new"}))
        client = AlpacaPaperTradingClient(CREDENTIALS, transport=transport)

        response = client.submit_fractional_market_sell(
            symbol="aapl",
            quantity="0.05",
            client_order_id="exit-123",
        )

        self.assertEqual(response["id"], "broker-exit-1")
        self.assertEqual(
            json.loads(transport.requests[0].body),
            {
                "symbol": "AAPL",
                "qty": "0.050000000",
                "side": "sell",
                "type": "market",
                "time_in_force": "day",
                "client_order_id": "exit-123",
            },
        )

    def test_rejects_invalid_fractional_sell(self) -> None:
        client = AlpacaPaperTradingClient(CREDENTIALS, transport=FakeTransport())
        for quantity in (0, -1, "NaN", "0.0000000001"):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                client.submit_fractional_market_sell(
                    symbol="AAPL",
                    quantity=quantity,
                    client_order_id="exit-123",
                )

    def test_fetches_exchange_calendar_with_early_close(self) -> None:
        transport = FakeTransport(
            json_response(
                [
                    {"date": "2026-11-27", "open": "09:30", "close": "13:00"},
                    {"date": "2026-11-30", "open": "09:30", "close": "16:00"},
                ]
            )
        )
        client = AlpacaPaperTradingClient(CREDENTIALS, transport=transport)

        sessions = client.get_market_calendar(start="2026-11-27", end="2026-11-30")

        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].closes_at.hour, 13)
        self.assertIn("start=2026-11-27", transport.requests[0].url)
        self.assertIn("end=2026-11-30", transport.requests[0].url)

    def test_validates_exchange_calendar_response_and_range(self) -> None:
        client = AlpacaPaperTradingClient(CREDENTIALS, transport=FakeTransport())
        with self.assertRaisesRegex(ValueError, "start"):
            client.get_market_calendar(start="2026-02-01", end="2026-01-01")

        malformed = AlpacaPaperTradingClient(
            CREDENTIALS, transport=FakeTransport(json_response(["bad"]))
        )
        with self.assertRaisesRegex(ValueError, "malformed"):
            malformed.get_market_calendar(start="2026-01-01", end="2026-01-02")

    def test_fetches_fractional_asset_eligibility(self) -> None:
        transport = FakeTransport(
            json_response(
                [
                    {
                        "id": "asset-1",
                        "class": "us_equity",
                        "exchange": "NASDAQ",
                        "symbol": "AAPL",
                        "name": "Apple Inc.",
                        "status": "active",
                        "tradable": True,
                        "fractionable": True,
                    }
                ]
            )
        )
        client = AlpacaPaperTradingClient(CREDENTIALS, transport=transport)

        assets = client.get_assets()

        self.assertEqual(assets[0].symbol, "AAPL")
        self.assertTrue(assets[0].fractionable)
        self.assertIn("asset_class=us_equity", transport.requests[0].url)

    def test_fetches_account_positions_and_non_trade_activities(self) -> None:
        transport = FakeTransport(
            json_response(
                {
                    "id": "account-1",
                    "status": "ACTIVE",
                    "currency": "USD",
                    "cash": "100000",
                    "equity": "100010",
                    "long_market_value": "10",
                    "trading_blocked": False,
                    "account_blocked": False,
                    "trade_suspended_by_user": False,
                }
            ),
            json_response(
                [
                    {
                        "asset_id": "asset-1",
                        "symbol": "AAPL",
                        "qty": "0.05",
                        "market_value": "10.50",
                        "current_price": "210",
                        "cost_basis": "10",
                        "side": "long",
                    }
                ]
            ),
            json_response(
                [
                    {
                        "id": "activity-1",
                        "activity_type": "DIV",
                        "date": "2026-08-20",
                        "symbol": "AAPL",
                        "net_amount": "0.01",
                        "qty": "0.05",
                        "per_share_amount": "0.20",
                    }
                ]
            ),
        )
        observed: list[tuple[str, object]] = []
        client = AlpacaPaperTradingClient(
            CREDENTIALS,
            transport=transport,
            response_observer=lambda path, _params, payload: observed.append(
                (path, payload)
            ),
        )

        account = client.get_account()
        positions = client.get_positions()
        activities = client.get_non_trade_activities(after="2026-08-01")

        self.assertEqual(account.equity, 100010)
        self.assertEqual(positions[0].quantity, 0.05)
        self.assertEqual(activities[0].activity_type, "DIV")
        self.assertIn("after=2026-08-01", transport.requests[2].url)
        self.assertEqual(
            [path for path, _payload in observed],
            ["/v2/account", "/v2/positions", "/v2/account/activities"],
        )

    def test_rejects_short_or_non_finite_position(self) -> None:
        for qty, side in (("-1", "short"), ("NaN", "long")):
            with self.subTest(qty=qty, side=side):
                client = AlpacaPaperTradingClient(
                    CREDENTIALS,
                    transport=FakeTransport(
                        json_response(
                            [
                                {
                                    "asset_id": "asset-1",
                                    "symbol": "AAPL",
                                    "qty": qty,
                                    "market_value": "10",
                                    "current_price": "200",
                                    "cost_basis": "10",
                                    "side": side,
                                }
                            ]
                        )
                    ),
                )
                with self.assertRaises(ValueError):
                    client.get_positions()


if __name__ == "__main__":
    unittest.main()
