"""Explicit, immutable promotion of reviewed strategies to paper trading."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import load_strategy_document
from .market_calendar import utc_iso


@dataclass(frozen=True, slots=True)
class StrategyPromotionResult:
    source_strategy_id: str
    paper_strategy_id: str
    paper_strategy_sha256: str
    created: bool
    promoted_at: str


def promote_strategy_to_paper(
    connection: sqlite3.Connection,
    *,
    source_strategy_id: str,
    paper_strategy_id: str,
    confirmation: str,
    paper_strategy_name: str | None = None,
    now: datetime | None = None,
) -> StrategyPromotionResult:
    """Clone a reviewed strategy into a new immutable paper version.

    The confirmation must exactly match the new ID. The source row and its
    canonical configuration must agree, and an audit event is committed in the
    same transaction as the paper strategy.
    """

    source_id = source_strategy_id.strip()
    target_id = paper_strategy_id.strip()
    if not source_id or not target_id:
        raise ValueError("source and paper strategy IDs are required")
    if source_id == target_id:
        raise ValueError("paper promotion requires a new strategy version ID")
    if confirmation != target_id:
        raise ValueError("paper promotion confirmation must exactly match the new ID")

    source = connection.execute(
        """
        SELECT id, name, status, config_json, config_sha256
        FROM strategy_versions WHERE id = ?
        """,
        (source_id,),
    ).fetchone()
    if source is None:
        raise ValueError("source strategy version does not exist")
    source_strategy = load_strategy_document(json.loads(str(source["config_json"])))
    if (
        source_strategy.id != source_id
        or source_strategy.status != str(source["status"])
        or source_strategy.sha256 != str(source["config_sha256"])
    ):
        raise ValueError("source strategy row does not match its immutable configuration")
    if source_strategy.status not in {"development", "backtest"}:
        raise ValueError("only development or backtest strategies can be promoted")

    target_document = dict(source_strategy.data)
    target_document["id"] = target_id
    target_document["name"] = _paper_name(
        paper_strategy_name,
        fallback=f"{source_strategy.name} (paper)",
    )
    target_document["status"] = "paper"
    target_strategy = load_strategy_document(target_document)
    promoted_at = utc_iso(now or datetime.now(timezone.utc))
    existing = connection.execute(
        """
        SELECT status, config_sha256, promoted_at
        FROM strategy_versions WHERE id = ?
        """,
        (target_id,),
    ).fetchone()
    if existing is not None:
        if (
            str(existing["status"]) != "paper"
            or str(existing["config_sha256"]) != target_strategy.sha256
            or existing["promoted_at"] is None
        ):
            raise ValueError(
                f"strategy {target_id} already exists with different promotion data"
            )
        return StrategyPromotionResult(
            source_id,
            target_id,
            target_strategy.sha256,
            False,
            str(existing["promoted_at"]),
        )

    payload = json.dumps(
        {
            "source_strategy_id": source_id,
            "source_strategy_sha256": source_strategy.sha256,
            "paper_strategy_id": target_id,
            "paper_strategy_sha256": target_strategy.sha256,
            "execution_mode": "paper",
            "alpaca_base_url": target_strategy.data["execution"]["alpaca_base_url"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with connection:
        connection.execute(
            """
            INSERT INTO strategy_versions(
                id, name, status, config_json, config_sha256, promoted_at
            ) VALUES (?, ?, 'paper', ?, ?, ?)
            """,
            (
                target_strategy.id,
                target_strategy.name,
                target_strategy.canonical_json,
                target_strategy.sha256,
                promoted_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_events(
                occurred_at, event_type, entity_type, entity_id, payload_json
            ) VALUES (?, 'strategy_promoted_to_paper', 'strategy_version', ?, ?)
            """,
            (promoted_at, target_id, payload),
        )
    return StrategyPromotionResult(
        source_id,
        target_id,
        target_strategy.sha256,
        True,
        promoted_at,
    )


def _paper_name(value: str | None, *, fallback: str) -> str:
    if value is None:
        return fallback
    name = value.strip()
    if not name:
        raise ValueError("paper strategy name cannot be blank")
    return name
