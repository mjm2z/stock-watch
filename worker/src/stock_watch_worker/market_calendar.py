"""US equity market sessions and scan-window calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class MarketSession:
    trading_date: date
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.opens_at)
        _require_aware(self.closes_at)
        if self.closes_at <= self.opens_at:
            raise ValueError("market close must be after market open")
        if self.opens_at.astimezone(NEW_YORK).date() != self.trading_date:
            raise ValueError("market open does not match trading_date")

    @classmethod
    def from_alpaca(cls, value: Mapping[str, Any]) -> "MarketSession":
        try:
            trading_date = date.fromisoformat(str(value["date"]))
            open_time = time.fromisoformat(str(value["open"]))
            close_time = time.fromisoformat(str(value["close"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Alpaca calendar session is malformed") from error
        return cls(
            trading_date=trading_date,
            opens_at=datetime.combine(trading_date, open_time, NEW_YORK),
            closes_at=datetime.combine(trading_date, close_time, NEW_YORK),
        )


@dataclass(frozen=True, slots=True)
class ScanWindow:
    scan_type: str
    scheduled_for: datetime
    market_session: MarketSession

    def __post_init__(self) -> None:
        if self.scan_type not in {"open", "close"}:
            raise ValueError("scan_type must be open or close")
        _require_aware(self.scheduled_for)


def scan_windows(
    sessions: Sequence[MarketSession],
    *,
    opening_delay: timedelta = timedelta(minutes=15),
    closing_delay: timedelta = timedelta(minutes=15),
) -> tuple[ScanWindow, ...]:
    if opening_delay < timedelta(0) or closing_delay < timedelta(0):
        raise ValueError("scan delays cannot be negative")
    windows: list[ScanWindow] = []
    for session in sorted(sessions, key=lambda item: item.opens_at):
        windows.extend(
            (
                ScanWindow("open", session.opens_at + opening_delay, session),
                ScanWindow("close", session.closes_at + closing_delay, session),
            )
        )
    return tuple(windows)


def due_scan_windows(
    now: datetime,
    sessions: Sequence[MarketSession],
    *,
    grace_period: timedelta = timedelta(minutes=20),
) -> tuple[ScanWindow, ...]:
    """Return windows due now, with a bounded catch-up period after downtime."""

    _require_aware(now)
    if grace_period <= timedelta(0):
        raise ValueError("grace_period must be positive")
    now_utc = now.astimezone(UTC)
    return tuple(
        window
        for window in scan_windows(sessions)
        if window.scheduled_for.astimezone(UTC)
        <= now_utc
        < window.scheduled_for.astimezone(UTC) + grace_period
    )


def utc_iso(value: datetime) -> str:
    _require_aware(value)
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime is required")
