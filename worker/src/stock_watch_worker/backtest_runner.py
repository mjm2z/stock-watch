"""Versioned backtest dataset loading, walk-forward execution, and persistence."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .backtest import (
    BacktestResult,
    BacktestSignal,
    SimulatedTrade,
    WalkForwardSplit,
    make_walk_forward_splits,
    simulate_close_signals,
)
from .backtest_portfolio import (
    PORTFOLIO_ANALYTICS_VERSION,
    summarize_unlimited_funding_portfolio,
)
from .domain import RiskLevel
from .features import DailyBar
from .market_calendar import utc_iso
from .outcomes import summarize_outcomes
from .reliability import summarize_reliability, wilson_interval
from .strategy import calculate_notional
from .universe import load_universe_timeline


RUN_NAMESPACE = uuid.UUID("4f599749-d873-4932-a8bc-4896a7295a72")
SCORE_BUCKETS = (
    ("75-79.99", 75.0, 80.0),
    ("80-87.99", 80.0, 88.0),
    ("88-93.99", 88.0, 94.0),
    ("94-100", 94.0, 101.0),
)


@dataclass(frozen=True, slots=True)
class ScoredBacktestSignal:
    symbol: str
    signal_session: str
    horizon_trading_days: int
    opportunity_score: float
    data_completeness: float
    risk_level: RiskLevel
    vetoes: tuple[str, ...]
    universe_snapshot_id: int | None


@dataclass(frozen=True, slots=True)
class UniverseSnapshotReference:
    snapshot_id: int
    effective_at: str
    content_sha256: str
    survivorship_biased: bool


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    train_sessions: int
    validation_sessions: int
    test_sessions: int
    step_sessions: int
    expanding: bool


@dataclass(frozen=True, slots=True)
class BacktestDataset:
    dataset_version: str
    feature_set_version: str
    signals: tuple[ScoredBacktestSignal, ...]
    bars_by_symbol: Mapping[str, tuple[DailyBar, ...]]
    walk_forward: WalkForwardConfig
    content_sha256: str
    canonical_json: str
    universe_membership_mode: str
    universe_snapshots: tuple[UniverseSnapshotReference, ...]


@dataclass(frozen=True, slots=True)
class PersistedBacktestResult:
    run_id: str
    status: str
    trades: int
    rejections: int
    splits: int
    inserted: bool
    metrics: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _PreparedRejection:
    signal: ScoredBacktestSignal
    reason: str


@dataclass(frozen=True, slots=True)
class _ThresholdSelection:
    threshold: float
    underpowered: bool
    metrics: Mapping[str, Any]


def load_backtest_dataset(path: str | Path) -> BacktestDataset:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("backtest dataset must be a JSON object")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if raw.get("schema_version") != 1:
        raise ValueError("backtest dataset schema_version must be 1")
    if raw.get("scan_type") != "close":
        raise ValueError("v1 backtests only support close-generated signals")
    dataset_version = _required_text(raw.get("dataset_version"), "dataset_version")
    feature_set_version = _required_text(
        raw.get("feature_set_version"), "feature_set_version"
    )
    bars_value = raw.get("bars")
    if not isinstance(bars_value, dict):
        raise ValueError("backtest dataset bars must be an object")
    bars: dict[str, tuple[DailyBar, ...]] = {}
    for raw_symbol, raw_bars in bars_value.items():
        symbol = _symbol(raw_symbol)
        if symbol in bars:
            raise ValueError(f"duplicate backtest bar symbol {symbol}")
        if not isinstance(raw_bars, list):
            raise ValueError(f"backtest bars for {symbol} must be an array")
        bars[symbol] = tuple(_parse_bar(value) for value in raw_bars)
    if "SPY" not in bars:
        raise ValueError("backtest dataset requires SPY bars")

    signals_value = raw.get("signals")
    if not isinstance(signals_value, list):
        raise ValueError("backtest dataset signals must be an array")
    signals = tuple(_parse_signal(value) for value in signals_value)
    identities = {
        (signal.symbol, signal.signal_session, signal.horizon_trading_days)
        for signal in signals
    }
    if len(identities) != len(signals):
        raise ValueError("backtest dataset contains duplicate scored signals")

    walk_value = raw.get("walk_forward")
    if not isinstance(walk_value, dict):
        raise ValueError("backtest dataset walk_forward must be an object")
    walk = WalkForwardConfig(
        train_sessions=_positive_int(walk_value.get("train_sessions"), "train_sessions"),
        validation_sessions=_positive_int(
            walk_value.get("validation_sessions"), "validation_sessions"
        ),
        test_sessions=_positive_int(walk_value.get("test_sessions"), "test_sessions"),
        step_sessions=_positive_int(walk_value.get("step_sessions"), "step_sessions"),
        expanding=_required_bool(walk_value.get("expanding"), "expanding"),
    )
    if walk.step_sessions < walk.test_sessions:
        raise ValueError("walk_forward step_sessions cannot overlap test windows")
    membership_mode, universe_snapshots = _parse_universe_provenance(raw, signals)
    return BacktestDataset(
        dataset_version=dataset_version,
        feature_set_version=feature_set_version,
        signals=signals,
        bars_by_symbol=bars,
        walk_forward=walk,
        content_sha256=digest,
        canonical_json=canonical,
        universe_membership_mode=membership_mode,
        universe_snapshots=universe_snapshots,
    )


def run_backtest(
    connection: sqlite3.Connection,
    *,
    dataset: BacktestDataset,
    strategy_version_id: str,
    universe_snapshot_id: int,
    round_trip_cost_bps: float = 10.0,
    minimum_validation_trades: int = 20,
    minimum_reliability_trades: int = 30,
    now: datetime | None = None,
) -> PersistedBacktestResult:
    if round_trip_cost_bps < 0 or not math.isfinite(round_trip_cost_bps):
        raise ValueError("round_trip_cost_bps must be finite and non-negative")
    if minimum_validation_trades < 1:
        raise ValueError("minimum_validation_trades must be positive")
    if minimum_reliability_trades < 1:
        raise ValueError("minimum_reliability_trades must be positive")
    strategy = connection.execute(
        "SELECT config_json FROM strategy_versions WHERE id = ?",
        (strategy_version_id,),
    ).fetchone()
    if strategy is None:
        raise ValueError("strategy version does not exist")
    universe = connection.execute(
        """
        SELECT universe, survivorship_biased FROM universe_snapshots WHERE id = ?
        """,
        (universe_snapshot_id,),
    ).fetchone()
    if universe is None:
        raise ValueError("universe snapshot does not exist")
    strategy_config = json.loads(str(strategy["config_json"]))
    minimum_score, minimum_completeness, allowed_risks = _qualification(
        strategy_config
    )
    maximum_open_notional = _maximum_open_notional(strategy_config)
    threshold_candidates = _threshold_candidates(strategy_config, minimum_score)
    sessions = tuple(bar.session for bar in dataset.bars_by_symbol["SPY"])
    splits = make_walk_forward_splits(
        sessions,
        train_sessions=dataset.walk_forward.train_sessions,
        validation_sessions=dataset.walk_forward.validation_sessions,
        test_sessions=dataset.walk_forward.test_sessions,
        step_sessions=dataset.walk_forward.step_sessions,
        expanding=dataset.walk_forward.expanding,
    )
    if not splits:
        raise ValueError("backtest dataset is too short for one walk-forward split")

    run_config = {
        "minimum_score": minimum_score,
        "minimum_data_completeness": minimum_completeness,
        "allowed_risk_levels": sorted(risk.value for risk in allowed_risks),
        "round_trip_cost_bps": round_trip_cost_bps,
        "minimum_validation_trades": minimum_validation_trades,
        "minimum_reliability_trades": minimum_reliability_trades,
        "threshold_candidates": threshold_candidates,
        "maximum_open_notional_per_ticker_usd": maximum_open_notional,
        "portfolio_analytics_version": PORTFOLIO_ANALYTICS_VERSION,
        "universe_membership_mode": dataset.universe_membership_mode,
        "walk_forward": asdict(dataset.walk_forward),
    }
    config_json = _canonical_json(run_config)
    run_id = f"backtest-{uuid.uuid5(RUN_NAMESPACE, '|'.join((strategy_version_id, str(universe_snapshot_id), dataset.content_sha256, dataset.feature_set_version, config_json))).hex}"
    existing = connection.execute(
        "SELECT status, metrics_json FROM backtest_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if existing and existing["status"] == "succeeded":
        counts = _run_counts(connection, run_id)
        return PersistedBacktestResult(
            run_id,
            "succeeded",
            counts["trades"],
            counts["rejections"],
            counts["splits"],
            False,
            json.loads(str(existing["metrics_json"])),
        )

    members_by_snapshot, members, survivorship_biased = _verified_universe_memberships(
        connection,
        dataset=dataset,
        anchor_snapshot_id=universe_snapshot_id,
        anchor_universe=str(universe["universe"]),
        anchor_survivorship_biased=bool(universe["survivorship_biased"]),
    )
    selections = _select_thresholds(
        dataset,
        splits=splits,
        members_by_snapshot=members_by_snapshot,
        fallback_snapshot_id=universe_snapshot_id,
        threshold_candidates=threshold_candidates,
        fallback_threshold=minimum_score,
        minimum_completeness=minimum_completeness,
        allowed_risks=allowed_risks,
        round_trip_cost_bps=round_trip_cost_bps,
        minimum_validation_trades=minimum_validation_trades,
        maximum_open_notional_per_symbol_usd=maximum_open_notional,
    )
    test_signals: list[ScoredBacktestSignal] = []
    eligible_values: list[BacktestSignal] = []
    prepared_rejection_values: list[_PreparedRejection] = []
    for split in splits:
        split_signals = tuple(
            signal
            for signal in dataset.signals
            if split.test_start <= signal.signal_session <= split.test_end
        )
        eligible, rejected = _eligible_signals(
            split_signals,
            members_by_snapshot=members_by_snapshot,
            fallback_snapshot_id=universe_snapshot_id,
            minimum_score=selections[split.index].threshold,
            minimum_completeness=minimum_completeness,
            allowed_risks=allowed_risks,
        )
        test_signals.extend(split_signals)
        eligible_values.extend(eligible)
        prepared_rejection_values.extend(rejected)
    prepared_rejections = tuple(prepared_rejection_values)
    simulated = simulate_close_signals(
        signals=tuple(eligible_values),
        bars_by_symbol=dataset.bars_by_symbol,
        spy_bars=dataset.bars_by_symbol["SPY"],
        round_trip_cost_bps=round_trip_cost_bps,
        maximum_open_notional_per_symbol_usd=maximum_open_notional,
    )
    metrics = _aggregate_metrics(
        dataset,
        simulated,
        prepared_rejections=prepared_rejections,
        splits=splits,
        selections=selections,
        evaluated_candidates=len(test_signals),
        minimum_reliability_trades=minimum_reliability_trades,
    )
    timestamp = utc_iso(now or datetime.now(timezone.utc))
    with connection:
        if existing:
            connection.execute("DELETE FROM backtest_splits WHERE backtest_run_id = ?", (run_id,))
            connection.execute("DELETE FROM backtest_rejections WHERE backtest_run_id = ?", (run_id,))
            connection.execute("DELETE FROM backtest_trades WHERE backtest_run_id = ?", (run_id,))
            connection.execute(
                """
                UPDATE backtest_runs SET status = 'running', metrics_json = '{}',
                    started_at = ?, completed_at = NULL, error = NULL
                WHERE id = ?
                """,
                (timestamp, run_id),
            )
        else:
            connection.execute(
                """
                INSERT INTO backtest_runs(
                    id, strategy_version_id, universe_snapshot_id,
                    dataset_version, dataset_sha256, feature_set_version,
                    status, survivorship_biased, round_trip_cost_bps,
                    config_json, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    strategy_version_id,
                    universe_snapshot_id,
                    dataset.dataset_version,
                    dataset.content_sha256,
                    dataset.feature_set_version,
                    int(survivorship_biased),
                    round_trip_cost_bps,
                    config_json,
                    timestamp,
                ),
            )
        split_ids: dict[int, int] = {}
        for split in splits:
            cursor = connection.execute(
                """
                INSERT INTO backtest_splits(
                    backtest_run_id, split_index, train_start, train_end,
                    validation_start, validation_end, test_start, test_end,
                    selected_threshold, validation_metrics_json,
                    test_metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    split.index,
                    split.train_start,
                    split.train_end,
                    split.validation_start,
                    split.validation_end,
                    split.test_start,
                    split.test_end,
                    selections[split.index].threshold,
                    _canonical_json(selections[split.index].metrics),
                    _canonical_json(
                        _split_test_metrics(
                            simulated,
                            split,
                            prepared_rejections=prepared_rejections,
                        )
                    ),
                ),
            )
            split_ids[split.index] = int(cursor.lastrowid)
        for trade in simulated.trades:
            split = _split_for_session(splits, trade.signal.signal_session)
            _insert_trade(
                connection,
                run_id=run_id,
                split_id=split_ids[split.index] if split else None,
                instrument_id=members[trade.signal.symbol],
                trade=trade,
            )
        for rejection in simulated.rejected:
            source = _scored_signal(dataset.signals, rejection.signal)
            _insert_rejection(
                connection,
                run_id=run_id,
                split_id=_split_id_for_signal(splits, split_ids, source.signal_session),
                instrument_id=members.get(source.symbol),
                rejection=_PreparedRejection(source, rejection.reason),
            )
        for rejection in prepared_rejections:
            _insert_rejection(
                connection,
                run_id=run_id,
                split_id=_split_id_for_signal(
                    splits, split_ids, rejection.signal.signal_session
                ),
                instrument_id=members.get(rejection.signal.symbol),
                rejection=rejection,
            )
        connection.execute(
            """
            UPDATE backtest_runs
            SET status = 'succeeded', metrics_json = ?, completed_at = ?
            WHERE id = ?
            """,
            (_canonical_json(metrics), timestamp, run_id),
        )
        connection.execute(
            """
            INSERT INTO audit_events(event_type, entity_type, entity_id, payload_json)
            VALUES ('backtest_completed', 'backtest_run', ?, ?)
            """,
            (
                run_id,
                _canonical_json(
                    {
                        "trades": len(simulated.trades),
                        "rejections": len(simulated.rejected)
                        + len(prepared_rejections),
                        "splits": len(splits),
                    }
                ),
            ),
        )
    return PersistedBacktestResult(
        run_id,
        "succeeded",
        len(simulated.trades),
        len(simulated.rejected) + len(prepared_rejections),
        len(splits),
        True,
        metrics,
    )


def _eligible_signals(
    signals: Sequence[ScoredBacktestSignal],
    *,
    members_by_snapshot: Mapping[int, Mapping[str, int]],
    fallback_snapshot_id: int,
    minimum_score: float,
    minimum_completeness: float,
    allowed_risks: frozenset[RiskLevel],
) -> tuple[tuple[BacktestSignal, ...], tuple[_PreparedRejection, ...]]:
    eligible: list[BacktestSignal] = []
    rejected: list[_PreparedRejection] = []
    for signal in signals:
        reason = None
        snapshot_id = signal.universe_snapshot_id or fallback_snapshot_id
        members = members_by_snapshot.get(snapshot_id)
        if members is None or signal.symbol not in members:
            reason = "not_in_universe"
        elif signal.opportunity_score < minimum_score:
            reason = "score_below_threshold"
        elif signal.data_completeness < minimum_completeness:
            reason = "insufficient_data"
        elif signal.risk_level not in allowed_risks:
            reason = "risk_not_allowed"
        elif signal.vetoes:
            reason = f"veto:{signal.vetoes[0]}"
        if reason:
            rejected.append(_PreparedRejection(signal, reason))
            continue
        eligible.append(
            BacktestSignal(
                symbol=signal.symbol,
                signal_session=signal.signal_session,
                horizon_trading_days=signal.horizon_trading_days,
                opportunity_score=signal.opportunity_score,
                risk_level=signal.risk_level,
                notional_usd=calculate_notional(
                    signal.opportunity_score, signal.risk_level
                ),
            )
        )
    return tuple(eligible), tuple(rejected)


def _select_thresholds(
    dataset: BacktestDataset,
    *,
    splits: Sequence[WalkForwardSplit],
    members_by_snapshot: Mapping[int, Mapping[str, int]],
    fallback_snapshot_id: int,
    threshold_candidates: Sequence[float],
    fallback_threshold: float,
    minimum_completeness: float,
    allowed_risks: frozenset[RiskLevel],
    round_trip_cost_bps: float,
    minimum_validation_trades: int,
    maximum_open_notional_per_symbol_usd: float,
) -> dict[int, _ThresholdSelection]:
    selections: dict[int, _ThresholdSelection] = {}
    for split in splits:
        candidates = tuple(
            signal
            for signal in dataset.signals
            if split.validation_start <= signal.signal_session <= split.validation_end
        )
        threshold_metrics: dict[str, Mapping[str, Any]] = {}
        powered: list[tuple[float, BacktestResult]] = []
        for threshold in threshold_candidates:
            eligible, rejected = _eligible_signals(
                candidates,
                members_by_snapshot=members_by_snapshot,
                fallback_snapshot_id=fallback_snapshot_id,
                minimum_score=threshold,
                minimum_completeness=minimum_completeness,
                allowed_risks=allowed_risks,
            )
            result = simulate_close_signals(
                signals=eligible,
                bars_by_symbol=dataset.bars_by_symbol,
                spy_bars=dataset.bars_by_symbol["SPY"],
                round_trip_cost_bps=round_trip_cost_bps,
                maximum_open_notional_per_symbol_usd=(
                    maximum_open_notional_per_symbol_usd
                ),
            )
            summary = _summary(result)
            objective = _selection_objective(result)
            point_objective = _point_selection_objective(result)
            threshold_metrics[_threshold_key(threshold)] = {
                "trades": len(result.trades),
                "rejections": len(rejected) + len(result.rejected),
                "objective": objective,
                "point_objective": point_objective,
                "summary": summary,
            }
            if len(result.trades) >= minimum_validation_trades:
                powered.append((threshold, result))
        underpowered = not powered
        def ranking_key(value: tuple[float, BacktestResult]) -> tuple[float, float, int, float]:
            threshold, result = value
            objective = _selection_objective(result)
            return (
                objective if objective is not None else float("-inf"),
                result.summary.average_excess_return
                if result.summary
                else float("-inf"),
                len(result.trades),
                -threshold,
            )

        selected_threshold = (
            fallback_threshold
            if underpowered
            else max(powered, key=ranking_key)[0]
        )
        metrics = {
            "candidates": len(candidates),
            "minimum_required_trades": minimum_validation_trades,
            "selected_threshold": selected_threshold,
            "underpowered": underpowered,
            "selection_objective": (
                "equal_weight_wilson_95_lower_bounds_for_positive_and_beat_spy"
            ),
            "thresholds": threshold_metrics,
        }
        selections[split.index] = _ThresholdSelection(
            threshold=selected_threshold,
            underpowered=underpowered,
            metrics=metrics,
        )
    return selections


def _aggregate_metrics(
    dataset: BacktestDataset,
    result: BacktestResult,
    *,
    prepared_rejections: Sequence[_PreparedRejection],
    splits: Sequence[WalkForwardSplit],
    selections: Mapping[int, _ThresholdSelection],
    evaluated_candidates: int,
    minimum_reliability_trades: int,
) -> Mapping[str, Any]:
    horizons: dict[str, Any] = {}
    for horizon in (5, 21, 63, 105):
        trades = tuple(
            trade for trade in result.trades if trade.signal.horizon_trading_days == horizon
        )
        if trades:
            horizons[str(horizon)] = asdict(
                summarize_outcomes(trade.outcome for trade in trades)
            )
    score_buckets: dict[str, Any] = {}
    for label, lower, upper in SCORE_BUCKETS:
        trades = tuple(
            trade
            for trade in result.trades
            if lower <= trade.signal.opportunity_score < upper
        )
        if trades:
            score_buckets[label] = asdict(
                summarize_outcomes(trade.outcome for trade in trades)
            )
    rejection_counts: dict[str, int] = {}
    for reason in (
        *(rejection.reason for rejection in result.rejected),
        *(rejection.reason for rejection in prepared_rejections),
    ):
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    return {
        "candidate_signals": len(dataset.signals),
        "evaluated_test_candidates": evaluated_candidates,
        "ignored_non_test_candidates": len(dataset.signals) - evaluated_candidates,
        "walk_forward_splits": len(splits),
        "universe_membership_mode": dataset.universe_membership_mode,
        "universe_snapshots": [
            reference.snapshot_id for reference in dataset.universe_snapshots
        ],
        "underpowered_validation_splits": sum(
            selection.underpowered for selection in selections.values()
        ),
        "validation_selection_objective": (
            "equal_weight_wilson_95_lower_bounds_for_positive_and_beat_spy"
        ),
        "selected_thresholds": {
            str(index): selection.threshold
            for index, selection in sorted(selections.items())
        },
        "trades": len(result.trades),
        "rejections": len(result.rejected) + len(prepared_rejections),
        "rejections_by_reason": rejection_counts,
        "total_notional_usd": sum(trade.signal.notional_usd for trade in result.trades),
        "total_pnl_usd": sum(trade.pnl_usd for trade in result.trades),
        "summary": _summary(result),
        "by_horizon": horizons,
        "by_score_bucket": score_buckets,
        "portfolio": summarize_unlimited_funding_portfolio(
            result.trades,
            bars_by_symbol=dataset.bars_by_symbol,
            spy_bars=dataset.bars_by_symbol["SPY"],
        ),
        "out_of_sample_reliability": _reliability_metrics(
            result.trades,
            minimum_observations=minimum_reliability_trades,
        ),
    }


def _reliability_metrics(
    trades: Sequence[SimulatedTrade],
    *,
    minimum_observations: int,
) -> Mapping[str, Any]:
    by_horizon = {
        str(horizon): summarize_reliability(
            (
                trade.outcome
                for trade in trades
                if trade.signal.horizon_trading_days == horizon
            ),
            minimum_observations=minimum_observations,
        )
        for horizon in (5, 21, 63, 105)
    }
    by_score_bucket = {
        label: summarize_reliability(
            (
                trade.outcome
                for trade in trades
                if lower <= trade.signal.opportunity_score < upper
            ),
            minimum_observations=minimum_observations,
        )
        for label, lower, upper in SCORE_BUCKETS
    }
    by_horizon_and_score_bucket = {
        str(horizon): {
            label: summarize_reliability(
                (
                    trade.outcome
                    for trade in trades
                    if trade.signal.horizon_trading_days == horizon
                    and lower <= trade.signal.opportunity_score < upper
                ),
                minimum_observations=minimum_observations,
            )
            for label, lower, upper in SCORE_BUCKETS
        }
        for horizon in (5, 21, 63, 105)
    }
    return {
        "basis": "untouched_walk_forward_test_trades",
        "selection_conditioned": True,
        "probability_forecasts_available": False,
        "probability_forecasts_reason": (
            "Empirical cohort rates are not per-signal calibrated probabilities."
        ),
        "overall": summarize_reliability(
            (trade.outcome for trade in trades),
            minimum_observations=minimum_observations,
        ),
        "by_horizon": by_horizon,
        "by_score_bucket": by_score_bucket,
        "by_horizon_and_score_bucket": by_horizon_and_score_bucket,
    }


def _split_test_metrics(
    result: BacktestResult,
    split: WalkForwardSplit,
    *,
    prepared_rejections: Sequence[_PreparedRejection],
) -> Mapping[str, Any]:
    trades = tuple(
        trade
        for trade in result.trades
        if split.test_start <= trade.signal.signal_session <= split.test_end
    )
    rejections = tuple(
        rejection
        for rejection in result.rejected
        if split.test_start <= rejection.signal.signal_session <= split.test_end
    )
    eligibility_rejections = sum(
        split.test_start <= rejection.signal.signal_session <= split.test_end
        for rejection in prepared_rejections
    )
    return {
        "trades": len(trades),
        "rejections": len(rejections) + eligibility_rejections,
        "summary": asdict(summarize_outcomes(trade.outcome for trade in trades))
        if trades
        else None,
    }


def _insert_trade(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    split_id: int | None,
    instrument_id: int,
    trade: SimulatedTrade,
) -> None:
    outcome = trade.outcome
    connection.execute(
        """
        INSERT INTO backtest_trades(
            backtest_run_id, backtest_split_id, instrument_id, signal_session,
            horizon_trading_days, opportunity_score, risk_level, notional_usd,
            entry_session, exit_session, entry_price, exit_price, quantity,
            gross_return, modeled_cost_return, net_return, spy_return,
            excess_return, beat_spy, terminal_positive, terminal_at_least_5,
            terminal_at_least_10, touched_5, touched_10,
            maximum_favorable_excursion, maximum_adverse_excursion, pnl_usd
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            split_id,
            instrument_id,
            trade.signal.signal_session,
            trade.signal.horizon_trading_days,
            trade.signal.opportunity_score,
            trade.signal.risk_level.value,
            trade.signal.notional_usd,
            trade.entry_session,
            trade.exit_session,
            trade.entry_price,
            trade.exit_price,
            trade.quantity,
            outcome.gross_return,
            outcome.modeled_cost_return,
            outcome.net_return,
            outcome.spy_return,
            outcome.excess_return,
            int(outcome.beat_spy),
            int(outcome.terminal_positive),
            int(outcome.terminal_at_least_5),
            int(outcome.terminal_at_least_10),
            int(outcome.touched_5),
            int(outcome.touched_10),
            outcome.maximum_favorable_excursion,
            outcome.maximum_adverse_excursion,
            trade.pnl_usd,
        ),
    )


def _insert_rejection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    split_id: int | None,
    instrument_id: int | None,
    rejection: _PreparedRejection,
) -> None:
    signal = rejection.signal
    connection.execute(
        """
        INSERT INTO backtest_rejections(
            backtest_run_id, backtest_split_id, instrument_id, symbol,
            signal_session, horizon_trading_days, opportunity_score,
            risk_level, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            split_id,
            instrument_id,
            signal.symbol,
            signal.signal_session,
            signal.horizon_trading_days,
            signal.opportunity_score,
            signal.risk_level.value,
            rejection.reason,
        ),
    )


def _parse_bar(value: Any) -> DailyBar:
    if not isinstance(value, dict):
        raise ValueError("backtest bar must be an object")
    session = _iso_date(value.get("session"), "bar session")
    return DailyBar(
        session=session,
        open=_finite_number(value.get("open"), "bar open"),
        high=_finite_number(value.get("high"), "bar high"),
        low=_finite_number(value.get("low"), "bar low"),
        close=_finite_number(value.get("close"), "bar close"),
        volume=_finite_number(value.get("volume"), "bar volume"),
    )


def _parse_signal(value: Any) -> ScoredBacktestSignal:
    if not isinstance(value, dict):
        raise ValueError("backtest signal must be an object")
    try:
        risk = RiskLevel(_required_text(value.get("risk_level"), "signal risk_level"))
    except ValueError as error:
        raise ValueError("backtest signal risk_level is invalid") from error
    horizon = _positive_int(value.get("horizon_trading_days"), "signal horizon")
    if horizon not in {5, 21, 63, 105}:
        raise ValueError("backtest signal horizon is unsupported")
    score = _finite_number(value.get("opportunity_score"), "signal score")
    completeness = _finite_number(
        value.get("data_completeness"), "signal data completeness"
    )
    if not 0 <= score <= 100 or not 0 <= completeness <= 100:
        raise ValueError("backtest signal score and completeness must be 0-100")
    raw_vetoes = value.get("vetoes", [])
    if not isinstance(raw_vetoes, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw_vetoes
    ):
        raise ValueError("backtest signal vetoes must be non-empty strings")
    return ScoredBacktestSignal(
        symbol=_symbol(value.get("symbol")),
        signal_session=_iso_date(value.get("signal_session"), "signal session"),
        horizon_trading_days=horizon,
        opportunity_score=score,
        data_completeness=completeness,
        risk_level=risk,
        vetoes=tuple(item.strip() for item in raw_vetoes),
        universe_snapshot_id=(
            _positive_int(value.get("universe_snapshot_id"), "signal universe snapshot")
            if value.get("universe_snapshot_id") is not None
            else None
        ),
    )


def _parse_universe_provenance(
    raw: Mapping[str, Any],
    signals: Sequence[ScoredBacktestSignal],
) -> tuple[str, tuple[UniverseSnapshotReference, ...]]:
    provenance = raw.get("provenance")
    if provenance is None:
        return "fixed_snapshot", ()
    if not isinstance(provenance, dict):
        raise ValueError("backtest provenance must be an object")
    mode = provenance.get("universe_membership_mode", "fixed_snapshot")
    if mode not in {"fixed_snapshot", "point_in_time"}:
        raise ValueError("backtest universe membership mode is invalid")
    raw_references = provenance.get("universe_snapshots", [])
    if not isinstance(raw_references, list):
        raise ValueError("backtest universe snapshots must be an array")
    references: list[UniverseSnapshotReference] = []
    for value in raw_references:
        if not isinstance(value, dict):
            raise ValueError("backtest universe snapshot reference must be an object")
        references.append(
            UniverseSnapshotReference(
                snapshot_id=_positive_int(value.get("id"), "universe snapshot id"),
                effective_at=_required_text(
                    value.get("effective_at"), "universe snapshot effective_at"
                ),
                content_sha256=_required_text(
                    value.get("content_sha256"), "universe snapshot content_sha256"
                ),
                survivorship_biased=_required_bool(
                    value.get("survivorship_biased"),
                    "universe snapshot survivorship_biased",
                ),
            )
        )
    if len({value.snapshot_id for value in references}) != len(references):
        raise ValueError("backtest universe snapshot references contain duplicates")
    signal_snapshot_ids = {value.universe_snapshot_id for value in signals}
    if mode == "point_in_time":
        if not references:
            raise ValueError("point-in-time backtest requires universe snapshot references")
        if not signals:
            raise ValueError("point-in-time backtest requires scored signals")
        if None in signal_snapshot_ids:
            raise ValueError("point-in-time backtest signals require universe_snapshot_id")
        reference_ids = {value.snapshot_id for value in references}
        if not signal_snapshot_ids <= reference_ids:
            raise ValueError("backtest signal references an undeclared universe snapshot")
    elif len(references) > 1:
        raise ValueError("fixed-snapshot backtest cannot declare multiple snapshots")
    return str(mode), tuple(references)


def _qualification(
    config: Mapping[str, Any],
) -> tuple[float, float, frozenset[RiskLevel]]:
    qualification = config.get("qualification")
    if not isinstance(qualification, dict):
        raise ValueError("strategy qualification configuration is missing")
    score = _finite_number(qualification.get("minimum_score"), "minimum score")
    completeness = _finite_number(
        qualification.get("minimum_data_completeness"), "minimum completeness"
    )
    raw_risks = qualification.get("allowed_risk_levels")
    if not isinstance(raw_risks, list):
        raise ValueError("strategy allowed risk levels are missing")
    try:
        risks = frozenset(RiskLevel(str(value)) for value in raw_risks)
    except ValueError as error:
        raise ValueError("strategy allowed risk levels are invalid") from error
    return score, completeness, risks


def _threshold_candidates(
    config: Mapping[str, Any], minimum_score: float
) -> tuple[float, ...]:
    sizing = config.get("sizing")
    raw_bands = sizing.get("bands") if isinstance(sizing, dict) else None
    values = {minimum_score}
    if isinstance(raw_bands, list):
        for band in raw_bands:
            if not isinstance(band, dict):
                continue
            value = _finite_number(
                band.get("minimum_score"), "sizing band minimum score"
            )
            if minimum_score <= value <= 100:
                values.add(value)
    return tuple(sorted(values))


def _maximum_open_notional(config: Mapping[str, Any]) -> float:
    sizing = config.get("sizing")
    if not isinstance(sizing, dict):
        raise ValueError("strategy sizing configuration is missing")
    value = _finite_number(
        sizing.get("maximum_open_notional_per_ticker_usd"),
        "maximum open notional per ticker",
    )
    if value <= 0:
        raise ValueError("maximum open notional per ticker must be positive")
    return value


def _selection_objective(result: BacktestResult) -> float | None:
    if result.summary is None:
        return None
    observations = len(result.trades)
    positive_lower = wilson_interval(
        sum(trade.outcome.terminal_positive for trade in result.trades),
        observations,
    )[0]
    beat_spy_lower = wilson_interval(
        sum(trade.outcome.beat_spy for trade in result.trades),
        observations,
    )[0]
    return (positive_lower + beat_spy_lower) / 2.0


def _point_selection_objective(result: BacktestResult) -> float | None:
    if result.summary is None:
        return None
    return (
        result.summary.positive_rate + result.summary.beat_spy_rate
    ) / 2.0


def _threshold_key(value: float) -> str:
    return format(value, "g")


def _universe_members(
    connection: sqlite3.Connection, snapshot_id: int
) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT instruments.symbol, instruments.id
        FROM universe_memberships
        JOIN instruments ON instruments.id = universe_memberships.instrument_id
        WHERE universe_memberships.snapshot_id = ?
        """,
        (snapshot_id,),
    ).fetchall()
    if not rows:
        raise ValueError("universe snapshot has no members")
    return {str(row["symbol"]): int(row["id"]) for row in rows}


def _verified_universe_memberships(
    connection: sqlite3.Connection,
    *,
    dataset: BacktestDataset,
    anchor_snapshot_id: int,
    anchor_universe: str,
    anchor_survivorship_biased: bool,
) -> tuple[dict[int, dict[str, int]], dict[str, int], bool]:
    references = dataset.universe_snapshots
    if dataset.universe_membership_mode == "fixed_snapshot":
        if references and references[0].snapshot_id != anchor_snapshot_id:
            raise ValueError("fixed backtest universe snapshot does not match anchor")
        signal_ids = {
            signal.universe_snapshot_id
            for signal in dataset.signals
            if signal.universe_snapshot_id is not None
        }
        if signal_ids and signal_ids != {anchor_snapshot_id}:
            raise ValueError("fixed backtest signal universe snapshot does not match anchor")
        references_to_verify = references
        snapshot_ids = (anchor_snapshot_id,)
    else:
        references_to_verify = references
        signal_dates = [date.fromisoformat(signal.signal_session) for signal in dataset.signals]
        database_timeline = load_universe_timeline(
            connection,
            anchor_snapshot_id=anchor_snapshot_id,
            start=min(signal_dates),
            end=max(signal_dates),
        )
        expected_snapshot_ids = tuple(
            snapshot.snapshot_id for snapshot in database_timeline
        )
        declared_snapshot_ids = tuple(
            reference.snapshot_id for reference in references
        )
        if declared_snapshot_ids != expected_snapshot_ids:
            raise ValueError(
                "point-in-time backtest snapshot timeline is incomplete or out of order"
            )
        snapshot_ids = declared_snapshot_ids

    reference_by_id = {
        reference.snapshot_id: reference for reference in references_to_verify
    }
    members_by_snapshot: dict[int, dict[str, int]] = {}
    actual_biases: list[bool] = []
    effective_dates: dict[int, date] = {}
    for snapshot_id in snapshot_ids:
        row = connection.execute(
            """
            SELECT universe, effective_at, content_sha256, survivorship_biased
            FROM universe_snapshots WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"backtest universe snapshot {snapshot_id} does not exist")
        if str(row["universe"]) != anchor_universe:
            raise ValueError("backtest universe snapshots do not share the anchor universe")
        reference = reference_by_id.get(snapshot_id)
        if reference and (
            reference.effective_at != str(row["effective_at"])
            or reference.content_sha256 != str(row["content_sha256"])
            or reference.survivorship_biased != bool(row["survivorship_biased"])
        ):
            raise ValueError(f"backtest universe snapshot {snapshot_id} provenance mismatch")
        members_by_snapshot[snapshot_id] = _universe_members(connection, snapshot_id)
        actual_biases.append(bool(row["survivorship_biased"]))
        try:
            effective_dates[snapshot_id] = date.fromisoformat(str(row["effective_at"])[:10])
        except ValueError as error:
            raise ValueError(
                f"backtest universe snapshot {snapshot_id} effective_at is invalid"
            ) from error
    if dataset.universe_membership_mode == "point_in_time":
        if len(set(effective_dates.values())) != len(effective_dates):
            raise ValueError("point-in-time backtest snapshots have ambiguous effective dates")
        for signal in dataset.signals:
            signal_date = date.fromisoformat(signal.signal_session)
            eligible_snapshots = [
                (effective_date, snapshot_id)
                for snapshot_id, effective_date in effective_dates.items()
                if effective_date <= signal_date
            ]
            if not eligible_snapshots:
                raise ValueError(
                    f"point-in-time backtest has no universe coverage for {signal.signal_session}"
                )
            expected_snapshot_id = max(eligible_snapshots)[1]
            if signal.universe_snapshot_id != expected_snapshot_id:
                raise ValueError(
                    "point-in-time backtest signal does not use the latest effective universe snapshot"
                )
    members = {
        symbol: instrument_id
        for snapshot_members in members_by_snapshot.values()
        for symbol, instrument_id in snapshot_members.items()
    }
    survivorship_biased = (
        any(actual_biases)
        if dataset.universe_membership_mode == "point_in_time"
        else anchor_survivorship_biased
    )
    return members_by_snapshot, members, survivorship_biased


def _scored_signal(
    values: Sequence[ScoredBacktestSignal], signal: BacktestSignal
) -> ScoredBacktestSignal:
    return next(
        value
        for value in values
        if (
            value.symbol,
            value.signal_session,
            value.horizon_trading_days,
        )
        == (signal.symbol, signal.signal_session, signal.horizon_trading_days)
    )


def _split_for_session(
    splits: Sequence[WalkForwardSplit], session: str
) -> WalkForwardSplit | None:
    return next(
        (split for split in splits if split.test_start <= session <= split.test_end),
        None,
    )


def _split_id_for_signal(
    splits: Sequence[WalkForwardSplit], split_ids: Mapping[int, int], session: str
) -> int | None:
    split = _split_for_session(splits, session)
    return split_ids[split.index] if split else None


def _summary(result: BacktestResult) -> Mapping[str, Any] | None:
    return asdict(result.summary) if result.summary else None


def _run_counts(connection: sqlite3.Connection, run_id: str) -> dict[str, int]:
    return {
        name: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE backtest_run_id = ?", (run_id,)
            ).fetchone()[0]
        )
        for name, table in (
            ("trades", "backtest_trades"),
            ("rejections", "backtest_rejections"),
            ("splits", "backtest_splits"),
        )
    }


def _symbol(value: Any) -> str:
    symbol = _required_text(value, "symbol").upper()
    if any(character.isspace() for character in symbol):
        raise ValueError("backtest symbol cannot contain whitespace")
    return symbol


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"backtest {name} must be a non-empty string")
    return value.strip()


def _iso_date(value: Any, name: str) -> str:
    text = _required_text(value, name)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as error:
        raise ValueError(f"backtest {name} must be an ISO date") from error


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"backtest {name} must be a positive integer")
    return value


def _required_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"backtest {name} must be a boolean")
    return value


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"backtest {name} must be finite")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"backtest {name} must be finite") from error
    if not math.isfinite(parsed):
        raise ValueError(f"backtest {name} must be finite")
    return parsed


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
