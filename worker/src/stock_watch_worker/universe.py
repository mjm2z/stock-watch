"""Versioned, reproducible universe snapshot ingestion."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class UniverseMember:
    symbol: str
    name: str | None = None
    exchange: str | None = None
    cik: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("universe symbol is required")
        object.__setattr__(self, "symbol", symbol)
        if self.name is not None:
            object.__setattr__(self, "name", self.name.strip() or None)
        if self.exchange is not None:
            object.__setattr__(self, "exchange", self.exchange.strip().upper() or None)
        if self.cik is not None:
            cik = self.cik.strip()
            if cik and not cik.isdigit():
                raise ValueError("universe CIK must contain only digits")
            object.__setattr__(self, "cik", (cik.lstrip("0") or "0") if cik else None)


@dataclass(frozen=True, slots=True)
class UniverseImportResult:
    snapshot_id: int
    content_sha256: str
    member_count: int
    already_existed: bool


@dataclass(frozen=True, slots=True)
class UniverseSnapshotInput:
    effective_at: str
    members: tuple[UniverseMember, ...]


@dataclass(frozen=True, slots=True)
class UniverseTimelineSnapshot:
    snapshot_id: int
    effective_at: str
    effective_date: date
    content_sha256: str
    survivorship_biased: bool
    members: tuple[str, ...]


def read_members_csv(path: str | Path) -> list[UniverseMember]:
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        members = _read_members(csv.DictReader(source))
    if not members:
        raise ValueError("universe CSV contains no members")
    return members


def read_members_csv_text(value: str) -> list[UniverseMember]:
    members = _read_members(csv.DictReader(io.StringIO(value.lstrip("\ufeff"))))
    if not members:
        raise ValueError("universe CSV contains no members")
    return members


def read_members_history_csv(path: str | Path) -> tuple[UniverseSnapshotInput, ...]:
    """Read a long-form constituent history grouped by effective timestamp."""

    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        fields = {field.strip().lower(): field for field in (reader.fieldnames or [])}
        effective_field = fields.get("effective_at") or fields.get("date")
        symbol_field = fields.get("symbol") or fields.get("ticker")
        if not effective_field or not symbol_field:
            raise ValueError(
                "universe history CSV requires effective_at/date and symbol/ticker columns"
            )
        name_field = fields.get("name") or fields.get("security")
        exchange_field = fields.get("exchange")
        cik_field = fields.get("cik")
        grouped: dict[str, list[UniverseMember]] = {}
        for row in reader:
            effective_at = row.get(effective_field, "").strip()
            _effective_date(effective_at)
            grouped.setdefault(effective_at, []).append(
                UniverseMember(
                    symbol=row.get(symbol_field, ""),
                    name=row.get(name_field) if name_field else None,
                    exchange=row.get(exchange_field) if exchange_field else None,
                    cik=row.get(cik_field) if cik_field else None,
                )
            )
    if not grouped:
        raise ValueError("universe history CSV contains no members")
    return tuple(
        UniverseSnapshotInput(effective_at, _normalize_members(grouped[effective_at]))
        for effective_at in sorted(grouped, key=lambda value: (_effective_date(value), value))
    )


def load_universe_timeline(
    connection: sqlite3.Connection,
    *,
    anchor_snapshot_id: int,
    start: date,
    end: date,
) -> tuple[UniverseTimelineSnapshot, ...]:
    """Resolve non-ambiguous daily membership snapshots covering a date range."""

    if start > end:
        raise ValueError("universe timeline start must not be after end")
    anchor = connection.execute(
        "SELECT universe FROM universe_snapshots WHERE id = ?",
        (anchor_snapshot_id,),
    ).fetchone()
    if anchor is None:
        raise ValueError("universe timeline anchor snapshot does not exist")
    rows = connection.execute(
        """
        SELECT id, effective_at, content_sha256, survivorship_biased
        FROM universe_snapshots
        WHERE universe = ?
        ORDER BY effective_at, id
        """,
        (str(anchor["universe"]),),
    ).fetchall()
    by_date: dict[date, list[sqlite3.Row]] = {}
    for row in rows:
        effective_date = _effective_date(str(row["effective_at"]))
        if effective_date <= end:
            by_date.setdefault(effective_date, []).append(row)
    ambiguous = [value.isoformat() for value, matches in by_date.items() if len(matches) > 1]
    if ambiguous:
        raise ValueError(
            "universe timeline has multiple snapshots on the same effective date: "
            + ", ".join(sorted(ambiguous))
        )
    prior_dates = [value for value in by_date if value <= start]
    if not prior_dates:
        raise ValueError("universe timeline has no snapshot effective on or before start")
    initial_date = max(prior_dates)
    selected_dates = [
        value for value in sorted(by_date) if value == initial_date or start < value <= end
    ]
    snapshots: list[UniverseTimelineSnapshot] = []
    for effective_date in selected_dates:
        row = by_date[effective_date][0]
        member_rows = connection.execute(
            """
            SELECT instruments.symbol
            FROM universe_memberships
            JOIN instruments ON instruments.id = universe_memberships.instrument_id
            WHERE universe_memberships.snapshot_id = ?
            ORDER BY instruments.symbol
            """,
            (int(row["id"]),),
        ).fetchall()
        members = tuple(str(member["symbol"]) for member in member_rows)
        if not members:
            raise ValueError(f"universe timeline snapshot {row['id']} has no members")
        snapshots.append(
            UniverseTimelineSnapshot(
                snapshot_id=int(row["id"]),
                effective_at=str(row["effective_at"]),
                effective_date=effective_date,
                content_sha256=str(row["content_sha256"]),
                survivorship_biased=bool(row["survivorship_biased"]),
                members=members,
            )
        )
    return tuple(snapshots)


def import_universe_snapshot(
    connection: sqlite3.Connection,
    members: Iterable[UniverseMember],
    *,
    universe: str,
    effective_at: str,
    source: str,
    source_url: str | None = None,
    survivorship_biased: bool = False,
) -> UniverseImportResult:
    normalized = _normalize_members(members)
    if not normalized:
        raise ValueError("universe snapshot requires at least one member")
    if not universe.strip() or not effective_at.strip() or not source.strip():
        raise ValueError("universe, effective_at, and source are required")

    canonical = json.dumps(
        [
            {
                "cik": member.cik,
                "exchange": member.exchange,
                "name": member.name,
                "symbol": member.symbol,
            }
            for member in normalized
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    existing = connection.execute(
        """
        SELECT id FROM universe_snapshots
        WHERE universe = ? AND effective_at = ? AND content_sha256 = ?
        """,
        (universe, effective_at, digest),
    ).fetchone()
    if existing:
        return UniverseImportResult(
            snapshot_id=int(existing["id"]),
            content_sha256=digest,
            member_count=len(normalized),
            already_existed=True,
        )

    with connection:
        cursor = connection.execute(
            """
            INSERT INTO universe_snapshots(
                universe, effective_at, source, source_url,
                content_sha256, survivorship_biased
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                universe.strip(),
                effective_at.strip(),
                source.strip(),
                source_url,
                digest,
                int(survivorship_biased),
            ),
        )
        snapshot_id = int(cursor.lastrowid)
        for member in normalized:
            connection.execute(
                """
                INSERT INTO instruments(symbol, name, exchange, cik)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol, asset_class) DO UPDATE SET
                    name = COALESCE(excluded.name, instruments.name),
                    exchange = COALESCE(excluded.exchange, instruments.exchange),
                    cik = COALESCE(excluded.cik, instruments.cik),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (member.symbol, member.name, member.exchange, member.cik),
            )
            instrument = connection.execute(
                "SELECT id FROM instruments WHERE symbol = ? AND asset_class = 'us_equity'",
                (member.symbol,),
            ).fetchone()
            connection.execute(
                "INSERT INTO universe_memberships(snapshot_id, instrument_id) VALUES (?, ?)",
                (snapshot_id, instrument["id"]),
            )

    return UniverseImportResult(
        snapshot_id=snapshot_id,
        content_sha256=digest,
        member_count=len(normalized),
        already_existed=False,
    )


def import_universe_snapshot_if_changed(
    connection: sqlite3.Connection,
    members: Iterable[UniverseMember],
    *,
    universe: str,
    effective_at: str,
    source: str,
    source_url: str | None = None,
    survivorship_biased: bool = False,
) -> UniverseImportResult:
    """Import only when membership content differs from the latest snapshot."""

    normalized = _normalize_members(members)
    if not normalized:
        raise ValueError("universe snapshot requires at least one member")
    digest = _members_sha256(normalized)
    latest = connection.execute(
        """
        SELECT id, effective_at, content_sha256 FROM universe_snapshots
        WHERE universe = ? ORDER BY effective_at DESC, id DESC LIMIT 1
        """,
        (universe.strip(),),
    ).fetchone()
    if latest is not None and str(latest["content_sha256"]) == digest:
        return UniverseImportResult(
            snapshot_id=int(latest["id"]),
            content_sha256=digest,
            member_count=len(normalized),
            already_existed=True,
        )
    if latest is not None and _effective_date(str(latest["effective_at"])) == _effective_date(
        effective_at
    ):
        raise ValueError(
            "refusing multiple changed universe snapshots on the same effective date"
        )
    return import_universe_snapshot(
        connection,
        normalized,
        universe=universe,
        effective_at=effective_at,
        source=source,
        source_url=source_url,
        survivorship_biased=survivorship_biased,
    )


def _normalize_members(members: Iterable[UniverseMember]) -> tuple[UniverseMember, ...]:
    by_symbol: dict[str, UniverseMember] = {}
    for member in members:
        existing = by_symbol.get(member.symbol)
        if existing and existing != member:
            raise ValueError(f"conflicting duplicate universe member: {member.symbol}")
        by_symbol[member.symbol] = member
    return tuple(by_symbol[symbol] for symbol in sorted(by_symbol))


def _members_sha256(members: Iterable[UniverseMember]) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                {
                    "cik": member.cik,
                    "exchange": member.exchange,
                    "name": member.name,
                    "symbol": member.symbol,
                }
                for member in members
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _read_members(reader: csv.DictReader[str]) -> list[UniverseMember]:
    fields = {field.strip().lower(): field for field in (reader.fieldnames or [])}
    symbol_field = fields.get("symbol") or fields.get("ticker")
    if not symbol_field:
        raise ValueError("universe CSV requires a symbol or ticker column")
    name_field = fields.get("name") or fields.get("security")
    exchange_field = fields.get("exchange")
    cik_field = fields.get("cik")
    return [
        UniverseMember(
            symbol=row.get(symbol_field, ""),
            name=row.get(name_field) if name_field else None,
            exchange=row.get(exchange_field) if exchange_field else None,
            cik=row.get(cik_field) if cik_field else None,
        )
        for row in reader
    ]


def _effective_date(value: str) -> date:
    if not value.strip():
        raise ValueError("universe effective_at is required")
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as error:
        raise ValueError("universe effective_at must start with an ISO date") from error
