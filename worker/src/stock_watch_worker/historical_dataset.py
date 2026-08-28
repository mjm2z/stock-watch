"""Build point-in-time scored close-signal manifests from durable research data."""

from __future__ import annotations

import bisect
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .domain import RiskLevel, ScoreRequest, SignalDecision
from .features import DailyBar, build_feature_set
from .sec_fundamentals import extract_fundamentals
from .sentiment import MODEL_VERSION
from .strategy import QualificationPolicy, calculate_score
from .universe import UniverseTimelineSnapshot, load_universe_timeline


FEATURE_SET_VERSION = "features-v0"
MINIMUM_HISTORY_SESSIONS = 200


@dataclass(frozen=True, slots=True)
class HistoricalDatasetStats:
    sessions_evaluated: int
    instruments: int
    scored_symbol_sessions: int
    signals: int
    qualified_signals: int
    skipped_insufficient_history: int
    fundamental_observations: int
    news_observations: int


@dataclass(frozen=True, slots=True)
class HistoricalDatasetResult:
    manifest: Mapping[str, Any]
    stats: HistoricalDatasetStats


def build_historical_backtest_dataset(
    connection: sqlite3.Connection,
    *,
    strategy_version_id: str,
    universe_snapshot_id: int,
    start: date,
    end: date,
    signal_stride_sessions: int = 5,
    history_sessions: int = 260,
    maximum_signals: int = 1_000_000,
    point_in_time_universe: bool = False,
    historical_news_ingestion_id: int | None = None,
    historical_calendar_ingestion_id: int | None = None,
    news_lookback_days: int = 3,
) -> HistoricalDatasetResult:
    if start > end:
        raise ValueError("historical dataset start must not be after end")
    if signal_stride_sessions < 1:
        raise ValueError("signal stride must be positive")
    if history_sessions < MINIMUM_HISTORY_SESSIONS:
        raise ValueError("historical dataset requires at least 200 history sessions")
    if maximum_signals < 1:
        raise ValueError("maximum_signals must be positive")
    if news_lookback_days < 1 or news_lookback_days > 30:
        raise ValueError("historical news lookback days must be between 1 and 30")
    if historical_news_ingestion_id is not None and historical_calendar_ingestion_id is None:
        raise ValueError("historical news requires a historical calendar ingestion")

    strategy = connection.execute(
        "SELECT config_json, config_sha256 FROM strategy_versions WHERE id = ?",
        (strategy_version_id,),
    ).fetchone()
    if strategy is None:
        raise ValueError("historical dataset strategy version does not exist")
    config = json.loads(str(strategy["config_json"]))
    if not isinstance(config, dict):
        raise ValueError("historical dataset strategy config is malformed")
    weights, policy, horizons = _strategy_inputs(config)
    universe = connection.execute(
        """
        SELECT effective_at, content_sha256, survivorship_biased
        FROM universe_snapshots WHERE id = ?
        """,
        (universe_snapshot_id,),
    ).fetchone()
    if universe is None:
        raise ValueError("historical dataset universe snapshot does not exist")
    if point_in_time_universe:
        timeline = load_universe_timeline(
            connection,
            anchor_snapshot_id=universe_snapshot_id,
            start=start,
            end=end,
        )
        members = tuple(sorted({symbol for item in timeline for symbol in item.members}))
    else:
        members = _members(connection, universe_snapshot_id)
        timeline = ()
    bars_by_symbol = _load_daily_bars(connection, (*members, "SPY"))
    spy_bars = bars_by_symbol.get("SPY", ())
    if not spy_bars:
        raise ValueError("historical dataset SPY bars are missing")
    spy_sessions = tuple(bar.session for bar in spy_bars)
    evaluation_indices = tuple(
        index
        for index, session in enumerate(spy_sessions)
        if start.isoformat() <= session <= end.isoformat()
    )[::signal_stride_sessions]
    if not evaluation_indices:
        raise ValueError("historical dataset has no SPY sessions in the requested range")
    if evaluation_indices[0] + 1 < history_sessions:
        raise ValueError(
            "historical dataset lacks the requested pre-signal history window"
        )
    maximum_horizon = max(horizons)
    if evaluation_indices[-1] + maximum_horizon >= len(spy_sessions):
        raise ValueError(
            "historical dataset lacks future SPY sessions through the maximum horizon"
        )
    session_closes, calendar_provenance = _historical_session_closes(
        connection,
        ingestion_id=historical_calendar_ingestion_id,
        required_sessions=tuple(spy_sessions[index] for index in evaluation_indices),
    )
    memberships_by_session = {
        spy_sessions[index]: _membership_for_session(
            timeline,
            session=spy_sessions[index],
            fixed_snapshot_id=universe_snapshot_id,
            fixed_members=members,
        )
        for index in evaluation_indices
    }
    estimated_signals = sum(
        len(snapshot.members) * len(horizons)
        for snapshot in memberships_by_session.values()
    )
    if estimated_signals > maximum_signals:
        raise ValueError(
            f"historical dataset would exceed maximum_signals ({estimated_signals})"
        )

    facts = _latest_company_facts(connection, members)
    news_by_symbol, news_provenance = _historical_news(
        connection,
        members=members,
        ingestion_id=historical_news_ingestion_id,
        required_start=start - timedelta(days=news_lookback_days),
        required_end=end,
    )
    symbol_sessions = {
        symbol: tuple(bar.session for bar in bars_by_symbol.get(symbol, ()))
        for symbol in members
    }
    signals: list[dict[str, Any]] = []
    used_symbols: set[str] = set()
    qualified = 0
    skipped_history = 0
    fundamental_observations = 0
    news_observations = 0
    scored_symbol_sessions = 0
    for spy_index in evaluation_indices:
        session = spy_sessions[spy_index]
        spy_history = spy_bars[spy_index - history_sessions + 1 : spy_index + 1]
        membership = memberships_by_session[session]
        for symbol in membership.members:
            stock_bars = bars_by_symbol.get(symbol, ())
            stock_index = bisect.bisect_right(symbol_sessions[symbol], session)
            stock_history = stock_bars[
                max(0, stock_index - history_sessions) : stock_index
            ]
            if len(stock_history) < MINIMUM_HISTORY_SESSIONS:
                skipped_history += 1
                continue
            vetoes: list[str] = []
            fundamentals = None
            company_facts = facts.get(symbol)
            if company_facts is not None:
                try:
                    fundamentals = extract_fundamentals(
                        company_facts,
                        as_of=session,
                        price=stock_history[-1].close,
                    ).inputs
                    if any(
                        value is not None
                        for value in (
                            fundamentals.revenue_growth,
                            fundamentals.net_margin,
                            fundamentals.free_cash_flow_margin,
                            fundamentals.debt_to_equity,
                            fundamentals.price_to_earnings,
                            fundamentals.free_cash_flow_yield,
                        )
                    ):
                        fundamental_observations += 1
                except (TypeError, ValueError):
                    vetoes.append("fundamental_parse_error")
            features = build_feature_set(
                as_of=session,
                bars=stock_history,
                spy_bars=spy_history,
                fundamentals=fundamentals,
                news_sentiments=(
                    sentiments := (
                        _news_sentiments_at_close(
                            news_by_symbol.get(symbol, ()),
                            cutoff=session_closes[session],
                            lookback_days=news_lookback_days,
                        )
                        if historical_news_ingestion_id is not None
                        else ()
                    )
                ),
                news_coverage_complete=historical_news_ingestion_id is not None,
            )
            news_observations += len(sentiments)
            score = calculate_score(
                ScoreRequest(
                    ticker=symbol,
                    pillars=features.pillars,
                    risk_level=features.risk_level,
                    vetoes=tuple(vetoes),
                    in_universe=True,
                ),
                weights=weights,
                policy=policy,
            )
            scored_symbol_sessions += 1
            used_symbols.add(symbol)
            for horizon in horizons:
                signals.append(
                    {
                        "symbol": symbol,
                        "signal_session": session,
                        "horizon_trading_days": horizon,
                        "opportunity_score": score.opportunity_score,
                        "data_completeness": score.data_completeness,
                        "risk_level": score.risk_level.value,
                        "vetoes": list(vetoes),
                        "universe_snapshot_id": membership.snapshot_id,
                    }
                )
                qualified += int(score.decision is SignalDecision.QUALIFIED)

    first_bar_session = spy_sessions[evaluation_indices[0] - history_sessions + 1]
    last_bar_session = spy_sessions[evaluation_indices[-1] + maximum_horizon]
    output_bars = {
        symbol: [
            asdict(bar)
            for bar in bars_by_symbol[symbol]
            if first_bar_session <= bar.session <= last_bar_session
        ]
        for symbol in ("SPY", *sorted(used_symbols))
    }
    dataset_version = (
        f"historical-close-v2:snapshot={universe_snapshot_id}:"
        f"membership={'point-in-time' if point_in_time_universe else 'fixed'}:"
        f"news={historical_news_ingestion_id or 'unavailable'}:"
        f"calendar={historical_calendar_ingestion_id or 'unavailable'}:"
        f"start={start.isoformat()}:end={end.isoformat()}:"
        f"stride={signal_stride_sessions}"
    )
    manifest: Mapping[str, Any] = {
        "schema_version": 1,
        "dataset_version": dataset_version,
        "feature_set_version": FEATURE_SET_VERSION,
        "scan_type": "close",
        "walk_forward": _walk_forward_config(
            total_sessions=(evaluation_indices[-1] + maximum_horizon)
            - (evaluation_indices[0] - history_sessions + 1)
            + 1,
            train_sessions=history_sessions - 1,
            evaluation_span_sessions=evaluation_indices[-1]
            - evaluation_indices[0]
            + 1,
        ),
        "provenance": {
            "strategy_version_id": strategy_version_id,
            "strategy_sha256": str(strategy["config_sha256"]),
            "universe_snapshot_id": universe_snapshot_id,
            "universe_effective_at": str(universe["effective_at"]),
            "universe_sha256": str(universe["content_sha256"]),
            "universe_membership_mode": (
                "point_in_time" if point_in_time_universe else "fixed_snapshot"
            ),
            "universe_snapshots": _timeline_provenance(
                timeline,
                fixed_snapshot_id=universe_snapshot_id,
                fixed_effective_at=str(universe["effective_at"]),
                fixed_sha256=str(universe["content_sha256"]),
                fixed_survivorship_biased=bool(universe["survivorship_biased"]),
            ),
            "survivorship_biased": (
                any(item.survivorship_biased for item in timeline)
                if point_in_time_universe
                else bool(universe["survivorship_biased"])
            ),
            "bar_provider": "alpaca",
            "bar_adjustment": "all",
            "news_coverage_complete": historical_news_ingestion_id is not None,
            "news_ingestion": news_provenance,
            "calendar_ingestion": calendar_provenance,
            "news_lookback_calendar_days": news_lookback_days,
            "news_cutoff_policy": (
                "provider exchange-session close"
                if historical_news_ingestion_id is not None
                else None
            ),
            "news_sentiment_model": MODEL_VERSION,
            "fundamental_policy": (
                "latest SEC CompanyFacts document with every fact filtered by filed date"
            ),
            "signal_stride_sessions": signal_stride_sessions,
        },
        "bars": output_bars,
        "signals": signals,
    }
    return HistoricalDatasetResult(
        manifest=manifest,
        stats=HistoricalDatasetStats(
            sessions_evaluated=len(evaluation_indices),
            instruments=len(members),
            scored_symbol_sessions=scored_symbol_sessions,
            signals=len(signals),
            qualified_signals=qualified,
            skipped_insufficient_history=skipped_history,
            fundamental_observations=fundamental_observations,
            news_observations=news_observations,
        ),
    )


def write_historical_backtest_dataset(
    path: str | Path, result: HistoricalDatasetResult
) -> int:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        result.manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    try:
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.write("\n")
    except FileExistsError as error:
        raise FileExistsError(
            f"historical dataset output already exists: {destination}"
        ) from error
    return len(encoded.encode("utf-8")) + 1


def _strategy_inputs(
    config: Mapping[str, Any],
) -> tuple[Mapping[str, float], QualificationPolicy, tuple[int, ...]]:
    raw_weights = config.get("weights")
    raw_qualification = config.get("qualification")
    raw_horizons = config.get("horizons_trading_days")
    if not isinstance(raw_weights, dict) or not isinstance(raw_qualification, dict):
        raise ValueError("historical dataset strategy scoring config is malformed")
    if not isinstance(raw_horizons, list):
        raise ValueError("historical dataset strategy horizons are malformed")
    try:
        weights = {str(name): float(value) for name, value in raw_weights.items()}
        allowed_risks = tuple(
            RiskLevel(str(value))
            for value in raw_qualification["allowed_risk_levels"]
        )
        policy = QualificationPolicy(
            minimum_score=float(raw_qualification["minimum_score"]),
            minimum_data_completeness=float(
                raw_qualification["minimum_data_completeness"]
            ),
            allowed_risk_levels=allowed_risks,
        )
        horizons = tuple(int(value) for value in raw_horizons)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("historical dataset strategy config is malformed") from error
    return weights, policy, horizons


def _members(
    connection: sqlite3.Connection, universe_snapshot_id: int
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT instruments.symbol
        FROM universe_memberships
        JOIN instruments ON instruments.id = universe_memberships.instrument_id
        WHERE universe_memberships.snapshot_id = ?
        ORDER BY instruments.symbol
        """,
        (universe_snapshot_id,),
    ).fetchall()
    symbols = tuple(str(row["symbol"]) for row in rows)
    if not symbols:
        raise ValueError("historical dataset universe snapshot has no members")
    return symbols


def _membership_for_session(
    timeline: Sequence[UniverseTimelineSnapshot],
    *,
    session: str,
    fixed_snapshot_id: int,
    fixed_members: Sequence[str],
) -> UniverseTimelineSnapshot:
    if not timeline:
        return UniverseTimelineSnapshot(
            snapshot_id=fixed_snapshot_id,
            effective_at="fixed",
            effective_date=date.min,
            content_sha256="fixed",
            survivorship_biased=True,
            members=tuple(fixed_members),
        )
    session_date = date.fromisoformat(session)
    matches = [item for item in timeline if item.effective_date <= session_date]
    if not matches:
        raise ValueError(f"historical dataset has no universe snapshot for {session}")
    return matches[-1]


def _timeline_provenance(
    timeline: Sequence[UniverseTimelineSnapshot],
    *,
    fixed_snapshot_id: int,
    fixed_effective_at: str,
    fixed_sha256: str,
    fixed_survivorship_biased: bool,
) -> list[Mapping[str, Any]]:
    if timeline:
        return [
            {
                "id": item.snapshot_id,
                "effective_at": item.effective_at,
                "content_sha256": item.content_sha256,
                "survivorship_biased": item.survivorship_biased,
            }
            for item in timeline
        ]
    return [
        {
            "id": fixed_snapshot_id,
            "effective_at": fixed_effective_at,
            "content_sha256": fixed_sha256,
            "survivorship_biased": fixed_survivorship_biased,
        }
    ]


def _load_daily_bars(
    connection: sqlite3.Connection, symbols: Sequence[str]
) -> dict[str, tuple[DailyBar, ...]]:
    placeholders = ",".join("?" for _ in symbols)
    rows = connection.execute(
        f"""
        SELECT instruments.symbol, bars.timestamp, bars.open, bars.high,
               bars.low, bars.close, bars.volume
        FROM market_bars AS bars
        JOIN instruments ON instruments.id = bars.instrument_id
        WHERE instruments.symbol IN ({placeholders})
          AND bars.timeframe = '1Day' AND bars.adjustment = 'all'
          AND bars.provider = 'alpaca'
        ORDER BY instruments.symbol, bars.timestamp
        """,
        tuple(symbols),
    ).fetchall()
    grouped: dict[str, list[DailyBar]] = {}
    seen: set[tuple[str, str]] = set()
    for row in rows:
        symbol = str(row["symbol"])
        session = str(row["timestamp"])[:10]
        identity = (symbol, session)
        if identity in seen:
            raise ValueError(f"historical dataset has duplicate daily bar {symbol} {session}")
        seen.add(identity)
        grouped.setdefault(symbol, []).append(
            DailyBar(
                session=session,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    return {symbol: tuple(values) for symbol, values in grouped.items()}


def _latest_company_facts(
    connection: sqlite3.Connection, symbols: Sequence[str]
) -> dict[str, Mapping[str, Any]]:
    placeholders = ",".join("?" for _ in symbols)
    rows = connection.execute(
        f"""
        SELECT instruments.symbol, documents.facts_json
        FROM company_fact_documents AS documents
        JOIN instruments ON instruments.id = documents.instrument_id
        WHERE instruments.symbol IN ({placeholders})
        ORDER BY instruments.symbol, documents.captured_at DESC, documents.id DESC
        """,
        tuple(symbols),
    ).fetchall()
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        symbol = str(row["symbol"])
        if symbol in result:
            continue
        value = json.loads(str(row["facts_json"]))
        if isinstance(value, dict):
            result[symbol] = value
    return result


def _historical_news(
    connection: sqlite3.Connection,
    *,
    members: Sequence[str],
    ingestion_id: int | None,
    required_start: date,
    required_end: date,
) -> tuple[dict[str, tuple[tuple[datetime, float], ...]], Mapping[str, Any] | None]:
    if ingestion_id is None:
        return {}, None
    ingestion = connection.execute(
        """
        SELECT version, status, metadata_json
        FROM data_ingestions
        WHERE id = ? AND dataset = 'historical_news' AND provider = 'alpaca'
        """,
        (ingestion_id,),
    ).fetchone()
    if ingestion is None:
        raise ValueError("historical news ingestion does not exist")
    if str(ingestion["status"]) != "succeeded":
        raise ValueError("historical news ingestion has not succeeded")
    metadata = json.loads(str(ingestion["metadata_json"]))
    if not isinstance(metadata, dict) or not metadata.get("news_coverage_complete"):
        raise ValueError("historical news ingestion does not claim complete coverage")
    if metadata.get("sentiment_model") != MODEL_VERSION:
        raise ValueError("historical news ingestion sentiment model does not match")
    try:
        coverage_start = date.fromisoformat(str(metadata["start"]))
        coverage_end = date.fromisoformat(str(metadata["end"]))
        covered_symbols = {str(value) for value in metadata["symbol_list"]}
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("historical news ingestion metadata is malformed") from error
    if coverage_start > required_start or coverage_end < required_end:
        raise ValueError("historical news ingestion does not cover the requested dates")
    missing_symbols = set(members) - covered_symbols
    if missing_symbols:
        raise ValueError("historical news ingestion does not cover every universe symbol")
    placeholders = ",".join("?" for _ in members)
    rows = connection.execute(
        f"""
        SELECT instruments.symbol, articles.published_at, links.sentiment
        FROM news_instruments AS links
        JOIN news_articles AS articles ON articles.id = links.news_id
        JOIN instruments ON instruments.id = links.instrument_id
        WHERE instruments.symbol IN ({placeholders})
          AND articles.provider = 'alpaca'
          AND links.sentiment_model = ?
        ORDER BY instruments.symbol, articles.published_at, articles.id
        """,
        (*members, MODEL_VERSION),
    ).fetchall()
    grouped: dict[str, list[tuple[datetime, float]]] = {}
    for row in rows:
        published_at = _aware_datetime(str(row["published_at"]))
        if coverage_start <= published_at.date() <= coverage_end:
            grouped.setdefault(str(row["symbol"]), []).append(
                (published_at, float(row["sentiment"]))
            )
    return (
        {symbol: tuple(values) for symbol, values in grouped.items()},
        {
            "id": ingestion_id,
            "version": str(ingestion["version"]),
            "start": coverage_start.isoformat(),
            "end": coverage_end.isoformat(),
        },
    )


def _news_sentiments_at_close(
    values: Sequence[tuple[datetime, float]],
    *,
    cutoff: datetime,
    lookback_days: int,
) -> tuple[float, ...]:
    start = cutoff - timedelta(days=lookback_days)
    return tuple(sentiment for published_at, sentiment in values if start <= published_at <= cutoff)


def _historical_session_closes(
    connection: sqlite3.Connection,
    *,
    ingestion_id: int | None,
    required_sessions: Sequence[str],
) -> tuple[dict[str, datetime], Mapping[str, Any] | None]:
    if ingestion_id is None:
        return {}, None
    ingestion = connection.execute(
        """
        SELECT version, status, metadata_json
        FROM data_ingestions
        WHERE id = ? AND dataset = 'historical_calendar'
          AND provider = 'alpaca-paper'
        """,
        (ingestion_id,),
    ).fetchone()
    if ingestion is None:
        raise ValueError("historical calendar ingestion does not exist")
    if str(ingestion["status"]) != "succeeded":
        raise ValueError("historical calendar ingestion has not succeeded")
    metadata = json.loads(str(ingestion["metadata_json"]))
    if not isinstance(metadata, dict) or not metadata.get("calendar_coverage_complete"):
        raise ValueError("historical calendar ingestion does not claim complete coverage")
    try:
        coverage_start = date.fromisoformat(str(metadata["start"]))
        coverage_end = date.fromisoformat(str(metadata["end"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("historical calendar ingestion metadata is malformed") from error
    required_dates = tuple(date.fromisoformat(value) for value in required_sessions)
    if coverage_start > min(required_dates) or coverage_end < max(required_dates):
        raise ValueError("historical calendar ingestion does not cover the requested dates")
    placeholders = ",".join("?" for _ in required_sessions)
    rows = connection.execute(
        f"""
        SELECT trading_date, closes_at FROM market_sessions
        WHERE provider = 'alpaca-paper' AND trading_date IN ({placeholders})
        """,
        tuple(required_sessions),
    ).fetchall()
    closes = {
        str(row["trading_date"]): _aware_datetime(str(row["closes_at"]))
        for row in rows
    }
    missing = set(required_sessions) - set(closes)
    if missing:
        raise ValueError("historical calendar is missing a required trading session")
    return closes, {
        "id": ingestion_id,
        "version": str(ingestion["version"]),
        "start": coverage_start.isoformat(),
        "end": coverage_end.isoformat(),
    }


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("historical news published_at is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("historical news published_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _walk_forward_config(
    *, total_sessions: int, train_sessions: int, evaluation_span_sessions: int
) -> Mapping[str, Any]:
    # Reserve up to six months each for validation and untouched test folds.
    validation = min(126, max(1, evaluation_span_sessions // 5))
    test = validation
    if train_sessions + validation + test > total_sessions:
        raise ValueError("historical dataset is too short for walk-forward evaluation")
    return {
        "train_sessions": train_sessions,
        "validation_sessions": validation,
        "test_sessions": test,
        "step_sessions": test,
        "expanding": True,
    }
