"""Restart-safe historical adjusted daily-bar ingestion for backtest research."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date
from itertools import islice
from typing import Iterator, Protocol, Sequence

from .ingestion import persist_market_bars
from .providers.alpaca import MarketBar
from .universe import load_universe_timeline


class HistoricalBarsProvider(Protocol):
    def get_historical_bars(
        self,
        symbols: Sequence[str],
        *,
        timeframe: str,
        start: str,
        end: str,
        adjustment: str = "all",
        feed: str = "iex",
    ) -> list[MarketBar]: ...


@dataclass(frozen=True, slots=True)
class HistoricalBackfillResult:
    ingestion_id: int
    version: str
    symbols: int
    logical_requests: int
    bars_observed: int
    bars_inserted: int
    bars_unchanged: int
    already_succeeded: bool


def backfill_historical_bars(
    connection: sqlite3.Connection,
    *,
    provider: HistoricalBarsProvider,
    universe_snapshot_id: int,
    start: date,
    end: date,
    symbol_chunk_size: int = 100,
    feed: str = "iex",
    adjustment: str = "all",
    point_in_time_universe: bool = False,
) -> HistoricalBackfillResult:
    if start > end:
        raise ValueError("historical backfill start must not be after end")
    if symbol_chunk_size < 1 or symbol_chunk_size > 500:
        raise ValueError("historical backfill chunk size must be between 1 and 500")
    if feed not in {"iex", "sip", "delayed_sip"}:
        raise ValueError("unsupported historical backfill feed")
    if adjustment not in {"raw", "split", "dividend", "spin-off", "all"}:
        raise ValueError("unsupported historical backfill adjustment")

    if point_in_time_universe:
        timeline = load_universe_timeline(
            connection,
            anchor_snapshot_id=universe_snapshot_id,
            start=start,
            end=end,
        )
        symbols = tuple(sorted({symbol for item in timeline for symbol in item.members}))
        timeline_json = json.dumps(
            [
                {
                    "id": item.snapshot_id,
                    "effective_at": item.effective_at,
                    "sha256": item.content_sha256,
                }
                for item in timeline
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        membership_version = "timeline=" + hashlib.sha256(
            timeline_json.encode("utf-8")
        ).hexdigest()
        snapshot_ids = [item.snapshot_id for item in timeline]
    else:
        symbols = _universe_symbols(connection, universe_snapshot_id)
        membership_version = f"snapshot={universe_snapshot_id}"
        snapshot_ids = [universe_snapshot_id]
    _ensure_spy(connection)
    all_symbols = tuple(dict.fromkeys((*symbols, "SPY")))
    version = (
        f"historical-bars-v2:{membership_version}:"
        f"start={start.isoformat()}:end={end.isoformat()}:"
        f"feed={feed}:adjustment={adjustment}"
    )
    existing = connection.execute(
        """
        SELECT id, status, metadata_json FROM data_ingestions
        WHERE dataset = 'historical_bars' AND provider = 'alpaca' AND version = ?
        """,
        (version,),
    ).fetchone()
    if existing is not None and existing["status"] == "succeeded":
        metadata = json.loads(str(existing["metadata_json"]))
        return HistoricalBackfillResult(
            ingestion_id=int(existing["id"]),
            version=version,
            symbols=int(metadata["symbols"]),
            logical_requests=int(metadata["logical_requests"]),
            bars_observed=int(metadata["bars_observed"]),
            bars_inserted=int(metadata["bars_inserted"]),
            bars_unchanged=int(metadata["bars_unchanged"]),
            already_succeeded=True,
        )

    with connection:
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO data_ingestions(
                    dataset, provider, started_at, status, version,
                    metadata_json
                ) VALUES ('historical_bars', 'alpaca', CURRENT_TIMESTAMP,
                          'running', ?, '{}')
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

    chunks = tuple(_chunks(all_symbols, symbol_chunk_size))
    observed = 0
    inserted = 0
    unchanged = 0
    attempted = 0
    try:
        for chunk in chunks:
            attempted += 1
            bars = provider.get_historical_bars(
                chunk,
                timeframe="1Day",
                start=start.isoformat(),
                end=end.isoformat(),
                adjustment=adjustment,
                feed=feed,
            )
            result = persist_market_bars(
                connection,
                bars,
                timeframe="1Day",
                adjustment=adjustment,
                provider="alpaca",
                ingestion_id=ingestion_id,
            )
            observed += len(bars)
            inserted += result.inserted
            unchanged += result.unchanged
        metrics = HistoricalBackfillResult(
            ingestion_id=ingestion_id,
            version=version,
            symbols=len(all_symbols),
            logical_requests=len(chunks),
            bars_observed=observed,
            bars_inserted=inserted,
            bars_unchanged=unchanged,
            already_succeeded=False,
        )
        metadata = asdict(metrics)
        metadata.pop("ingestion_id")
        metadata.pop("version")
        metadata.pop("already_succeeded")
        metadata["universe_membership_mode"] = (
            "point_in_time" if point_in_time_universe else "fixed_snapshot"
        )
        metadata["universe_snapshot_ids"] = snapshot_ids
        with connection:
            connection.execute(
                """
                UPDATE data_ingestions
                SET completed_at = CURRENT_TIMESTAMP, status = 'succeeded',
                    request_count = ?, row_count = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    len(chunks),
                    observed,
                    json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                    ingestion_id,
                ),
            )
        return metrics
    except Exception as error:
        with connection:
            connection.execute(
                """
                UPDATE data_ingestions
                SET completed_at = CURRENT_TIMESTAMP, status = 'failed', error = ?,
                    request_count = ?, row_count = ?
                WHERE id = ?
                """,
                (str(error)[:2000], attempted, observed, ingestion_id),
            )
        raise


def _universe_symbols(
    connection: sqlite3.Connection, universe_snapshot_id: int
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT instruments.symbol
        FROM universe_memberships
        JOIN instruments ON instruments.id = universe_memberships.instrument_id
        WHERE universe_memberships.snapshot_id = ?
        ORDER BY instruments.symbol
        """,
        (universe_snapshot_id,),
    ).fetchall()
    symbols = tuple(str(row["symbol"]) for row in rows)
    if not symbols:
        raise ValueError("historical backfill universe snapshot has no members")
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
    iterator = iter(values)
    while chunk := tuple(islice(iterator, size)):
        yield chunk
