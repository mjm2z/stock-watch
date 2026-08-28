"""Restart-safe historical news ingestion for point-in-time research."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import islice
from typing import Iterator, Protocol, Sequence

from .ingestion import persist_news_articles
from .providers.alpaca import NewsArticle
from .sentiment import MODEL_VERSION
from .universe import load_universe_timeline


class HistoricalNewsProvider(Protocol):
    def get_news(
        self,
        *,
        start: str,
        end: str,
        symbols: Sequence[str] = (),
        include_content: bool = False,
    ) -> list[NewsArticle]: ...


@dataclass(frozen=True, slots=True)
class HistoricalNewsBackfillResult:
    ingestion_id: int
    version: str
    symbols: int
    logical_requests: int
    articles_observed: int
    articles_inserted: int
    articles_unchanged: int
    unknown_symbols: tuple[str, ...]
    already_succeeded: bool


def backfill_historical_news(
    connection: sqlite3.Connection,
    *,
    provider: HistoricalNewsProvider,
    universe_snapshot_id: int,
    start: date,
    end: date,
    symbol_chunk_size: int = 50,
    window_days: int = 7,
    point_in_time_universe: bool = False,
) -> HistoricalNewsBackfillResult:
    if start > end:
        raise ValueError("historical news start must not be after end")
    if symbol_chunk_size < 1 or symbol_chunk_size > 200:
        raise ValueError("historical news symbol chunk size must be between 1 and 200")
    if window_days < 1 or window_days > 31:
        raise ValueError("historical news window days must be between 1 and 31")

    if point_in_time_universe:
        timeline = load_universe_timeline(
            connection,
            anchor_snapshot_id=universe_snapshot_id,
            start=start,
            end=end,
        )
        symbols = tuple(sorted({symbol for item in timeline for symbol in item.members}))
        timeline_identity = [
            (item.snapshot_id, item.effective_at, item.content_sha256)
            for item in timeline
        ]
        membership_mode = "point_in_time"
    else:
        symbols = _universe_symbols(connection, universe_snapshot_id)
        timeline_identity = [(universe_snapshot_id,)]
        membership_mode = "fixed_snapshot"
    symbols_sha256 = hashlib.sha256("\n".join(symbols).encode("utf-8")).hexdigest()
    identity = json.dumps(
        {
            "end": end.isoformat(),
            "membership": timeline_identity,
            "sentiment_model": MODEL_VERSION,
            "start": start.isoformat(),
            "symbol_chunk_size": symbol_chunk_size,
            "symbols_sha256": symbols_sha256,
            "window_days": window_days,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    version = "historical-news-v1:" + hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()
    existing = connection.execute(
        """
        SELECT id, status, metadata_json FROM data_ingestions
        WHERE dataset = 'historical_news' AND provider = 'alpaca' AND version = ?
        """,
        (version,),
    ).fetchone()
    if existing is not None and existing["status"] == "succeeded":
        return _stored_result(existing, version)

    metadata_base = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "symbol_list": list(symbols),
        "symbol_count": len(symbols),
        "symbols_sha256": symbols_sha256,
        "universe_membership_mode": membership_mode,
        "universe_snapshot_ids": [value[0] for value in timeline_identity],
        "window_days": window_days,
        "symbol_chunk_size": symbol_chunk_size,
        "sentiment_model": MODEL_VERSION,
        "news_coverage_complete": False,
    }
    with connection:
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO data_ingestions(
                    dataset, provider, started_at, status, version, metadata_json
                ) VALUES ('historical_news', 'alpaca', CURRENT_TIMESTAMP,
                          'running', ?, ?)
                """,
                (version, _canonical_json(metadata_base)),
            )
            ingestion_id = int(cursor.lastrowid)
        else:
            ingestion_id = int(existing["id"])
            connection.execute(
                """
                UPDATE data_ingestions
                SET started_at = CURRENT_TIMESTAMP, completed_at = NULL,
                    status = 'running', error = NULL, metadata_json = ?
                WHERE id = ?
                """,
                (_canonical_json(metadata_base), ingestion_id),
            )

    chunks = tuple(_chunks(symbols, symbol_chunk_size))
    windows = tuple(_windows(start, end, window_days))
    observed = inserted = unchanged = attempted = 0
    unknown: set[str] = set()
    try:
        for window_start, window_end in windows:
            for chunk in chunks:
                attempted += 1
                articles = provider.get_news(
                    start=_utc_iso(window_start),
                    end=_utc_iso(window_end),
                    symbols=chunk,
                    include_content=False,
                )
                result = persist_news_articles(
                    connection,
                    articles,
                    provider="alpaca",
                    ingestion_id=ingestion_id,
                )
                observed += len(articles)
                inserted += result.inserted
                unchanged += result.unchanged
                unknown.update(result.skipped_unknown_symbols)
        metrics = HistoricalNewsBackfillResult(
            ingestion_id=ingestion_id,
            version=version,
            symbols=len(symbols),
            logical_requests=len(chunks) * len(windows),
            articles_observed=observed,
            articles_inserted=inserted,
            articles_unchanged=unchanged,
            unknown_symbols=tuple(sorted(unknown)),
            already_succeeded=False,
        )
        metadata = {**metadata_base, **asdict(metrics)}
        for key in ("ingestion_id", "version", "already_succeeded"):
            metadata.pop(key)
        metadata["news_coverage_complete"] = True
        with connection:
            connection.execute(
                """
                UPDATE data_ingestions
                SET completed_at = CURRENT_TIMESTAMP, status = 'succeeded',
                    request_count = ?, row_count = ?, metadata_json = ?
                WHERE id = ?
                """,
                (attempted, observed, _canonical_json(metadata), ingestion_id),
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


def _stored_result(row: sqlite3.Row, version: str) -> HistoricalNewsBackfillResult:
    metadata = json.loads(str(row["metadata_json"]))
    return HistoricalNewsBackfillResult(
        ingestion_id=int(row["id"]),
        version=version,
        symbols=int(metadata["symbol_count"]),
        logical_requests=int(metadata["logical_requests"]),
        articles_observed=int(metadata["articles_observed"]),
        articles_inserted=int(metadata["articles_inserted"]),
        articles_unchanged=int(metadata["articles_unchanged"]),
        unknown_symbols=tuple(str(value) for value in metadata["unknown_symbols"]),
        already_succeeded=True,
    )


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
        raise ValueError("historical news universe snapshot has no members")
    return symbols


def _windows(
    start: date, end: date, window_days: int
) -> Iterator[tuple[datetime, datetime]]:
    current = datetime.combine(start, time.min, tzinfo=timezone.utc)
    exclusive_end = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    while current < exclusive_end:
        next_window = min(current + timedelta(days=window_days), exclusive_end)
        yield current, next_window - timedelta(microseconds=1)
        current = next_window


def _chunks(values: Sequence[str], size: int) -> Iterator[tuple[str, ...]]:
    iterator = iter(values)
    while chunk := tuple(islice(iterator, size)):
        yield chunk


def _utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
