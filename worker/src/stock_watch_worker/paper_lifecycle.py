"""Crash-safe entry reconciliation and time-bounded paper-lot exits."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from .http import ProviderError
from .market_calendar import MarketSession, utc_iso
from .paper_orders import PaperOrderBroker, submit_or_reconcile_order


EXIT_NAMESPACE = uuid.UUID("ed21af7c-0f98-416e-93fb-9ea26b754e06")
NEW_YORK = ZoneInfo("America/New_York")
NONTERMINAL_ORDER_STATUSES = (
    "pending",
    "submitted",
    "accepted",
    "partially_filled",
)


class PaperLifecycleBroker(PaperOrderBroker, Protocol):
    def submit_fractional_market_sell(
        self,
        *,
        symbol: str,
        quantity: Decimal | float | str,
        client_order_id: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ExitIntentResult:
    action: str
    exit_order_id: str


@dataclass(frozen=True, slots=True)
class ReconciledExit:
    exit_order_id: str
    client_order_id: str
    broker_order_id: str
    status: str
    broker_status: str


@dataclass(frozen=True, slots=True)
class PaperLifecycleResult:
    entries_reconciled: int
    targets_updated: int
    exit_intents_created: int
    exits_reconciled: int
    lots_closed: int


def create_exit_intent(
    connection: sqlite3.Connection,
    *,
    lot_id: str,
) -> ExitIntentResult:
    """Commit one deterministic sell intent before any broker request."""

    existing = connection.execute(
        "SELECT id FROM paper_exit_orders WHERE lot_id = ?", (lot_id,)
    ).fetchone()
    if existing is not None:
        return ExitIntentResult("existing", str(existing["id"]))
    lot = connection.execute(
        """
        SELECT lots.id, lots.status, lots.entry_quantity,
               entries.status AS entry_order_status,
               strategy.status AS strategy_status
        FROM paper_trade_lots AS lots
        JOIN paper_orders AS entries ON entries.id = lots.entry_order_id
        JOIN strategy_versions AS strategy ON strategy.id = lots.strategy_version_id
        WHERE lots.id = ?
        """,
        (lot_id,),
    ).fetchone()
    if lot is None:
        raise ValueError("paper lot does not exist")
    if lot["strategy_status"] != "paper":
        raise ValueError("paper lot strategy is not promoted to paper")
    if lot["status"] != "open":
        raise ValueError("only an open paper lot can create an exit intent")
    if lot["entry_order_status"] != "filled":
        raise ValueError("paper lot entry must be completely filled before exit")
    quantity = _positive_decimal(lot["entry_quantity"])
    if quantity is None:
        raise ValueError("paper lot has no filled entry quantity")

    exit_order_id = f"exit-{uuid.uuid5(EXIT_NAMESPACE, lot_id).hex}"
    client_order_id = f"swx-{uuid.uuid5(EXIT_NAMESPACE, 'client:' + lot_id).hex}"
    with connection:
        connection.execute(
            """
            INSERT INTO paper_exit_orders(
                id, lot_id, client_order_id, quantity, status
            ) VALUES (?, ?, ?, ?, 'pending')
            """,
            (exit_order_id, lot_id, client_order_id, float(quantity)),
        )
        connection.execute(
            "UPDATE paper_trade_lots SET status = 'closing' WHERE id = ?",
            (lot_id,),
        )
        _audit(
            connection,
            "paper_exit_intent_created",
            "paper_exit_order",
            exit_order_id,
            {"lot_id": lot_id, "quantity": float(quantity)},
        )
    return ExitIntentResult("created", exit_order_id)


def submit_or_reconcile_exit(
    connection: sqlite3.Connection,
    *,
    exit_order_id: str,
    broker: PaperLifecycleBroker,
    now: datetime,
) -> ReconciledExit:
    """Reconcile by client ID before submitting a fractional market sell."""

    row = connection.execute(
        """
        SELECT exits.id, exits.client_order_id, exits.quantity, exits.status,
               instruments.symbol
        FROM paper_exit_orders AS exits
        JOIN paper_trade_lots AS lots ON lots.id = exits.lot_id
        JOIN instruments ON instruments.id = lots.instrument_id
        WHERE exits.id = ?
        """,
        (exit_order_id,),
    ).fetchone()
    if row is None:
        raise ValueError("paper exit order does not exist")
    if row["status"] in {"canceled", "rejected", "error"}:
        raise ValueError(f"paper exit order in terminal status {row['status']}")

    client_order_id = str(row["client_order_id"])
    try:
        response = broker.get_order_by_client_order_id(client_order_id)
    except ProviderError as error:
        if error.status != 404:
            _record_exit_error(connection, exit_order_id, str(error))
            raise
        timestamp = utc_iso(now)
        with connection:
            connection.execute(
                """
                UPDATE paper_exit_orders
                SET status = 'submitted', submitted_at = COALESCE(submitted_at, ?),
                    updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (timestamp, timestamp, exit_order_id),
            )
        try:
            response = broker.submit_fractional_market_sell(
                symbol=str(row["symbol"]),
                quantity=float(row["quantity"]),
                client_order_id=client_order_id,
            )
        except Exception as error:
            _record_exit_error(connection, exit_order_id, str(error))
            raise
    return reconcile_exit_response(
        connection,
        exit_order_id=exit_order_id,
        response=response,
        now=now,
    )


def reconcile_exit_response(
    connection: sqlite3.Connection,
    *,
    exit_order_id: str,
    response: Mapping[str, Any],
    now: datetime,
) -> ReconciledExit:
    try:
        broker_order_id = str(response["id"])
        broker_status = str(response["status"])
    except (KeyError, TypeError) as error:
        raise ValueError("broker exit response is missing id or status") from error
    if not broker_order_id or not broker_status:
        raise ValueError("broker exit response is missing id or status")
    status = _normalize_broker_status(broker_status)
    raw_json = json.dumps(response, sort_keys=True, separators=(",", ":"), default=str)
    timestamp = utc_iso(now)
    submitted_at = _optional_text(response.get("submitted_at")) or timestamp
    with connection:
        cursor = connection.execute(
            """
            UPDATE paper_exit_orders
            SET broker_order_id = ?, broker_request_id = ?, status = ?,
                submitted_at = COALESCE(submitted_at, ?), updated_at = ?,
                error = CASE WHEN ? IN ('rejected', 'error') THEN ? ELSE NULL END,
                raw_json = ?
            WHERE id = ?
            """,
            (
                broker_order_id,
                _optional_text(response.get("request_id")),
                status,
                submitted_at,
                timestamp,
                status,
                _optional_text(response.get("reject_reason")),
                raw_json,
                exit_order_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("paper exit order does not exist")
        _update_lot_from_exit(
            connection,
            exit_order_id=exit_order_id,
            broker_order_id=broker_order_id,
            status=status,
            response=response,
            fallback_timestamp=timestamp,
            raw_json=raw_json,
        )
        _audit(
            connection,
            "paper_exit_reconciled",
            "paper_exit_order",
            exit_order_id,
            {"broker_order_id": broker_order_id, "status": status},
        )
    row = connection.execute(
        "SELECT client_order_id FROM paper_exit_orders WHERE id = ?",
        (exit_order_id,),
    ).fetchone()
    return ReconciledExit(
        exit_order_id=exit_order_id,
        client_order_id=str(row["client_order_id"]),
        broker_order_id=broker_order_id,
        status=status,
        broker_status=broker_status,
    )


def reconcile_paper_lifecycle(
    connection: sqlite3.Connection,
    *,
    broker: PaperLifecycleBroker,
    sessions: Sequence[MarketSession],
    now: datetime,
) -> PaperLifecycleResult:
    """Reconcile entries/exits and submit exits after the configured horizon close."""

    utc_iso(now)
    ordered_sessions = _validated_sessions(sessions)
    entries_reconciled = 0
    targets_updated = 0
    exit_intents_created = 0
    exits_reconciled = 0
    initially_closed = _closed_lot_count(connection)

    entry_rows = connection.execute(
        f"""
        SELECT id FROM paper_orders
        WHERE status IN ({','.join('?' for _ in NONTERMINAL_ORDER_STATUSES)})
        ORDER BY updated_at, id
        """,
        NONTERMINAL_ORDER_STATUSES,
    ).fetchall()
    for row in entry_rows:
        submit_or_reconcile_order(
            connection,
            order_id=str(row["id"]),
            broker=broker,
            now=now,
        )
        entries_reconciled += 1

    exit_rows = connection.execute(
        f"""
        SELECT id FROM paper_exit_orders
        WHERE status IN ({','.join('?' for _ in NONTERMINAL_ORDER_STATUSES)})
        ORDER BY updated_at, id
        """,
        NONTERMINAL_ORDER_STATUSES,
    ).fetchall()
    for row in exit_rows:
        submit_or_reconcile_exit(
            connection,
            exit_order_id=str(row["id"]),
            broker=broker,
            now=now,
        )
        exits_reconciled += 1

    lots = connection.execute(
        """
        SELECT id, opened_at, horizon_trading_days,
               minimum_exit_at, target_exit_at
        FROM paper_trade_lots
        WHERE status = 'open' AND opened_at IS NOT NULL
        ORDER BY opened_at, id
        """
    ).fetchall()
    for lot in lots:
        schedule = _lot_schedule(
            opened_at=str(lot["opened_at"]),
            horizon=int(lot["horizon_trading_days"]),
            sessions=ordered_sessions,
        )
        if schedule is None:
            continue
        minimum_exit_at, target_exit_at = schedule
        if (
            lot["minimum_exit_at"] != minimum_exit_at
            or lot["target_exit_at"] != target_exit_at
        ):
            with connection:
                connection.execute(
                    """
                    UPDATE paper_trade_lots
                    SET minimum_exit_at = ?, target_exit_at = ?
                    WHERE id = ? AND status = 'open'
                    """,
                    (minimum_exit_at, target_exit_at, lot["id"]),
                )
            targets_updated += 1
        target = _parse_timestamp(target_exit_at)
        if now.astimezone(target.tzinfo) < target:
            continue
        intent = create_exit_intent(connection, lot_id=str(lot["id"]))
        exit_intents_created += int(intent.action == "created")
        submit_or_reconcile_exit(
            connection,
            exit_order_id=intent.exit_order_id,
            broker=broker,
            now=now,
        )
        exits_reconciled += 1

    return PaperLifecycleResult(
        entries_reconciled=entries_reconciled,
        targets_updated=targets_updated,
        exit_intents_created=exit_intents_created,
        exits_reconciled=exits_reconciled,
        lots_closed=_closed_lot_count(connection) - initially_closed,
    )


def _lot_schedule(
    *,
    opened_at: str,
    horizon: int,
    sessions: Sequence[MarketSession],
) -> tuple[str, str] | None:
    opened = _parse_timestamp(opened_at)
    opened_date = opened.astimezone(NEW_YORK).date()
    entry_index = next(
        (index for index, session in enumerate(sessions) if session.trading_date == opened_date),
        None,
    )
    if entry_index is None:
        return None
    target_index = entry_index + horizon - 1
    if target_index >= len(sessions):
        return None
    minimum_index = min(entry_index + 1, target_index)
    return (
        utc_iso(sessions[minimum_index].closes_at),
        utc_iso(sessions[target_index].closes_at),
    )


def _validated_sessions(sessions: Sequence[MarketSession]) -> tuple[MarketSession, ...]:
    ordered = tuple(sorted(sessions, key=lambda session: session.trading_date))
    if len({session.trading_date for session in ordered}) != len(ordered):
        raise ValueError("market calendar contains duplicate sessions")
    return ordered


def _update_lot_from_exit(
    connection: sqlite3.Connection,
    *,
    exit_order_id: str,
    broker_order_id: str,
    status: str,
    response: Mapping[str, Any],
    fallback_timestamp: str,
    raw_json: str,
) -> None:
    lot = connection.execute(
        """
        SELECT lots.id, lots.entry_price
        FROM paper_exit_orders AS exits
        JOIN paper_trade_lots AS lots ON lots.id = exits.lot_id
        WHERE exits.id = ?
        """,
        (exit_order_id,),
    ).fetchone()
    if lot is None:
        raise ValueError("paper exit lot does not exist")
    if status in {"canceled", "rejected", "error"}:
        connection.execute(
            "UPDATE paper_trade_lots SET status = 'closing' WHERE id = ?",
            (lot["id"],),
        )
        return
    quantity = _positive_decimal(response.get("filled_qty"))
    price = _positive_decimal(response.get("filled_avg_price"))
    if quantity is None or price is None:
        if status == "filled":
            raise ValueError("filled paper exit is missing quantity or price")
        return
    filled_at = _optional_text(response.get("filled_at")) or fallback_timestamp
    aggregate_fill_id = f"exit-fill-{uuid.uuid5(EXIT_NAMESPACE, broker_order_id).hex}"
    aggregate_broker_fill_id = f"aggregate:{broker_order_id}"
    connection.execute(
        """
        INSERT INTO paper_exit_fills(
            id, exit_order_id, broker_fill_id, filled_at,
            quantity, price, notional_usd, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(exit_order_id, broker_fill_id) DO UPDATE SET
            filled_at = excluded.filled_at,
            quantity = excluded.quantity,
            price = excluded.price,
            notional_usd = excluded.notional_usd,
            raw_json = excluded.raw_json
        """,
        (
            aggregate_fill_id,
            exit_order_id,
            aggregate_broker_fill_id,
            filled_at,
            float(quantity),
            float(price),
            float(quantity * price),
            raw_json,
        ),
    )
    if status != "filled":
        connection.execute(
            """
            UPDATE paper_trade_lots
            SET exit_quantity = ?, exit_price = ?
            WHERE id = ?
            """,
            (float(quantity), float(price), lot["id"]),
        )
        return
    entry_price = _positive_decimal(lot["entry_price"])
    if entry_price is None:
        raise ValueError("paper lot is missing its entry price")
    realized_return = float(price / entry_price - Decimal("1"))
    connection.execute(
        """
        UPDATE paper_trade_lots
        SET status = 'closed', closed_at = ?, exit_quantity = ?,
            exit_price = ?, realized_return = ?
        WHERE id = ?
        """,
        (filled_at, float(quantity), float(price), realized_return, lot["id"]),
    )


def _record_exit_error(
    connection: sqlite3.Connection, exit_order_id: str, error: str
) -> None:
    with connection:
        connection.execute(
            """
            UPDATE paper_exit_orders
            SET error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error[:2000], exit_order_id),
        )


def _normalize_broker_status(status: str) -> str:
    normalized = status.lower()
    mapping = {
        "pending_new": "submitted",
        "pending_replace": "submitted",
        "pending_cancel": "submitted",
        "accepted": "accepted",
        "new": "accepted",
        "accepted_for_bidding": "accepted",
        "partially_filled": "partially_filled",
        "filled": "filled",
        "canceled": "canceled",
        "expired": "canceled",
        "replaced": "canceled",
        "done_for_day": "canceled",
        "rejected": "rejected",
        "stopped": "error",
        "suspended": "error",
        "calculated": "error",
    }
    if normalized not in mapping:
        raise ValueError(f"unsupported Alpaca order status: {status}")
    return mapping[normalized]


def _positive_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("broker fill contains an invalid numeric value") from error
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("broker fill values must be positive")
    return parsed


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("paper lifecycle timestamps must include a timezone")
    return parsed


def _closed_lot_count(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM paper_trade_lots WHERE status = 'closed'"
    ).fetchone()
    return int(row["count"])


def _audit(
    connection: sqlite3.Connection,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: Mapping[str, object],
) -> None:
    connection.execute(
        """
        INSERT INTO audit_events(event_type, entity_type, entity_id, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            event_type,
            entity_type,
            entity_id,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        ),
    )
