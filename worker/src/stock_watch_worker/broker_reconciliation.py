"""Immutable Alpaca paper-account snapshots and fail-closed position reconciliation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol, Sequence

from .market_calendar import utc_iso
from .providers.alpaca import AlpacaAccount, AlpacaAccountActivity, AlpacaPosition


BROKER = "alpaca-paper"
CORPORATE_ACTION_TYPES = {
    "CGD",
    "DIV",
    "DIVCGL",
    "DIVCGS",
    "DIVFEE",
    "DIVFT",
    "DIVNRA",
    "DIVROC",
    "DIVTW",
    "MA",
    "NC",
    "REORG",
    "SC",
    "SSO",
    "SSP",
}


class BrokerSnapshotProvider(Protocol):
    def get_account(self) -> AlpacaAccount: ...

    def get_positions(self) -> list[AlpacaPosition]: ...

    def get_non_trade_activities(
        self, *, after: str | None = None
    ) -> list[AlpacaAccountActivity]: ...


@dataclass(frozen=True, slots=True)
class BrokerReconciliationResult:
    reconciliation_id: int
    account_snapshot_id: int
    captured_at: str
    status: str
    expected_positions: Mapping[str, float]
    actual_positions: Mapping[str, float]
    discrepancies: tuple[Mapping[str, object], ...]
    corporate_actions: tuple[Mapping[str, object], ...]
    activities_inserted: int
    inserted: bool


def capture_and_reconcile_broker(
    connection: sqlite3.Connection,
    *,
    broker: BrokerSnapshotProvider,
    captured_at: datetime,
) -> BrokerReconciliationResult:
    """Capture account state and compare it with strategy-owned open quantities."""

    timestamp = utc_iso(captured_at)
    existing = _existing_result(connection, timestamp)
    if existing is not None:
        return existing

    account = broker.get_account()
    positions = broker.get_positions()
    after = _latest_activity_date(connection)
    activities = broker.get_non_trade_activities(after=after)

    expected = _expected_positions(connection)
    actual = _actual_positions(positions)
    discrepancies = _discrepancies(expected, actual)
    affected_symbols = {
        str(item["symbol"])
        for item in discrepancies
        if item.get("symbol") is not None
    }
    corporate_actions = _corporate_action_evidence(
        connection,
        new_activities=activities,
        affected_symbols=affected_symbols,
    )
    blocked_reasons = []
    if account.status.upper() != "ACTIVE":
        blocked_reasons.append(f"account_status:{account.status}")
    if account.trading_blocked:
        blocked_reasons.append("trading_blocked")
    if account.account_blocked:
        blocked_reasons.append("account_blocked")
    if account.trade_suspended:
        blocked_reasons.append("trade_suspended_by_user")
    if blocked_reasons:
        status = "blocked"
        discrepancies = (
            *discrepancies,
            {"kind": "account_blocked", "reasons": blocked_reasons},
        )
    elif discrepancies:
        status = "drift"
    else:
        status = "matched"

    account_raw = _canonical_json(account.raw)
    expected_json = _canonical_json(expected)
    actual_json = _canonical_json(actual)
    discrepancies_json = _canonical_json(discrepancies)
    corporate_actions_json = _canonical_json(corporate_actions)
    inserted_activities = 0
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO broker_account_snapshots(
                captured_at, broker, account_id, status, currency, cash, equity,
                long_market_value, trading_blocked, account_blocked,
                trade_suspended, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                BROKER,
                account.id,
                account.status,
                account.currency,
                account.cash,
                account.equity,
                account.long_market_value,
                int(account.trading_blocked),
                int(account.account_blocked),
                int(account.trade_suspended),
                account_raw,
            ),
        )
        account_snapshot_id = int(cursor.lastrowid)
        for position in positions:
            connection.execute(
                """
                INSERT INTO broker_position_snapshots(
                    account_snapshot_id, symbol, asset_id, quantity,
                    market_value, current_price, cost_basis, side, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_snapshot_id,
                    position.symbol,
                    position.asset_id,
                    position.quantity,
                    position.market_value,
                    position.current_price,
                    position.cost_basis,
                    position.side,
                    _canonical_json(position.raw),
                ),
            )
        for activity in activities:
            inserted_activities += _insert_activity(
                connection, activity=activity, captured_at=timestamp
            )
        cursor = connection.execute(
            """
            INSERT INTO broker_reconciliations(
                captured_at, account_snapshot_id, status,
                expected_positions_json, actual_positions_json,
                discrepancies_json, corporate_actions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                account_snapshot_id,
                status,
                expected_json,
                actual_json,
                discrepancies_json,
                corporate_actions_json,
            ),
        )
        reconciliation_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO audit_events(event_type, entity_type, entity_id, payload_json)
            VALUES ('broker_positions_reconciled', 'broker_reconciliation', ?, ?)
            """,
            (
                str(reconciliation_id),
                _canonical_json(
                    {
                        "status": status,
                        "account_snapshot_id": account_snapshot_id,
                        "discrepancy_count": len(discrepancies),
                    }
                ),
            ),
        )
    return BrokerReconciliationResult(
        reconciliation_id=reconciliation_id,
        account_snapshot_id=account_snapshot_id,
        captured_at=timestamp,
        status=status,
        expected_positions=expected,
        actual_positions=actual,
        discrepancies=tuple(discrepancies),
        corporate_actions=corporate_actions,
        activities_inserted=inserted_activities,
        inserted=True,
    )


def _expected_positions(connection: sqlite3.Connection) -> dict[str, float]:
    rows = connection.execute(
        """
        SELECT instruments.symbol,
               SUM(lots.entry_quantity - COALESCE(lots.exit_quantity, 0)) AS quantity
        FROM paper_trade_lots AS lots
        JOIN instruments ON instruments.id = lots.instrument_id
        WHERE lots.status IN ('open', 'closing')
          AND lots.entry_quantity IS NOT NULL
        GROUP BY instruments.symbol
        HAVING quantity > 0
        ORDER BY instruments.symbol
        """
    ).fetchall()
    return {str(row["symbol"]): float(row["quantity"]) for row in rows}


def _actual_positions(positions: Sequence[AlpacaPosition]) -> dict[str, float]:
    actual: dict[str, float] = {}
    for position in positions:
        if position.symbol in actual:
            raise ValueError(f"Alpaca returned duplicate position {position.symbol}")
        actual[position.symbol] = position.quantity
    return dict(sorted(actual.items()))


def _discrepancies(
    expected: Mapping[str, float], actual: Mapping[str, float]
) -> tuple[Mapping[str, object], ...]:
    results: list[Mapping[str, object]] = []
    for symbol in sorted(set(expected) | set(actual)):
        expected_quantity = expected.get(symbol, 0.0)
        actual_quantity = actual.get(symbol, 0.0)
        tolerance = max(1e-8, abs(expected_quantity) * 1e-6)
        if abs(expected_quantity - actual_quantity) <= tolerance:
            continue
        kind = "quantity_mismatch"
        if not expected_quantity:
            kind = "unexpected_broker_position"
        elif not actual_quantity:
            kind = "missing_broker_position"
        results.append(
            {
                "kind": kind,
                "symbol": symbol,
                "expected_quantity": expected_quantity,
                "actual_quantity": actual_quantity,
                "difference": actual_quantity - expected_quantity,
            }
        )
    return tuple(results)


def _insert_activity(
    connection: sqlite3.Connection,
    *,
    activity: AlpacaAccountActivity,
    captured_at: str,
) -> int:
    raw_json = _canonical_json(activity.raw)
    existing = connection.execute(
        """
        SELECT raw_json FROM broker_account_activities
        WHERE broker = ? AND activity_id = ?
        """,
        (BROKER, activity.id),
    ).fetchone()
    if existing:
        if str(existing["raw_json"]) != raw_json:
            raise ValueError(f"broker activity {activity.id} changed after capture")
        return 0
    connection.execute(
        """
        INSERT INTO broker_account_activities(
            broker, activity_id, activity_type, occurred_at, symbol,
            net_amount, quantity, per_share_amount, captured_at, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            BROKER,
            activity.id,
            activity.activity_type,
            activity.occurred_at,
            activity.symbol,
            activity.net_amount,
            activity.quantity,
            activity.per_share_amount,
            captured_at,
            raw_json,
        ),
    )
    return 1


def _corporate_action_evidence(
    connection: sqlite3.Connection,
    *,
    new_activities: Sequence[AlpacaAccountActivity],
    affected_symbols: set[str],
) -> tuple[Mapping[str, object], ...]:
    if not affected_symbols:
        return ()
    evidence: dict[str, Mapping[str, object]] = {}
    placeholders = ",".join("?" for _ in affected_symbols)
    rows = connection.execute(
        f"""
        SELECT activity_id, activity_type, occurred_at, symbol, quantity, net_amount
        FROM broker_account_activities
        WHERE symbol IN ({placeholders})
        ORDER BY occurred_at DESC, activity_id DESC
        """,
        tuple(sorted(affected_symbols)),
    ).fetchall()
    for row in rows:
        if str(row["activity_type"]) in CORPORATE_ACTION_TYPES:
            evidence[str(row["activity_id"])] = {
                "activity_id": str(row["activity_id"]),
                "activity_type": str(row["activity_type"]),
                "occurred_at": str(row["occurred_at"]),
                "symbol": str(row["symbol"]),
                "quantity": row["quantity"],
                "net_amount": row["net_amount"],
            }
    for activity in new_activities:
        if (
            activity.activity_type in CORPORATE_ACTION_TYPES
            and activity.symbol in affected_symbols
        ):
            evidence[activity.id] = {
                "activity_id": activity.id,
                "activity_type": activity.activity_type,
                "occurred_at": activity.occurred_at,
                "symbol": activity.symbol,
                "quantity": activity.quantity,
                "net_amount": activity.net_amount,
            }
    return tuple(
        sorted(
            evidence.values(),
            key=lambda item: (str(item["occurred_at"]), str(item["activity_id"])),
            reverse=True,
        )
    )


def _latest_activity_date(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        """
        SELECT MAX(occurred_at) AS occurred_at
        FROM broker_account_activities WHERE broker = ?
        """,
        (BROKER,),
    ).fetchone()
    if row is None or row["occurred_at"] is None:
        return None
    return str(row["occurred_at"])[:10]


def _existing_result(
    connection: sqlite3.Connection, captured_at: str
) -> BrokerReconciliationResult | None:
    row = connection.execute(
        """
        SELECT id, account_snapshot_id, status, expected_positions_json,
               actual_positions_json, discrepancies_json, corporate_actions_json
        FROM broker_reconciliations WHERE captured_at = ?
        """,
        (captured_at,),
    ).fetchone()
    if row is None:
        return None
    return BrokerReconciliationResult(
        reconciliation_id=int(row["id"]),
        account_snapshot_id=int(row["account_snapshot_id"]),
        captured_at=captured_at,
        status=str(row["status"]),
        expected_positions=json.loads(row["expected_positions_json"]),
        actual_positions=json.loads(row["actual_positions_json"]),
        discrepancies=tuple(json.loads(row["discrepancies_json"])),
        corporate_actions=tuple(json.loads(row["corporate_actions_json"])),
        activities_inserted=0,
        inserted=False,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
