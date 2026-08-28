"""Contribution-aware paper portfolio and SPY benchmark snapshots."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence
from zoneinfo import ZoneInfo

from .market_calendar import utc_iso


NEW_YORK = ZoneInfo("America/New_York")
METHODOLOGY = "fill_cohort_contribution_adjusted_v1"


@dataclass(frozen=True, slots=True)
class ValuationBar:
    session: date
    open: float
    close: float


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotResult:
    observed_at: str
    inserted: bool
    filled_lots: int
    contributed_capital: float
    cash: float
    market_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    spy_value: float | None
    price_fallback_lots: tuple[str, ...]
    benchmark_missing_lots: tuple[str, ...]


def record_portfolio_snapshot(
    connection: sqlite3.Connection,
    *,
    observed_at: datetime,
    provider: str = "alpaca",
) -> PortfolioSnapshotResult:
    """Value every filled lot and a cash-flow-matched SPY cohort benchmark.

    Each lot contributes its actual entry quantity times fill price. Closed or
    partially exited shares become cash; remaining shares use the latest stored
    adjusted close. The SPY cohort receives the same contribution on the lot's
    entry session and realizes the same exited fraction on the fill session.
    """

    observed_timestamp = utc_iso(observed_at)
    if not provider.strip():
        raise ValueError("portfolio valuation provider is required")
    lots = connection.execute(
        """
        SELECT lots.id, lots.instrument_id, lots.status, lots.opened_at,
               lots.closed_at, lots.entry_quantity, lots.entry_price,
               lots.exit_quantity, lots.exit_price,
               (
                   SELECT fills.filled_at
                   FROM paper_exit_orders AS exits
                   JOIN paper_exit_fills AS fills ON fills.exit_order_id = exits.id
                   WHERE exits.lot_id = lots.id
                   ORDER BY fills.filled_at DESC LIMIT 1
               ) AS exit_filled_at
        FROM paper_trade_lots AS lots
        WHERE lots.opened_at IS NOT NULL
          AND lots.entry_quantity IS NOT NULL
          AND lots.entry_price IS NOT NULL
          AND lots.status IN ('open', 'closing', 'closed')
        ORDER BY lots.opened_at, lots.id
        """
    ).fetchall()
    spy = connection.execute(
        "SELECT id FROM instruments WHERE symbol = 'SPY' AND asset_class = 'us_equity'"
    ).fetchone()
    if lots and spy is None:
        raise ValueError("SPY benchmark instrument is missing")

    instrument_ids = {int(row["instrument_id"]) for row in lots}
    if spy is not None:
        instrument_ids.add(int(spy["id"]))
    bars = _load_bars(
        connection,
        instrument_ids=tuple(sorted(instrument_ids)),
        provider=provider,
        observed_at=observed_at,
    )
    spy_bars = bars.get(int(spy["id"]), ()) if spy is not None else ()
    spy_by_session = {bar.session: bar for bar in spy_bars}

    contributed = 0.0
    cash = 0.0
    market_value = 0.0
    realized_pnl = 0.0
    unrealized_pnl = 0.0
    spy_value = 0.0
    price_fallbacks: list[str] = []
    benchmark_missing: list[str] = []
    observed_date = observed_at.astimezone(NEW_YORK).date()

    for lot in lots:
        lot_id = str(lot["id"])
        entry_quantity = _positive("entry quantity", lot["entry_quantity"])
        entry_price = _positive("entry price", lot["entry_price"])
        entry_date = _timestamp_date(str(lot["opened_at"]))
        initial_value = entry_quantity * entry_price
        contributed += initial_value

        exited_quantity = _optional_nonnegative("exit quantity", lot["exit_quantity"])
        exit_price = _optional_positive("exit price", lot["exit_price"])
        if (exited_quantity is None) != (exit_price is None):
            raise ValueError(f"paper lot {lot_id} has incomplete exit economics")
        exited_quantity = exited_quantity or 0.0
        if exited_quantity > entry_quantity + 1e-9:
            raise ValueError(f"paper lot {lot_id} exits more shares than it entered")
        remaining_quantity = max(0.0, entry_quantity - exited_quantity)
        if lot["status"] == "closed" and remaining_quantity > 1e-9:
            raise ValueError(f"closed paper lot {lot_id} retains an open quantity")
        if exited_quantity:
            assert exit_price is not None
            proceeds = exited_quantity * exit_price
            cash += proceeds
            realized_pnl += exited_quantity * (exit_price - entry_price)

        current_price = entry_price
        if remaining_quantity:
            current_bar = _latest_bar_on_or_after(
                bars.get(int(lot["instrument_id"]), ()),
                start=entry_date,
                end=observed_date,
            )
            if current_bar is None:
                price_fallbacks.append(lot_id)
            else:
                current_price = current_bar.close
            market_value += remaining_quantity * current_price
            unrealized_pnl += remaining_quantity * (current_price - entry_price)

        entry_spy = spy_by_session.get(entry_date)
        if entry_spy is None:
            benchmark_missing.append(lot_id)
            continue
        spy_quantity = initial_value / entry_spy.open
        exited_fraction = exited_quantity / entry_quantity
        if exited_fraction:
            exit_timestamp = lot["closed_at"] or lot["exit_filled_at"]
            if exit_timestamp is None:
                benchmark_missing.append(lot_id)
                continue
            exit_spy = spy_by_session.get(_timestamp_date(str(exit_timestamp)))
            if exit_spy is None:
                benchmark_missing.append(lot_id)
                continue
            spy_value += spy_quantity * exited_fraction * exit_spy.open
        remaining_fraction = 1.0 - exited_fraction
        if remaining_fraction:
            current_spy = _latest_bar_on_or_after(
                spy_bars,
                start=entry_date,
                end=observed_date,
            )
            if current_spy is None:
                benchmark_missing.append(lot_id)
                continue
            spy_value += spy_quantity * remaining_fraction * current_spy.close

    benchmark_value = None if benchmark_missing else spy_value
    equity = cash + market_value
    raw = json.dumps(
        {
            "benchmark_complete": not benchmark_missing,
            "benchmark_missing_lots": sorted(set(benchmark_missing)),
            "filled_lots": len(lots),
            "methodology": METHODOLOGY,
            "price_fallback_lots": sorted(set(price_fallbacks)),
            "provider": provider,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    values = (
        cash,
        market_value,
        equity,
        market_value,
        realized_pnl,
        unrealized_pnl,
        benchmark_value,
        contributed,
        f"paper_fills+{provider}_adjusted_all",
        raw,
    )
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO portfolio_snapshots(
                observed_at, cash, market_value, equity, gross_exposure,
                realized_pnl, unrealized_pnl, spy_value,
                contributed_capital, source, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(observed_at) DO NOTHING
            """,
            (observed_timestamp, *values),
        )
    inserted = cursor.rowcount == 1
    if not inserted:
        existing = connection.execute(
            """
            SELECT cash, market_value, equity, gross_exposure, realized_pnl,
                   unrealized_pnl, spy_value, contributed_capital, source, raw_json
            FROM portfolio_snapshots WHERE observed_at = ?
            """,
            (observed_timestamp,),
        ).fetchone()
        if existing is None or not _same_snapshot(existing, values):
            raise ValueError("immutable portfolio snapshot conflicts with current valuation")
    return PortfolioSnapshotResult(
        observed_at=observed_timestamp,
        inserted=inserted,
        filled_lots=len(lots),
        contributed_capital=contributed,
        cash=cash,
        market_value=market_value,
        equity=equity,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        spy_value=benchmark_value,
        price_fallback_lots=tuple(sorted(set(price_fallbacks))),
        benchmark_missing_lots=tuple(sorted(set(benchmark_missing))),
    )


def _load_bars(
    connection: sqlite3.Connection,
    *,
    instrument_ids: Sequence[int],
    provider: str,
    observed_at: datetime,
) -> dict[int, tuple[ValuationBar, ...]]:
    if not instrument_ids:
        return {}
    placeholders = ",".join("?" for _ in instrument_ids)
    rows = connection.execute(
        f"""
        SELECT instrument_id, timestamp, open, close
        FROM market_bars
        WHERE instrument_id IN ({placeholders})
          AND timeframe = '1Day' AND adjustment = 'all' AND provider = ?
        ORDER BY instrument_id, timestamp
        """,
        (*instrument_ids, provider),
    ).fetchall()
    observed_date = observed_at.astimezone(NEW_YORK).date()
    grouped: dict[int, list[ValuationBar]] = {}
    seen: set[tuple[int, date]] = set()
    for row in rows:
        session = _timestamp_date(str(row["timestamp"]))
        if session > observed_date:
            continue
        key = (int(row["instrument_id"]), session)
        if key in seen:
            raise ValueError("portfolio market history contains duplicate sessions")
        seen.add(key)
        open_price = _positive("bar open", row["open"])
        close_price = _positive("bar close", row["close"])
        grouped.setdefault(key[0], []).append(
            ValuationBar(session=session, open=open_price, close=close_price)
        )
    return {key: tuple(value) for key, value in grouped.items()}


def _latest_bar_on_or_after(
    bars: Sequence[ValuationBar], *, start: date, end: date
) -> ValuationBar | None:
    eligible = [bar for bar in bars if start <= bar.session <= end]
    return eligible[-1] if eligible else None


def _timestamp_date(value: str) -> date:
    if len(value) == 10:
        return date.fromisoformat(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("portfolio timestamp must include a timezone")
    return parsed.astimezone(NEW_YORK).date()


def _positive(name: str, value: object) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _optional_positive(name: str, value: object) -> float | None:
    return None if value is None else _positive(name, value)


def _optional_nonnegative(name: str, value: object) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} cannot be negative")
    return parsed


def _same_snapshot(row: sqlite3.Row, values: tuple[object, ...]) -> bool:
    numeric_names = (
        "cash",
        "market_value",
        "equity",
        "gross_exposure",
        "realized_pnl",
        "unrealized_pnl",
        "spy_value",
        "contributed_capital",
    )
    for name, expected in zip(numeric_names, values[:8], strict=True):
        actual = row[name]
        if actual is None or expected is None:
            if actual is not expected:
                return False
        elif not math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12):
            return False
    return row["source"] == values[8] and row["raw_json"] == values[9]
