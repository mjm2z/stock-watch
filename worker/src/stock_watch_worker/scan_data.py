"""Point-in-time loading of cached inputs for a durable scan run."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Mapping
from zoneinfo import ZoneInfo

from .features import DailyBar, FundamentalInputs
from .sec_fundamentals import extract_fundamentals


NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class CandidateData:
    instrument_id: int
    symbol: str
    bars: tuple[DailyBar, ...]
    fundamentals: FundamentalInputs | None
    news_sentiments: tuple[float, ...]
    news_coverage_complete: bool
    source_refs: Mapping[str, object]
    vetoes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScanInputs:
    scan_run_id: str
    scan_type: str
    data_cutoff: str
    spy_bars: tuple[DailyBar, ...]
    candidates: tuple[CandidateData, ...]


def load_scan_inputs(
    connection: sqlite3.Connection,
    *,
    scan_run_id: str,
    news_coverage_complete: bool,
    news_lookback: timedelta = timedelta(days=3),
    history_sessions: int = 260,
) -> ScanInputs:
    if news_lookback <= timedelta(0):
        raise ValueError("news_lookback must be positive")
    if history_sessions < 200:
        raise ValueError("at least 200 history sessions are required")
    scan = connection.execute(
        """
        SELECT id, universe_snapshot_id, scan_type, scheduled_for, data_cutoff
        FROM scan_runs WHERE id = ?
        """,
        (scan_run_id,),
    ).fetchone()
    if scan is None:
        raise ValueError("scan run does not exist")
    if scan["scan_type"] not in {"open", "close", "manual"}:
        raise ValueError("scan input loading only supports live or manual scans")
    cutoff = _parse_timestamp(str(scan["data_cutoff"]))
    market_date = _parse_timestamp(str(scan["scheduled_for"])).astimezone(NEW_YORK).date()

    member_rows = connection.execute(
        """
        SELECT instruments.id, instruments.symbol, instruments.active,
               instruments.fractionable
        FROM universe_memberships
        JOIN instruments ON instruments.id = universe_memberships.instrument_id
        WHERE universe_memberships.snapshot_id = ?
        ORDER BY instruments.symbol
        """,
        (scan["universe_snapshot_id"],),
    ).fetchall()
    if not member_rows:
        raise ValueError("scan universe snapshot has no members")
    spy = connection.execute(
        "SELECT id FROM instruments WHERE symbol = 'SPY' AND asset_class = 'us_equity'"
    ).fetchone()
    if spy is None:
        raise ValueError("SPY benchmark instrument is missing")

    member_ids = [int(row["id"]) for row in member_rows]
    all_ids = tuple(sorted(set(member_ids) | {int(spy["id"])}))
    bars_by_instrument = _load_bars(
        connection,
        instrument_ids=all_ids,
        cutoff=str(scan["data_cutoff"]),
        market_date=market_date,
        include_market_date=scan["scan_type"] != "open",
        history_sessions=history_sessions,
    )
    facts_by_instrument = _load_company_facts(
        connection,
        instrument_ids=tuple(member_ids),
        cutoff=str(scan["data_cutoff"]),
    )
    news_by_instrument, news_refs = _load_news(
        connection,
        instrument_ids=tuple(member_ids),
        start=cutoff - news_lookback,
        cutoff=cutoff,
    )

    candidates: list[CandidateData] = []
    for row in member_rows:
        instrument_id = int(row["id"])
        symbol = str(row["symbol"])
        bars = bars_by_instrument.get(instrument_id, ())
        fundamentals: FundamentalInputs | None = None
        vetoes: list[str] = []
        fact_document = facts_by_instrument.get(instrument_id)
        fact_refs: dict[str, object] = {}
        if fact_document is not None and bars:
            try:
                extracted = extract_fundamentals(
                    fact_document["facts"],
                    as_of=str(scan["data_cutoff"]),
                    price=bars[-1].close,
                )
                fundamentals = extracted.inputs
                fact_refs = {
                    "company_facts_document_id": fact_document["id"],
                    "company_facts_sha256": fact_document["sha256"],
                    "sec_accessions": list(extracted.accessions),
                }
            except (TypeError, ValueError):
                vetoes.append("fundamental_parse_error")
        if not bool(row["active"]):
            vetoes.append("instrument_inactive")
        if row["fractionable"] != 1:
            vetoes.append("instrument_not_fractionable")
        candidates.append(
            CandidateData(
                instrument_id=instrument_id,
                symbol=symbol,
                bars=bars,
                fundamentals=fundamentals,
                news_sentiments=news_by_instrument.get(instrument_id, ()),
                news_coverage_complete=news_coverage_complete,
                source_refs={
                    "market_bar_provider": "alpaca",
                    "market_bar_count": len(bars),
                    **fact_refs,
                    "news_ids": list(news_refs.get(instrument_id, ())),
                },
                vetoes=tuple(vetoes),
            )
        )

    return ScanInputs(
        scan_run_id=str(scan["id"]),
        scan_type=str(scan["scan_type"]),
        data_cutoff=str(scan["data_cutoff"]),
        spy_bars=bars_by_instrument.get(int(spy["id"]), ()),
        candidates=tuple(candidates),
    )


def _load_bars(
    connection: sqlite3.Connection,
    *,
    instrument_ids: tuple[int, ...],
    cutoff: str,
    market_date: date,
    include_market_date: bool,
    history_sessions: int,
) -> dict[int, tuple[DailyBar, ...]]:
    placeholders = ",".join("?" for _ in instrument_ids)
    rows = connection.execute(
        f"""
        SELECT instrument_id, timestamp, open, high, low, close, volume
        FROM market_bars
        WHERE instrument_id IN ({placeholders})
          AND timeframe = '1Day' AND adjustment = 'all'
          AND provider = 'alpaca' AND timestamp <= ?
        ORDER BY instrument_id, timestamp
        """,
        (*instrument_ids, cutoff),
    ).fetchall()
    grouped: dict[int, list[DailyBar]] = {}
    for row in rows:
        session = _session_date(str(row["timestamp"]))
        if session > market_date or (session == market_date and not include_market_date):
            continue
        grouped.setdefault(int(row["instrument_id"]), []).append(
            DailyBar(
                session=session.isoformat(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return {
        instrument_id: tuple(values[-history_sessions:])
        for instrument_id, values in grouped.items()
    }


def _load_company_facts(
    connection: sqlite3.Connection,
    *,
    instrument_ids: tuple[int, ...],
    cutoff: str,
) -> dict[int, dict[str, object]]:
    placeholders = ",".join("?" for _ in instrument_ids)
    rows = connection.execute(
        f"""
        SELECT id, instrument_id, content_sha256, facts_json
        FROM company_fact_documents
        WHERE instrument_id IN ({placeholders}) AND captured_at <= ?
        ORDER BY instrument_id, captured_at DESC, id DESC
        """,
        (*instrument_ids, cutoff),
    ).fetchall()
    result: dict[int, dict[str, object]] = {}
    for row in rows:
        instrument_id = int(row["instrument_id"])
        if instrument_id in result:
            continue
        facts = json.loads(str(row["facts_json"]))
        if isinstance(facts, dict):
            result[instrument_id] = {
                "id": int(row["id"]),
                "sha256": str(row["content_sha256"]),
                "facts": facts,
            }
    return result


def _load_news(
    connection: sqlite3.Connection,
    *,
    instrument_ids: tuple[int, ...],
    start: datetime,
    cutoff: datetime,
) -> tuple[dict[int, tuple[float, ...]], dict[int, tuple[str, ...]]]:
    placeholders = ",".join("?" for _ in instrument_ids)
    rows = connection.execute(
        f"""
        SELECT links.instrument_id, links.sentiment, articles.id
        FROM news_instruments AS links
        JOIN news_articles AS articles ON articles.id = links.news_id
        WHERE links.instrument_id IN ({placeholders})
          AND articles.published_at >= ? AND articles.published_at <= ?
          AND links.sentiment IS NOT NULL
        ORDER BY links.instrument_id, articles.published_at, articles.id
        """,
        (*instrument_ids, _utc_iso(start), _utc_iso(cutoff)),
    ).fetchall()
    sentiments: dict[int, list[float]] = {}
    refs: dict[int, list[str]] = {}
    for row in rows:
        instrument_id = int(row["instrument_id"])
        sentiments.setdefault(instrument_id, []).append(float(row["sentiment"]))
        refs.setdefault(instrument_id, []).append(str(row["id"]))
    return (
        {key: tuple(values) for key, values in sentiments.items()},
        {key: tuple(values) for key, values in refs.items()},
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("scan timestamps must include a timezone")
    return parsed


def _session_date(value: str) -> date:
    if len(value) == 10:
        return date.fromisoformat(value)
    return _parse_timestamp(value).astimezone(NEW_YORK).date()


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
