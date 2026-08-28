"""Fail-closed synchronization of a current universe from an approved CSV URL."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Sequence
from urllib.parse import urlsplit

from .http import HttpTransport, UrllibTransport
from .universe import (
    UniverseImportResult,
    UniverseMember,
    import_universe_snapshot_if_changed,
    read_members_csv_text,
)


MAXIMUM_CSV_BYTES = 2_000_000


@dataclass(frozen=True, slots=True)
class UniverseSyncResult:
    import_result: UniverseImportResult
    source: str
    source_url: str
    added_symbols: tuple[str, ...]
    removed_symbols: tuple[str, ...]
    cik_coverage: float


def sync_universe_from_latest_source(
    connection: sqlite3.Connection,
    *,
    universe: str,
    effective_at: str,
    minimum_members: int = 450,
    maximum_members: int = 550,
    minimum_cik_coverage: float = 0.95,
    maximum_symbol_churn: float = 0.10,
    transport: HttpTransport | None = None,
) -> UniverseSyncResult:
    """Download and validate the source recorded by the latest snapshot."""

    latest = connection.execute(
        """
        SELECT id, source, source_url
        FROM universe_snapshots
        WHERE universe = ?
        ORDER BY effective_at DESC, id DESC
        LIMIT 1
        """,
        (universe.strip(),),
    ).fetchone()
    if latest is None:
        raise ValueError("universe sync requires an existing approved snapshot")
    source = str(latest["source"]).strip()
    source_url = str(latest["source_url"] or "").strip()
    if not source_url:
        raise ValueError("latest universe snapshot has no synchronization URL")
    return sync_universe_from_url(
        connection,
        universe=universe,
        effective_at=effective_at,
        source=source,
        source_url=source_url,
        minimum_members=minimum_members,
        maximum_members=maximum_members,
        minimum_cik_coverage=minimum_cik_coverage,
        maximum_symbol_churn=maximum_symbol_churn,
        transport=transport,
    )


def sync_universe_from_url(
    connection: sqlite3.Connection,
    *,
    universe: str,
    effective_at: str,
    source: str,
    source_url: str,
    minimum_members: int = 450,
    maximum_members: int = 550,
    minimum_cik_coverage: float = 0.95,
    maximum_symbol_churn: float = 0.10,
    transport: HttpTransport | None = None,
) -> UniverseSyncResult:
    _validate_limits(
        minimum_members=minimum_members,
        maximum_members=maximum_members,
        minimum_cik_coverage=minimum_cik_coverage,
        maximum_symbol_churn=maximum_symbol_churn,
    )
    parsed_url = urlsplit(source_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise ValueError("universe synchronization URL must use HTTPS")

    response = (transport or UrllibTransport()).request(
        "GET",
        source_url,
        headers={
            "Accept": "text/csv,text/plain;q=0.9",
            "User-Agent": "stock-watch-universe-sync/1.0",
        },
        timeout=30,
    )
    if not 200 <= response.status < 300:
        raise RuntimeError(f"universe source returned HTTP {response.status}")
    if len(response.body) > MAXIMUM_CSV_BYTES:
        raise ValueError("universe CSV exceeds the maximum allowed size")
    try:
        text = response.body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("universe CSV is not valid UTF-8") from error
    members = read_members_csv_text(text)
    cik_coverage = validate_universe_members(
        members,
        minimum_members=minimum_members,
        maximum_members=maximum_members,
        minimum_cik_coverage=minimum_cik_coverage,
    )

    previous_symbols = _latest_symbols(connection, universe)
    current_symbols = {member.symbol for member in members}
    added = tuple(sorted(current_symbols - previous_symbols))
    removed = tuple(sorted(previous_symbols - current_symbols))
    if previous_symbols:
        symbol_churn = len(set(added) | set(removed)) / len(previous_symbols)
        if symbol_churn > maximum_symbol_churn:
            raise ValueError(
                "universe symbol churn exceeds the approved maximum: "
                f"{symbol_churn:.3f} > {maximum_symbol_churn:.3f}"
            )

    imported = import_universe_snapshot_if_changed(
        connection,
        members,
        universe=universe,
        effective_at=effective_at,
        source=source,
        source_url=source_url,
    )
    return UniverseSyncResult(
        import_result=imported,
        source=source,
        source_url=source_url,
        added_symbols=added,
        removed_symbols=removed,
        cik_coverage=cik_coverage,
    )


def validate_universe_members(
    members: Sequence[UniverseMember],
    *,
    minimum_members: int,
    maximum_members: int,
    minimum_cik_coverage: float,
) -> float:
    """Validate a reviewed current-universe CSV and return its CIK coverage."""

    _validate_limits(
        minimum_members=minimum_members,
        maximum_members=maximum_members,
        minimum_cik_coverage=minimum_cik_coverage,
        maximum_symbol_churn=1,
    )
    if not minimum_members <= len(members) <= maximum_members:
        raise ValueError(
            "universe member count is outside the approved range: "
            f"{len(members)} not in [{minimum_members}, {maximum_members}]"
        )
    cik_coverage = sum(member.cik is not None for member in members) / len(members)
    if cik_coverage < minimum_cik_coverage:
        raise ValueError(
            "universe CIK coverage is below the approved minimum: "
            f"{cik_coverage:.3f} < {minimum_cik_coverage:.3f}"
        )
    return cik_coverage


def _latest_symbols(connection: sqlite3.Connection, universe: str) -> set[str]:
    rows: Sequence[sqlite3.Row] = connection.execute(
        """
        SELECT instruments.symbol
        FROM universe_memberships
        JOIN instruments ON instruments.id = universe_memberships.instrument_id
        WHERE universe_memberships.snapshot_id = (
            SELECT id FROM universe_snapshots
            WHERE universe = ?
            ORDER BY effective_at DESC, id DESC
            LIMIT 1
        )
        """,
        (universe.strip(),),
    ).fetchall()
    return {str(row["symbol"]) for row in rows}


def _validate_limits(
    *,
    minimum_members: int,
    maximum_members: int,
    minimum_cik_coverage: float,
    maximum_symbol_churn: float,
) -> None:
    if minimum_members <= 0 or maximum_members < minimum_members:
        raise ValueError("universe member limits are invalid")
    if not 0 <= minimum_cik_coverage <= 1:
        raise ValueError("minimum CIK coverage must be between zero and one")
    if not 0 <= maximum_symbol_churn <= 1:
        raise ValueError("maximum symbol churn must be between zero and one")
