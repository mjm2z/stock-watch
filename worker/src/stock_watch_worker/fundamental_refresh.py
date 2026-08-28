"""Rate-limited refresh policy for cached SEC CompanyFacts documents."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .http import ProviderError
from .ingestion import persist_company_facts
from .providers.sec import SecClient


@dataclass(frozen=True, slots=True)
class FundamentalRefreshResult:
    refreshed: int
    skipped_fresh: int
    missing_cik: tuple[str, ...]
    unavailable: tuple[str, ...]


class FundamentalRefreshError(RuntimeError):
    """Add the affected security and progress position to a refresh failure."""


def refresh_company_facts(
    connection: sqlite3.Connection,
    *,
    sec: SecClient,
    universe_snapshot_id: int,
    now: datetime,
    maximum_age: timedelta = timedelta(hours=24),
    progress: Callable[[int, int, str], None] | None = None,
) -> FundamentalRefreshResult:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone aware")
    if maximum_age <= timedelta(0):
        raise ValueError("maximum_age must be positive")
    rows = connection.execute(
        """
        SELECT instruments.id, instruments.symbol, instruments.cik,
               MAX(documents.captured_at) AS latest_capture
        FROM universe_memberships
        JOIN instruments ON instruments.id = universe_memberships.instrument_id
        LEFT JOIN company_fact_documents AS documents
            ON documents.instrument_id = instruments.id
        WHERE universe_memberships.snapshot_id = ?
        GROUP BY instruments.id, instruments.symbol, instruments.cik
        ORDER BY instruments.symbol
        """,
        (universe_snapshot_id,),
    ).fetchall()
    if not rows:
        raise ValueError("universe snapshot has no members")

    refreshed = 0
    skipped = 0
    missing_cik: list[str] = []
    unavailable: list[str] = []
    captured_at = _utc_iso(now)
    total = len(rows)
    if progress is not None:
        progress(0, total, f"starting SEC CompanyFacts refresh for {total} symbols")
    for index, row in enumerate(rows, start=1):
        symbol = str(row["symbol"])
        cik = row["cik"]
        if cik is None or not str(cik).strip():
            missing_cik.append(symbol)
            _report_progress(
                progress, index, total, symbol, refreshed, skipped, unavailable
            )
            continue
        latest = row["latest_capture"]
        if latest is not None and now.astimezone(timezone.utc) - _parse_timestamp(
            str(latest)
        ) < maximum_age:
            skipped += 1
            _report_progress(
                progress, index, total, symbol, refreshed, skipped, unavailable
            )
            continue
        try:
            facts = sec.get_company_facts(str(cik))
            persist_company_facts(
                connection,
                symbol=symbol,
                captured_at=captured_at,
                company_facts=facts,
            )
            refreshed += 1
        except ProviderError as error:
            if error.retryable:
                raise FundamentalRefreshError(
                    f"SEC CompanyFacts refresh failed for {symbol} "
                    f"(CIK {cik}) at {index}/{total}"
                ) from error
            unavailable.append(symbol)
        except Exception as error:
            raise FundamentalRefreshError(
                f"SEC CompanyFacts refresh failed for {symbol} "
                f"(CIK {cik}) at {index}/{total}"
            ) from error
        _report_progress(
            progress, index, total, symbol, refreshed, skipped, unavailable
        )
    return FundamentalRefreshResult(
        refreshed=refreshed,
        skipped_fresh=skipped,
        missing_cik=tuple(missing_cik),
        unavailable=tuple(unavailable),
    )


def _report_progress(
    progress: Callable[[int, int, str], None] | None,
    current: int,
    total: int,
    symbol: str,
    refreshed: int,
    skipped: int,
    unavailable: list[str],
) -> None:
    if progress is None or (current != total and current % 10 != 0):
        return
    progress(
        current,
        total,
        f"processed {current}/{total} through {symbol}; refreshed={refreshed} "
        f"fresh={skipped} unavailable={len(unavailable)}",
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CompanyFacts capture timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
