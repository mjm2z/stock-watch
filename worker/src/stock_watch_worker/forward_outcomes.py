"""Persist bias-resistant forward outcomes for qualified live signals."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Sequence
from zoneinfo import ZoneInfo

from .features import DailyBar
from .market_calendar import utc_iso
from .outcomes import calculate_outcome


NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_DATASET_VERSION = "alpaca-iex-1day-adjusted-all-v1"


@dataclass(frozen=True, slots=True)
class ForwardOutcomeResult:
    candidates: int
    completed: int
    pending_history: int
    missing_history: int


def evaluate_forward_outcomes(
    connection: sqlite3.Connection,
    *,
    observed_at: datetime,
    round_trip_cost_bps: float = 10.0,
    provider: str = "alpaca",
    dataset_version: str = DEFAULT_DATASET_VERSION,
) -> ForwardOutcomeResult:
    """Evaluate qualified signals at a next-session-open, horizon-close window.

    Using the first session after the scan for both opening and closing signals
    avoids pretending that a completed daily bar supplied a tradable 09:45
    price. Paper fills remain the authoritative execution-performance record.
    """

    observed_timestamp = utc_iso(observed_at)
    if round_trip_cost_bps < 0:
        raise ValueError("round_trip_cost_bps cannot be negative")
    if not provider.strip() or not dataset_version.strip():
        raise ValueError("outcome provider and dataset version are required")

    rows = connection.execute(
        """
        SELECT signals.id, signals.instrument_id,
               signals.horizon_trading_days, scans.scheduled_for
        FROM signals
        JOIN scan_runs AS scans ON scans.id = signals.scan_run_id
        WHERE signals.decision = 'qualified'
          AND scans.scan_type IN ('open', 'close', 'manual')
          AND NOT EXISTS (
              SELECT 1 FROM signal_outcomes AS outcomes
              WHERE outcomes.signal_id = signals.id
                AND outcomes.horizon_trading_days = signals.horizon_trading_days
          )
        ORDER BY signals.as_of, signals.id
        """
    ).fetchall()
    if not rows:
        return ForwardOutcomeResult(0, 0, 0, 0)

    spy = connection.execute(
        "SELECT id FROM instruments WHERE symbol = 'SPY' AND asset_class = 'us_equity'"
    ).fetchone()
    if spy is None:
        raise ValueError("SPY benchmark instrument is missing")
    instrument_ids = tuple(
        sorted({int(row["instrument_id"]) for row in rows} | {int(spy["id"])})
    )
    bars_by_instrument = _load_daily_bars(
        connection,
        instrument_ids=instrument_ids,
        provider=provider,
        observed_at=observed_at,
    )
    spy_bars = bars_by_instrument.get(int(spy["id"]), ())
    if not spy_bars:
        raise ValueError("SPY benchmark history is missing")
    spy_by_session = {bar.session: bar for bar in spy_bars}
    spy_sessions = tuple(bar.session for bar in spy_bars)

    completed = 0
    pending = 0
    missing = 0
    for row in rows:
        stock_bars = bars_by_instrument.get(int(row["instrument_id"]), ())
        if not stock_bars:
            missing += 1
            continue
        signal_session = _market_date(str(row["scheduled_for"])).isoformat()
        entry_index = _first_session_after(spy_sessions, signal_session)
        if entry_index is None:
            pending += 1
            continue
        exit_index = entry_index + int(row["horizon_trading_days"]) - 1
        if exit_index >= len(spy_sessions):
            pending += 1
            continue
        window_sessions = spy_sessions[entry_index : exit_index + 1]
        stock_by_session = {bar.session: bar for bar in stock_bars}
        if any(session not in stock_by_session for session in window_sessions):
            missing += 1
            continue
        stock_window = tuple(stock_by_session[session] for session in window_sessions)
        spy_entry = spy_by_session[window_sessions[0]]
        spy_exit = spy_by_session[window_sessions[-1]]
        outcome = calculate_outcome(
            entry_price=stock_window[0].open,
            terminal_price=stock_window[-1].close,
            observed_highs=[bar.high for bar in stock_window],
            observed_lows=[bar.low for bar in stock_window],
            spy_entry_price=spy_entry.open,
            spy_terminal_price=spy_exit.close,
            round_trip_cost_bps=round_trip_cost_bps,
        )
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO signal_outcomes(
                    signal_id, horizon_trading_days, observed_at,
                    entry_price, terminal_price, gross_return,
                    modeled_cost_return, net_return, terminal_positive,
                    terminal_at_least_5, terminal_at_least_10,
                    touched_5, touched_10, spy_return, excess_return,
                    beat_spy, maximum_favorable_excursion,
                    maximum_adverse_excursion, provider, dataset_version,
                    entry_session, exit_session
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(signal_id, horizon_trading_days) DO NOTHING
                """,
                (
                    row["id"],
                    row["horizon_trading_days"],
                    observed_timestamp,
                    outcome.entry_price,
                    outcome.terminal_price,
                    outcome.gross_return,
                    outcome.modeled_cost_return,
                    outcome.net_return,
                    int(outcome.terminal_positive),
                    int(outcome.terminal_at_least_5),
                    int(outcome.terminal_at_least_10),
                    int(outcome.touched_5),
                    int(outcome.touched_10),
                    outcome.spy_return,
                    outcome.excess_return,
                    int(outcome.beat_spy),
                    outcome.maximum_favorable_excursion,
                    outcome.maximum_adverse_excursion,
                    provider,
                    dataset_version,
                    window_sessions[0],
                    window_sessions[-1],
                ),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    INSERT INTO audit_events(
                        event_type, entity_type, entity_id, payload_json
                    ) VALUES ('signal_outcome_completed', 'signal', ?, ?)
                    """,
                    (
                        row["id"],
                        json.dumps(
                            {
                                "beat_spy": outcome.beat_spy,
                                "entry_session": window_sessions[0],
                                "exit_session": window_sessions[-1],
                                "net_return": outcome.net_return,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                )
        completed += int(cursor.rowcount == 1)
    return ForwardOutcomeResult(
        candidates=len(rows),
        completed=completed,
        pending_history=pending,
        missing_history=missing,
    )


def _load_daily_bars(
    connection: sqlite3.Connection,
    *,
    instrument_ids: Sequence[int],
    provider: str,
    observed_at: datetime,
) -> dict[int, tuple[DailyBar, ...]]:
    placeholders = ",".join("?" for _ in instrument_ids)
    rows = connection.execute(
        f"""
        SELECT instrument_id, timestamp, open, high, low, close, volume
        FROM market_bars
        WHERE instrument_id IN ({placeholders})
          AND timeframe = '1Day' AND adjustment = 'all' AND provider = ?
        ORDER BY instrument_id, timestamp
        """,
        (*instrument_ids, provider),
    ).fetchall()
    observed_date = observed_at.astimezone(NEW_YORK).date()
    grouped: dict[int, list[DailyBar]] = {}
    seen: set[tuple[int, str]] = set()
    for row in rows:
        session = _market_date(str(row["timestamp"]))
        if session > observed_date:
            continue
        key = (int(row["instrument_id"]), session.isoformat())
        if key in seen:
            raise ValueError("daily market history contains duplicate sessions")
        seen.add(key)
        grouped.setdefault(key[0], []).append(
            DailyBar(
                session=key[1],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _first_session_after(sessions: Sequence[str], signal_session: str) -> int | None:
    return next(
        (index for index, session in enumerate(sessions) if session > signal_session),
        None,
    )


def _market_date(value: str) -> date:
    if len(value) == 10:
        return date.fromisoformat(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("market timestamp must include a timezone")
    return parsed.astimezone(NEW_YORK).date()
