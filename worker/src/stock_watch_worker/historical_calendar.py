"""Durable exchange-session ingestion for point-in-time research cutoffs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Iterator, Protocol

from .market_calendar import MarketSession, utc_iso


class HistoricalCalendarProvider(Protocol):
    def get_market_calendar(
        self, *, start: date | str, end: date | str
    ) -> list[MarketSession]: ...


@dataclass(frozen=True, slots=True)
class HistoricalCalendarBackfillResult:
    ingestion_id: int
    version: str
    logical_requests: int
    sessions_observed: int
    sessions_inserted: int
    sessions_unchanged: int
    already_succeeded: bool


def backfill_historical_calendar(
    connection: sqlite3.Connection,
    *,
    provider: HistoricalCalendarProvider,
    start: date,
    end: date,
    window_days: int = 366,
) -> HistoricalCalendarBackfillResult:
    if start > end:
        raise ValueError("historical calendar start must not be after end")
    if window_days < 1 or window_days > 366:
        raise ValueError("historical calendar window days must be between 1 and 366")
    identity = json.dumps(
        {
            "end": end.isoformat(),
            "start": start.isoformat(),
            "window_days": window_days,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    version = "historical-calendar-v1:" + hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()
    existing = connection.execute(
        """
        SELECT id, status, metadata_json FROM data_ingestions
        WHERE dataset = 'historical_calendar'
          AND provider = 'alpaca-paper' AND version = ?
        """,
        (version,),
    ).fetchone()
    if existing is not None and existing["status"] == "succeeded":
        metadata = json.loads(str(existing["metadata_json"]))
        return HistoricalCalendarBackfillResult(
            ingestion_id=int(existing["id"]),
            version=version,
            logical_requests=int(metadata["logical_requests"]),
            sessions_observed=int(metadata["sessions_observed"]),
            sessions_inserted=int(metadata["sessions_inserted"]),
            sessions_unchanged=int(metadata["sessions_unchanged"]),
            already_succeeded=True,
        )

    metadata_base = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "window_days": window_days,
        "calendar_coverage_complete": False,
    }
    with connection:
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO data_ingestions(
                    dataset, provider, started_at, status, version, metadata_json
                ) VALUES ('historical_calendar', 'alpaca-paper', CURRENT_TIMESTAMP,
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

    observed = inserted = unchanged = attempted = 0
    seen_dates: set[date] = set()
    try:
        for window_start, window_end in _windows(start, end, window_days):
            attempted += 1
            sessions = provider.get_market_calendar(start=window_start, end=window_end)
            for session in sessions:
                if not window_start <= session.trading_date <= window_end:
                    raise ValueError("historical calendar provider returned an out-of-range session")
                if session.trading_date in seen_dates:
                    raise ValueError("historical calendar provider returned a duplicate session")
                seen_dates.add(session.trading_date)
                observed += 1
                values = (utc_iso(session.opens_at), utc_iso(session.closes_at))
                cursor = connection.execute(
                    """
                    INSERT INTO market_sessions(
                        trading_date, provider, opens_at, closes_at, ingestion_id
                    ) VALUES (?, 'alpaca-paper', ?, ?, ?)
                    ON CONFLICT(trading_date, provider) DO NOTHING
                    """,
                    (session.trading_date.isoformat(), *values, ingestion_id),
                )
                if cursor.rowcount == 1:
                    inserted += 1
                else:
                    stored = connection.execute(
                        """
                        SELECT opens_at, closes_at FROM market_sessions
                        WHERE trading_date = ? AND provider = 'alpaca-paper'
                        """,
                        (session.trading_date.isoformat(),),
                    ).fetchone()
                    if stored is None or tuple(stored) != values:
                        raise ValueError(
                            f"immutable market session changed: {session.trading_date}"
                        )
                    unchanged += 1
            connection.commit()
        metrics = HistoricalCalendarBackfillResult(
            ingestion_id=ingestion_id,
            version=version,
            logical_requests=attempted,
            sessions_observed=observed,
            sessions_inserted=inserted,
            sessions_unchanged=unchanged,
            already_succeeded=False,
        )
        metadata = {**metadata_base, **asdict(metrics)}
        for key in ("ingestion_id", "version", "already_succeeded"):
            metadata.pop(key)
        metadata["calendar_coverage_complete"] = True
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


def _windows(start: date, end: date, window_days: int) -> Iterator[tuple[date, date]]:
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=window_days - 1), end)
        yield current, window_end
        current = window_end + timedelta(days=1)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
