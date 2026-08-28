"""Idempotent feature, signal, and paper-intent execution for one scan run."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from .domain import RiskLevel, ScoreRequest, ScoreResult, SignalDecision
from .features import FeatureSet, build_feature_set
from .http import ProviderError
from .market_calendar import utc_iso
from .paper_orders import PaperOrderBroker, create_order_intent, submit_or_reconcile_order
from .scan_data import CandidateData, ScanInputs
from .strategy import QualificationPolicy, calculate_notional, calculate_score


SIGNAL_NAMESPACE = uuid.UUID("313e89b7-568d-474b-8042-3c5087f42d61")


@dataclass(frozen=True, slots=True)
class ScanExecutionResult:
    scan_run_id: str
    status: str
    candidates_total: int
    candidates_scored: int
    candidate_failures: int
    signals_created: int
    signals_existing: int
    qualified_signals: int
    order_intents_created: int
    order_intents_rejected: int
    broker_orders_reconciled: int


def execute_scan(
    connection: sqlite3.Connection,
    *,
    inputs: ScanInputs,
    now: datetime,
    broker: PaperOrderBroker | None = None,
) -> ScanExecutionResult:
    scan = connection.execute(
        """
        SELECT scans.id, scans.strategy_version_id, scans.universe_snapshot_id,
               scans.status, strategy.status AS strategy_status,
               strategy.config_json
        FROM scan_runs AS scans
        JOIN strategy_versions AS strategy ON strategy.id = scans.strategy_version_id
        WHERE scans.id = ?
        """,
        (inputs.scan_run_id,),
    ).fetchone()
    if scan is None:
        raise ValueError("scan run does not exist")
    if inputs.data_cutoff != _scan_cutoff(connection, inputs.scan_run_id):
        raise ValueError("scan inputs do not match the durable data cutoff")
    if not inputs.spy_bars:
        _mark_scan_failed(connection, inputs.scan_run_id, now, "SPY history is missing")
        raise ValueError("SPY history is missing")

    config = _strategy_config(str(scan["config_json"]))
    horizons = _horizons(config)
    weights = _weights(config)
    policy = _qualification_policy(config)
    started_at = utc_iso(now)
    with connection:
        connection.execute(
            """
            UPDATE scan_runs
            SET status = 'running', started_at = COALESCE(started_at, ?),
                completed_at = NULL, error = NULL
            WHERE id = ?
            """,
            (started_at, inputs.scan_run_id),
        )

    scored = 0
    failures = 0
    signals_created = 0
    signals_existing = 0
    qualified = 0
    intents_created = 0
    intents_rejected = 0
    broker_reconciled = 0

    for candidate in inputs.candidates:
        try:
            _require_membership(
                connection,
                int(scan["universe_snapshot_id"]),
                candidate.instrument_id,
            )
            features = build_feature_set(
                as_of=inputs.data_cutoff,
                bars=candidate.bars,
                spy_bars=inputs.spy_bars,
                fundamentals=candidate.fundamentals,
                news_sentiments=candidate.news_sentiments,
                news_coverage_complete=candidate.news_coverage_complete,
            )
            score = calculate_score(
                ScoreRequest(
                    ticker=candidate.symbol,
                    pillars=features.pillars,
                    risk_level=features.risk_level,
                    vetoes=candidate.vetoes,
                    in_universe=True,
                ),
                weights=weights,
                policy=policy,
            )
            feature_id = _persist_feature(
                connection,
                candidate=candidate,
                features=features,
                data_completeness=score.data_completeness,
            )
            scored += 1
            for horizon in horizons:
                signal_id, created = _persist_signal(
                    connection,
                    scan_run_id=inputs.scan_run_id,
                    strategy_version_id=str(scan["strategy_version_id"]),
                    candidate=candidate,
                    feature_id=feature_id,
                    as_of=inputs.data_cutoff,
                    horizon=horizon,
                    score=score,
                )
                signals_created += int(created)
                signals_existing += int(not created)
                if score.decision is not SignalDecision.QUALIFIED:
                    continue
                qualified += 1
                if scan["strategy_status"] != "paper":
                    continue
                notional = calculate_notional(score.opportunity_score, score.risk_level)
                intent = create_order_intent(
                    connection,
                    signal_id=signal_id,
                    notional_usd=notional,
                )
                intents_created += int(intent.action == "created")
                intents_rejected += int(intent.action == "rejected")
                if broker is not None and intent.order_id is not None:
                    try:
                        submit_or_reconcile_order(
                            connection,
                            order_id=intent.order_id,
                            broker=broker,
                            now=now,
                        )
                        broker_reconciled += 1
                    except (ProviderError, ValueError) as error:
                        failures += 1
                        _audit_candidate_failure(
                            connection,
                            inputs.scan_run_id,
                            candidate,
                            f"paper order reconciliation failed: {error}",
                        )
        except (TypeError, ValueError) as error:
            failures += 1
            _audit_candidate_failure(
                connection,
                inputs.scan_run_id,
                candidate,
                str(error),
            )

    status = "partial" if failures else "succeeded"
    metrics = {
        "broker_orders_reconciled": broker_reconciled,
        "candidate_failures": failures,
        "candidates_scored": scored,
        "candidates_total": len(inputs.candidates),
        "order_intents_created": intents_created,
        "order_intents_rejected": intents_rejected,
        "qualified_signals": qualified,
        "signals_created": signals_created,
        "signals_existing": signals_existing,
    }
    with connection:
        connection.execute(
            """
            UPDATE scan_runs
            SET status = ?, completed_at = ?, metrics_json = ?, error = ?
            WHERE id = ?
            """,
            (
                status,
                utc_iso(now),
                _canonical_json(metrics),
                f"{failures} candidate or order failures" if failures else None,
                inputs.scan_run_id,
            ),
        )
    return ScanExecutionResult(
        scan_run_id=inputs.scan_run_id,
        status=status,
        candidates_total=len(inputs.candidates),
        candidates_scored=scored,
        candidate_failures=failures,
        signals_created=signals_created,
        signals_existing=signals_existing,
        qualified_signals=qualified,
        order_intents_created=intents_created,
        order_intents_rejected=intents_rejected,
        broker_orders_reconciled=broker_reconciled,
    )


def _persist_feature(
    connection: sqlite3.Connection,
    *,
    candidate: CandidateData,
    features: FeatureSet,
    data_completeness: float,
) -> int:
    payload = _canonical_json(
        {
            "as_of": features.as_of,
            "pillars": {
                name: {
                    "as_of": value.as_of,
                    "score": value.score,
                    "source_count": value.source_count,
                }
                for name, value in features.pillars.items()
            },
            "raw": dict(features.raw),
            "risk_level": features.risk_level.value,
        }
    )
    source_refs = _canonical_json(dict(candidate.source_refs))
    with connection:
        connection.execute(
            """
            INSERT INTO feature_snapshots(
                instrument_id, as_of, feature_set_version,
                features_json, data_completeness, source_refs_json
            ) VALUES (?, ?, 'features-v0', ?, ?, ?)
            ON CONFLICT(instrument_id, as_of, feature_set_version) DO NOTHING
            """,
            (
                candidate.instrument_id,
                features.as_of,
                payload,
                data_completeness,
                source_refs,
            ),
        )
    row = connection.execute(
        """
        SELECT id, features_json, data_completeness, source_refs_json
        FROM feature_snapshots
        WHERE instrument_id = ? AND as_of = ? AND feature_set_version = 'features-v0'
        """,
        (candidate.instrument_id, features.as_of),
    ).fetchone()
    if row is None:
        raise RuntimeError("feature snapshot was not persisted")
    if (
        row["features_json"] != payload
        or float(row["data_completeness"]) != data_completeness
        or row["source_refs_json"] != source_refs
    ):
        raise ValueError("immutable feature snapshot conflicts with scan inputs")
    return int(row["id"])


def _persist_signal(
    connection: sqlite3.Connection,
    *,
    scan_run_id: str,
    strategy_version_id: str,
    candidate: CandidateData,
    feature_id: int,
    as_of: str,
    horizon: int,
    score: ScoreResult,
) -> tuple[str, bool]:
    signal_id = f"signal-{uuid.uuid5(SIGNAL_NAMESPACE, f'{scan_run_id}:{candidate.instrument_id}:{horizon}').hex}"
    reasons = _canonical_json(list(score.reasons))
    explanation = _explanation(candidate.symbol, score)
    with connection:
        cursor = connection.execute(
            """
            INSERT INTO signals(
                id, scan_run_id, strategy_version_id, instrument_id,
                feature_snapshot_id, horizon_trading_days, as_of,
                opportunity_score, data_completeness, risk_level,
                decision, reasons_json, explanation
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scan_run_id, instrument_id, horizon_trading_days) DO NOTHING
            """,
            (
                signal_id,
                scan_run_id,
                strategy_version_id,
                candidate.instrument_id,
                feature_id,
                horizon,
                as_of,
                score.opportunity_score,
                score.data_completeness,
                score.risk_level.value,
                score.decision.value,
                reasons,
                explanation,
            ),
        )
        created = cursor.rowcount == 1
        row = connection.execute(
            """
            SELECT id, opportunity_score, data_completeness, risk_level,
                   decision, reasons_json, explanation
            FROM signals
            WHERE scan_run_id = ? AND instrument_id = ? AND horizon_trading_days = ?
            """,
            (scan_run_id, candidate.instrument_id, horizon),
        ).fetchone()
        if row is None:
            raise RuntimeError("signal was not persisted")
        actual_signal_id = str(row["id"])
        expected = (
            score.opportunity_score,
            score.data_completeness,
            score.risk_level.value,
            score.decision.value,
            reasons,
            explanation,
        )
        observed = (
            float(row["opportunity_score"]),
            float(row["data_completeness"]),
            str(row["risk_level"]),
            str(row["decision"]),
            str(row["reasons_json"]),
            str(row["explanation"]),
        )
        if observed != expected:
            raise ValueError("immutable signal conflicts with scan inputs")
        for contribution in score.contributions:
            connection.execute(
                """
                INSERT INTO signal_components(
                    signal_id, name, raw_value, normalized_score,
                    weight, weighted_points, available, source_refs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id, name) DO NOTHING
                """,
                (
                    actual_signal_id,
                    contribution.name,
                    contribution.score,
                    contribution.score,
                    contribution.weight,
                    contribution.weighted_points,
                    int(contribution.available),
                    _canonical_json(dict(candidate.source_refs)),
                ),
            )
    return actual_signal_id, created


def _strategy_config(value: str) -> Mapping[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("strategy config must be a JSON object")
    return parsed


def _horizons(config: Mapping[str, object]) -> tuple[int, ...]:
    values = config.get("horizons_trading_days")
    if not isinstance(values, list) or not values:
        raise ValueError("strategy has no holding horizons")
    horizons = tuple(int(value) for value in values)
    if any(value not in {5, 21, 63, 105} for value in horizons):
        raise ValueError("strategy has an unsupported holding horizon")
    return horizons


def _weights(config: Mapping[str, object]) -> Mapping[str, float]:
    values = config.get("weights")
    if not isinstance(values, dict):
        raise ValueError("strategy weights are missing")
    return {str(name): float(value) for name, value in values.items()}


def _qualification_policy(config: Mapping[str, object]) -> QualificationPolicy:
    values = config.get("qualification")
    if not isinstance(values, dict):
        raise ValueError("strategy qualification policy is missing")
    allowed = values.get("allowed_risk_levels")
    if not isinstance(allowed, list):
        raise ValueError("allowed risk levels are missing")
    return QualificationPolicy(
        minimum_score=float(values["minimum_score"]),
        minimum_data_completeness=float(values["minimum_data_completeness"]),
        allowed_risk_levels=tuple(RiskLevel(str(value)) for value in allowed),
    )


def _explanation(symbol: str, score: ScoreResult) -> str:
    ranked = sorted(
        (item for item in score.contributions if item.available),
        key=lambda item: item.weighted_points,
        reverse=True,
    )
    strongest = ", ".join(
        f"{item.name} {item.score:.1f}" for item in ranked[:3] if item.score is not None
    )
    result = (
        f"{symbol} heuristic opportunity score {score.opportunity_score:.2f}/100; "
        f"data completeness {score.data_completeness:.2f}%; risk {score.risk_level.value}."
    )
    if strongest:
        result += f" Strongest available pillars: {strongest}."
    if score.reasons:
        result += f" Rejected because: {', '.join(score.reasons)}."
    else:
        result += " Qualified under the immutable strategy thresholds."
    return result


def _require_membership(
    connection: sqlite3.Connection, snapshot_id: int, instrument_id: int
) -> None:
    row = connection.execute(
        """
        SELECT 1 FROM universe_memberships
        WHERE snapshot_id = ? AND instrument_id = ?
        """,
        (snapshot_id, instrument_id),
    ).fetchone()
    if row is None:
        raise ValueError("candidate is not a member of the scan universe")


def _audit_candidate_failure(
    connection: sqlite3.Connection,
    scan_run_id: str,
    candidate: CandidateData,
    error: str,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO audit_events(event_type, entity_type, entity_id, payload_json)
            VALUES ('scan_candidate_failed', 'scan_run', ?, ?)
            """,
            (
                scan_run_id,
                _canonical_json(
                    {
                        "error": error[:2000],
                        "instrument_id": candidate.instrument_id,
                        "symbol": candidate.symbol,
                    }
                ),
            ),
        )


def _mark_scan_failed(
    connection: sqlite3.Connection, scan_run_id: str, now: datetime, error: str
) -> None:
    with connection:
        connection.execute(
            """
            UPDATE scan_runs SET status = 'failed', completed_at = ?, error = ?
            WHERE id = ?
            """,
            (utc_iso(now), error[:2000], scan_run_id),
        )


def _scan_cutoff(connection: sqlite3.Connection, scan_run_id: str) -> str:
    row = connection.execute(
        "SELECT data_cutoff FROM scan_runs WHERE id = ?", (scan_run_id,)
    ).fetchone()
    return str(row["data_cutoff"])


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
