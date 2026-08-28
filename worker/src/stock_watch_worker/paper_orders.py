"""Crash-safe paper-order intent, submission, and broker reconciliation."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol

from .http import ProviderError
from .market_calendar import utc_iso


ORDER_NAMESPACE = uuid.UUID("b50521f3-3847-494b-96af-c06f91cb7496")


class PaperOrderBroker(Protocol):
    def get_order_by_client_order_id(self, client_order_id: str) -> Mapping[str, Any]: ...

    def submit_notional_market_buy(
        self,
        *,
        symbol: str,
        notional_usd: Decimal | float | str,
        client_order_id: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class OrderIntentResult:
    action: str
    order_id: str | None
    lot_id: str | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReconciledOrder:
    order_id: str
    client_order_id: str
    broker_order_id: str
    status: str
    broker_status: str


def create_order_intent(
    connection: sqlite3.Connection,
    *,
    signal_id: str,
    notional_usd: float,
    maximum_open_notional_per_ticker_usd: float = 30.0,
) -> OrderIntentResult:
    """Persist an order and lot before any broker call.

    Strategy promotion to ``paper`` is an explicit safety gate. A development
    or backtest strategy can create signals but cannot create order intents.
    """

    if not 5 <= notional_usd <= 15:
        raise ValueError("paper notional must be between $5 and $15")
    if maximum_open_notional_per_ticker_usd <= 0:
        raise ValueError("maximum open notional must be positive")
    signal = connection.execute(
        """
        SELECT s.id, s.strategy_version_id, s.instrument_id,
               s.horizon_trading_days, s.as_of, s.decision, s.risk_level,
               i.symbol, i.active, i.fractionable,
               strategy.status AS strategy_status
        FROM signals AS s
        JOIN instruments AS i ON i.id = s.instrument_id
        JOIN strategy_versions AS strategy ON strategy.id = s.strategy_version_id
        WHERE s.id = ?
        """,
        (signal_id,),
    ).fetchone()
    if signal is None:
        raise ValueError("signal does not exist")

    existing = connection.execute(
        """
        SELECT orders.id AS order_id, lots.id AS lot_id
        FROM paper_orders AS orders
        LEFT JOIN paper_trade_lots AS lots ON lots.entry_order_id = orders.id
        WHERE orders.signal_id = ?
        """,
        (signal_id,),
    ).fetchone()
    if existing:
        return OrderIntentResult(
            "existing", str(existing["order_id"]), str(existing["lot_id"])
        )

    rejection = _eligibility_rejection(signal)
    if rejection:
        _audit_rejection(connection, signal_id, rejection)
        return OrderIntentResult("rejected", None, None, rejection)

    reconciliation_rejection = _broker_reconciliation_rejection(
        connection, signal_as_of=str(signal["as_of"])
    )
    if reconciliation_rejection:
        _audit_rejection(connection, signal_id, reconciliation_rejection)
        return OrderIntentResult(
            "rejected", None, None, reconciliation_rejection
        )

    duplicate = connection.execute(
        """
        SELECT id FROM paper_trade_lots
        WHERE strategy_version_id = ? AND instrument_id = ?
          AND horizon_trading_days = ?
          AND status IN ('pending', 'open', 'closing')
        LIMIT 1
        """,
        (
            signal["strategy_version_id"],
            signal["instrument_id"],
            signal["horizon_trading_days"],
        ),
    ).fetchone()
    if duplicate:
        _audit_rejection(connection, signal_id, "duplicate_open_lot")
        return OrderIntentResult("rejected", None, None, "duplicate_open_lot")

    exposure = connection.execute(
        """
        SELECT COALESCE(SUM(entry_notional_usd), 0) AS notional
        FROM paper_trade_lots
        WHERE strategy_version_id = ? AND instrument_id = ?
          AND status IN ('pending', 'open', 'closing')
        """,
        (signal["strategy_version_id"], signal["instrument_id"]),
    ).fetchone()
    if float(exposure["notional"]) + notional_usd > maximum_open_notional_per_ticker_usd:
        _audit_rejection(connection, signal_id, "ticker_notional_limit")
        return OrderIntentResult("rejected", None, None, "ticker_notional_limit")

    order_id = f"order-{uuid.uuid5(ORDER_NAMESPACE, signal_id).hex}"
    lot_id = f"lot-{uuid.uuid5(ORDER_NAMESPACE, 'lot:' + signal_id).hex}"
    client_order_id = f"sw-{uuid.uuid5(ORDER_NAMESPACE, 'client:' + signal_id).hex}"
    with connection:
        connection.execute(
            """
            INSERT INTO paper_orders(
                id, signal_id, client_order_id, side, order_type,
                time_in_force, notional_usd, status
            ) VALUES (?, ?, ?, 'buy', 'market', 'day', ?, 'pending')
            """,
            (order_id, signal_id, client_order_id, notional_usd),
        )
        connection.execute(
            """
            INSERT INTO paper_trade_lots(
                id, signal_id, strategy_version_id, instrument_id,
                horizon_trading_days, entry_order_id, status,
                entry_notional_usd
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                lot_id,
                signal_id,
                signal["strategy_version_id"],
                signal["instrument_id"],
                signal["horizon_trading_days"],
                order_id,
                notional_usd,
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_events(event_type, entity_type, entity_id, payload_json)
            VALUES ('paper_order_intent_created', 'paper_order', ?, ?)
            """,
            (
                order_id,
                json.dumps(
                    {"signal_id": signal_id, "notional_usd": notional_usd},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
    return OrderIntentResult("created", order_id, lot_id)


def _broker_reconciliation_rejection(
    connection: sqlite3.Connection,
    *,
    signal_as_of: str,
) -> str | None:
    latest = connection.execute(
        """
        SELECT status, captured_at FROM broker_reconciliations
        ORDER BY captured_at DESC, id DESC LIMIT 1
        """
    ).fetchone()
    if latest is None:
        return "broker_reconciliation_unavailable"
    if latest["status"] != "matched":
        return "broker_position_drift"
    if _aware_timestamp(str(latest["captured_at"])) < _aware_timestamp(signal_as_of):
        return "broker_reconciliation_stale"
    return None


def _aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("broker reconciliation timestamps must include a timezone")
    return parsed


def submit_or_reconcile_order(
    connection: sqlite3.Connection,
    *,
    order_id: str,
    broker: PaperOrderBroker,
    now: datetime,
) -> ReconciledOrder:
    """Reconcile by client ID before submit, closing the crash-after-submit gap."""

    row = connection.execute(
        """
        SELECT orders.id, orders.client_order_id, orders.notional_usd,
               orders.status, instruments.symbol
        FROM paper_orders AS orders
        JOIN signals ON signals.id = orders.signal_id
        JOIN instruments ON instruments.id = signals.instrument_id
        WHERE orders.id = ?
        """,
        (order_id,),
    ).fetchone()
    if row is None:
        raise ValueError("paper order does not exist")
    if row["status"] in {"canceled", "rejected", "error"}:
        raise ValueError(f"paper order in terminal status {row['status']}")

    client_order_id = str(row["client_order_id"])
    try:
        response = broker.get_order_by_client_order_id(client_order_id)
    except ProviderError as error:
        if error.status != 404:
            _record_submission_error(connection, order_id, str(error))
            raise
        timestamp = utc_iso(now)
        with connection:
            connection.execute(
                """
                UPDATE paper_orders
                SET status = 'submitted', submitted_at = COALESCE(submitted_at, ?),
                    updated_at = ?, error = NULL
                WHERE id = ?
                """,
                (timestamp, timestamp, order_id),
            )
        try:
            response = broker.submit_notional_market_buy(
                symbol=str(row["symbol"]),
                notional_usd=float(row["notional_usd"]),
                client_order_id=client_order_id,
            )
        except Exception as error:
            _record_submission_error(connection, order_id, str(error))
            raise
    return reconcile_broker_order(connection, order_id=order_id, response=response, now=now)


def reconcile_broker_order(
    connection: sqlite3.Connection,
    *,
    order_id: str,
    response: Mapping[str, Any],
    now: datetime,
) -> ReconciledOrder:
    try:
        broker_order_id = str(response["id"])
        broker_status = str(response["status"])
    except (KeyError, TypeError) as error:
        raise ValueError("broker order response is missing id or status") from error
    if not broker_order_id or not broker_status:
        raise ValueError("broker order response is missing id or status")
    status = _normalize_broker_status(broker_status)
    raw_json = json.dumps(response, sort_keys=True, separators=(",", ":"), default=str)
    timestamp = utc_iso(now)
    submitted_at = _optional_text(response.get("submitted_at")) or timestamp
    with connection:
        cursor = connection.execute(
            """
            UPDATE paper_orders
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
                order_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("paper order does not exist")
        _update_lot_from_order(
            connection,
            order_id,
            broker_order_id,
            status,
            response,
            timestamp,
            raw_json,
        )
        connection.execute(
            """
            INSERT INTO audit_events(event_type, entity_type, entity_id, payload_json)
            VALUES ('paper_order_reconciled', 'paper_order', ?, ?)
            """,
            (
                order_id,
                json.dumps(
                    {"broker_order_id": broker_order_id, "status": status},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
    row = connection.execute(
        "SELECT client_order_id FROM paper_orders WHERE id = ?", (order_id,)
    ).fetchone()
    return ReconciledOrder(
        order_id=order_id,
        client_order_id=str(row["client_order_id"]),
        broker_order_id=broker_order_id,
        status=status,
        broker_status=broker_status,
    )


def _eligibility_rejection(signal: sqlite3.Row) -> str | None:
    if signal["strategy_status"] != "paper":
        return "strategy_not_promoted_to_paper"
    if signal["decision"] != "qualified":
        return "signal_not_qualified"
    if signal["risk_level"] == "high":
        return "risk_not_allowed"
    if not bool(signal["active"]):
        return "instrument_inactive"
    if signal["fractionable"] != 1:
        return "instrument_not_fractionable"
    return None


def _audit_rejection(
    connection: sqlite3.Connection, signal_id: str, reason: str
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO audit_events(event_type, entity_type, entity_id, payload_json)
            VALUES ('paper_order_intent_rejected', 'signal', ?, ?)
            """,
            (
                signal_id,
                json.dumps({"reason": reason}, separators=(",", ":")),
            ),
        )


def _record_submission_error(
    connection: sqlite3.Connection, order_id: str, error: str
) -> None:
    with connection:
        connection.execute(
            """
            UPDATE paper_orders SET error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error[:2000], order_id),
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


def _update_lot_from_order(
    connection: sqlite3.Connection,
    order_id: str,
    broker_order_id: str,
    status: str,
    response: Mapping[str, Any],
    fallback_timestamp: str,
    raw_json: str,
) -> None:
    if status in {"canceled", "rejected", "error"}:
        lot_status = "canceled" if status == "canceled" else "error"
        connection.execute(
            "UPDATE paper_trade_lots SET status = ? WHERE entry_order_id = ?",
            (lot_status, order_id),
        )
        return
    quantity = _positive_decimal(response.get("filled_qty"))
    price = _positive_decimal(response.get("filled_avg_price"))
    if quantity is None or price is None:
        if status == "filled":
            raise ValueError("filled paper entry is missing quantity or price")
        return
    opened_at = _optional_text(response.get("filled_at")) or fallback_timestamp
    lot_status = "open" if status in {"partially_filled", "filled"} else "pending"
    aggregate_fill_id = f"fill-{uuid.uuid5(ORDER_NAMESPACE, broker_order_id).hex}"
    aggregate_broker_fill_id = f"aggregate:{broker_order_id}"
    connection.execute(
        """
        INSERT INTO paper_fills(
            id, order_id, broker_fill_id, filled_at,
            quantity, price, notional_usd, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(order_id, broker_fill_id) DO UPDATE SET
            filled_at = excluded.filled_at,
            quantity = excluded.quantity,
            price = excluded.price,
            notional_usd = excluded.notional_usd,
            raw_json = excluded.raw_json
        """,
        (
            aggregate_fill_id,
            order_id,
            aggregate_broker_fill_id,
            opened_at,
            float(quantity),
            float(price),
            float(quantity * price),
            raw_json,
        ),
    )
    connection.execute(
        """
        UPDATE paper_trade_lots
        SET status = ?, opened_at = COALESCE(opened_at, ?),
            entry_quantity = ?, entry_price = ?
        WHERE entry_order_id = ?
        """,
        (lot_status, opened_at, float(quantity), float(price), order_id),
    )


def _positive_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result > 0 else None


def _optional_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
