"""Provider collection adapters used before deterministic scan execution."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from itertools import islice
from typing import Iterator, Sequence

from .ingestion import (
    persist_market_bars,
    persist_news_articles,
    refresh_asset_metadata,
)
from .providers.alpaca import AlpacaMarketDataClient, AlpacaPaperTradingClient
from .worker_runtime import CollectionResult


@dataclass(frozen=True, slots=True)
class AlpacaCollectionMetrics:
    assets_updated: int
    missing_asset_symbols: int
    bars_observed: int
    bars_inserted: int
    news_observed: int
    news_inserted: int


class AlpacaScanCollector:
    """Collect adjusted daily bars, news, and paper eligibility for one scan."""

    def __init__(
        self,
        market_data: AlpacaMarketDataClient,
        paper_trading: AlpacaPaperTradingClient,
        *,
        symbol_chunk_size: int = 100,
        history_calendar_days: int = 420,
        news_lookback: timedelta = timedelta(days=3),
    ) -> None:
        if symbol_chunk_size < 1:
            raise ValueError("symbol_chunk_size must be positive")
        if history_calendar_days < 300:
            raise ValueError("history_calendar_days must be at least 300")
        if news_lookback <= timedelta(0):
            raise ValueError("news_lookback must be positive")
        self._market_data = market_data
        self._paper_trading = paper_trading
        self._symbol_chunk_size = symbol_chunk_size
        self._history_calendar_days = history_calendar_days
        self._news_lookback = news_lookback

    def collect_scan(
        self, connection: sqlite3.Connection, *, scan_run_id: str
    ) -> CollectionResult:
        scan = connection.execute(
            """
            SELECT universe_snapshot_id, data_cutoff
            FROM scan_runs WHERE id = ?
            """,
            (scan_run_id,),
        ).fetchone()
        if scan is None:
            raise ValueError("scan run does not exist")
        version = f"{scan_run_id}:alpaca-scan-v0"
        existing = connection.execute(
            """
            SELECT id, status, metadata_json FROM data_ingestions
            WHERE dataset = 'scan_bundle' AND provider = 'alpaca' AND version = ?
            """,
            (version,),
        ).fetchone()
        if existing is not None and existing["status"] == "succeeded":
            metadata = json.loads(str(existing["metadata_json"]))
            return CollectionResult(
                news_coverage_complete=bool(metadata.get("news_coverage_complete"))
            )

        with connection:
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO data_ingestions(
                        dataset, provider, started_at, status, version
                    ) VALUES ('scan_bundle', 'alpaca', CURRENT_TIMESTAMP, 'running', ?)
                    """,
                    (version,),
                )
                ingestion_id = int(cursor.lastrowid)
            else:
                ingestion_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE data_ingestions
                    SET started_at = CURRENT_TIMESTAMP, completed_at = NULL,
                        status = 'running', error = NULL
                    WHERE id = ?
                    """,
                    (ingestion_id,),
                )

        try:
            symbols = _universe_symbols(
                connection, int(scan["universe_snapshot_id"])
            )
            _ensure_spy(connection)
            assets = self._paper_trading.get_assets()
            asset_result = refresh_asset_metadata(
                connection,
                assets,
                universe_snapshot_id=int(scan["universe_snapshot_id"]),
            )

            cutoff = _parse_timestamp(str(scan["data_cutoff"]))
            start = cutoff - timedelta(days=self._history_calendar_days)
            bars_observed = 0
            bars_inserted = 0
            for chunk in _chunks((*symbols, "SPY"), self._symbol_chunk_size):
                bars = self._market_data.get_historical_bars(
                    chunk,
                    timeframe="1Day",
                    start=_utc_iso(start),
                    end=_utc_iso(cutoff),
                    adjustment="all",
                    feed="iex",
                )
                result = persist_market_bars(
                    connection,
                    bars,
                    timeframe="1Day",
                    adjustment="all",
                    provider="alpaca",
                    ingestion_id=ingestion_id,
                )
                bars_observed += len(bars)
                bars_inserted += result.inserted

            articles = self._market_data.get_news(
                start=_utc_iso(cutoff - self._news_lookback),
                end=_utc_iso(cutoff),
                include_content=False,
            )
            news_result = persist_news_articles(
                connection,
                articles,
                provider="alpaca",
                ingestion_id=ingestion_id,
            )
            metrics = AlpacaCollectionMetrics(
                assets_updated=asset_result.updated,
                missing_asset_symbols=len(asset_result.missing_symbols),
                bars_observed=bars_observed,
                bars_inserted=bars_inserted,
                news_observed=len(articles),
                news_inserted=news_result.inserted,
            )
            metadata = {
                **asdict(metrics),
                "news_coverage_complete": True,
            }
            with connection:
                connection.execute(
                    """
                    UPDATE data_ingestions
                    SET completed_at = CURRENT_TIMESTAMP, status = 'succeeded',
                        request_count = ?, row_count = ?, metadata_json = ?
                    WHERE id = ?
                    """,
                    (
                        len(tuple(_chunks((*symbols, "SPY"), self._symbol_chunk_size))) + 2,
                        bars_observed + len(articles),
                        _canonical_json(metadata),
                        ingestion_id,
                    ),
                )
            return CollectionResult(news_coverage_complete=True)
        except Exception as error:
            with connection:
                connection.execute(
                    """
                    UPDATE data_ingestions
                    SET completed_at = CURRENT_TIMESTAMP, status = 'failed', error = ?
                    WHERE id = ?
                    """,
                    (str(error)[:2000], ingestion_id),
                )
            raise


def _universe_symbols(
    connection: sqlite3.Connection, snapshot_id: int
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT instruments.symbol
        FROM universe_memberships
        JOIN instruments ON instruments.id = universe_memberships.instrument_id
        WHERE universe_memberships.snapshot_id = ?
        ORDER BY instruments.symbol
        """,
        (snapshot_id,),
    ).fetchall()
    symbols = tuple(str(row["symbol"]) for row in rows)
    if not symbols:
        raise ValueError("scan universe snapshot has no members")
    return symbols


def _ensure_spy(connection: sqlite3.Connection) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO instruments(symbol, name, exchange, active)
            VALUES ('SPY', 'SPDR S&P 500 ETF Trust', 'ARCA', 1)
            ON CONFLICT(symbol, asset_class) DO UPDATE SET active = 1
            """
        )


def _chunks(values: Sequence[str], size: int) -> Iterator[tuple[str, ...]]:
    iterator = iter(dict.fromkeys(values))
    while chunk := tuple(islice(iterator, size)):
        yield chunk


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("scan data cutoff must include a timezone")
    return parsed


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
