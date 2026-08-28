"""Fail-closed database readiness checks for scheduled operation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from .config import load_strategy_document


@dataclass(frozen=True, slots=True)
class DeploymentReadiness:
    ready: bool
    checks: Mapping[str, Mapping[str, Any]]


def check_deployment_readiness(
    connection: sqlite3.Connection,
    *,
    strategy_id: str,
    minimum_universe_members: int = 450,
    minimum_asset_coverage: float = 0.95,
    minimum_cik_coverage: float = 0.95,
) -> DeploymentReadiness:
    if minimum_universe_members < 1:
        raise ValueError("minimum universe members must be positive")
    for name, value in (
        ("minimum asset coverage", minimum_asset_coverage),
        ("minimum CIK coverage", minimum_cik_coverage),
    ):
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between zero and one")

    strategy_check = _strategy_check(connection, strategy_id.strip())
    snapshot = connection.execute(
        """
        SELECT id, effective_at, source, survivorship_biased
        FROM universe_snapshots
        WHERE universe = 'sp500'
        ORDER BY effective_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if snapshot is None:
        universe_check: Mapping[str, Any] = {
            "ready": False,
            "reason": "missing_sp500_snapshot",
            "members": 0,
            "minimum_members": minimum_universe_members,
        }
        asset_check = _coverage_check(
            known=0,
            total=0,
            minimum=minimum_asset_coverage,
            missing_reason="missing_sp500_snapshot",
        )
        cik_check = _coverage_check(
            known=0,
            total=0,
            minimum=minimum_cik_coverage,
            missing_reason="missing_sp500_snapshot",
        )
    else:
        snapshot_id = int(snapshot["id"])
        coverage = connection.execute(
            """
            SELECT
                COUNT(*) AS members,
                SUM(CASE WHEN instruments.fractionable IS NOT NULL THEN 1 ELSE 0 END)
                    AS asset_metadata,
                SUM(CASE WHEN instruments.cik IS NOT NULL AND instruments.cik != ''
                    THEN 1 ELSE 0 END) AS ciks
            FROM universe_memberships
            JOIN instruments ON instruments.id = universe_memberships.instrument_id
            WHERE universe_memberships.snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        members = int(coverage["members"])
        universe_check = {
            "ready": members >= minimum_universe_members,
            "snapshot_id": snapshot_id,
            "effective_at": str(snapshot["effective_at"]),
            "source": str(snapshot["source"]),
            "survivorship_biased": bool(snapshot["survivorship_biased"]),
            "members": members,
            "minimum_members": minimum_universe_members,
        }
        asset_check = _coverage_check(
            known=int(coverage["asset_metadata"] or 0),
            total=members,
            minimum=minimum_asset_coverage,
            missing_reason="asset_metadata_incomplete",
        )
        cik_check = _coverage_check(
            known=int(coverage["ciks"] or 0),
            total=members,
            minimum=minimum_cik_coverage,
            missing_reason="cik_coverage_incomplete",
        )

    checks = {
        "strategy": strategy_check,
        "universe": universe_check,
        "asset_metadata": asset_check,
        "cik_coverage": cik_check,
    }
    return DeploymentReadiness(
        ready=all(bool(check["ready"]) for check in checks.values()),
        checks=checks,
    )


def readiness_json(result: DeploymentReadiness) -> str:
    return json.dumps(
        {"ready": result.ready, "checks": result.checks},
        sort_keys=True,
        separators=(",", ":"),
    )


def _strategy_check(
    connection: sqlite3.Connection, strategy_id: str
) -> Mapping[str, Any]:
    if not strategy_id:
        return {"ready": False, "reason": "missing_strategy_id"}
    row = connection.execute(
        """
        SELECT id, status, config_json, config_sha256
        FROM strategy_versions WHERE id = ?
        """,
        (strategy_id,),
    ).fetchone()
    if row is None:
        return {
            "ready": False,
            "reason": "strategy_not_registered",
            "strategy_id": strategy_id,
        }
    try:
        strategy = load_strategy_document(json.loads(str(row["config_json"])))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        return {
            "ready": False,
            "reason": "invalid_strategy_configuration",
            "strategy_id": strategy_id,
            "error": str(error),
        }
    verified = (
        strategy.id == strategy_id
        and strategy.status == str(row["status"])
        and strategy.sha256 == str(row["config_sha256"])
    )
    return {
        "ready": verified,
        "reason": None if verified else "strategy_hash_or_status_mismatch",
        "strategy_id": strategy_id,
        "status": str(row["status"]),
        "config_sha256": str(row["config_sha256"]),
    }


def _coverage_check(
    *,
    known: int,
    total: int,
    minimum: float,
    missing_reason: str,
) -> Mapping[str, Any]:
    coverage = known / total if total else 0.0
    ready = total > 0 and coverage >= minimum
    return {
        "ready": ready,
        "reason": None if ready else missing_reason,
        "known": known,
        "total": total,
        "coverage": coverage,
        "minimum_coverage": minimum,
    }
