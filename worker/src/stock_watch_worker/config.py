"""Load and validate immutable strategy configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .strategy import DEFAULT_WEIGHTS


ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALLOWED_HORIZONS = {5, 21, 63, 105}


@dataclass(frozen=True, slots=True)
class LoadedStrategy:
    id: str
    name: str
    status: str
    canonical_json: str
    sha256: str
    data: Mapping[str, Any]


def load_strategy(path: str | Path) -> LoadedStrategy:
    strategy_path = Path(path)
    data = json.loads(strategy_path.read_text(encoding="utf-8"))
    return load_strategy_document(data)


def load_strategy_document(data: Any) -> LoadedStrategy:
    """Validate and canonicalize an in-memory strategy document."""

    if not isinstance(data, dict):
        raise ValueError("strategy configuration must be a JSON object")
    _validate_strategy(data)

    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return LoadedStrategy(
        id=data["id"],
        name=data["name"],
        status=data["status"],
        canonical_json=canonical,
        sha256=digest,
        data=data,
    )


def _validate_strategy(data: Mapping[str, Any]) -> None:
    for key in ("id", "name", "status", "universe", "direction"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"strategy {key} must be a non-empty string")

    if data["universe"] != "sp500":
        raise ValueError("v1 only permits the sp500 universe")
    if data["direction"] != "long":
        raise ValueError("v1 is long only")
    if data["status"] not in {"development", "backtest", "paper", "retired"}:
        raise ValueError("invalid strategy status")

    scan_windows = data.get("scan_windows")
    if not isinstance(scan_windows, list) or len(scan_windows) != 2:
        raise ValueError("v1 requires opening and closing scan windows")
    expected_windows = {
        ("open", "09:45", "America/New_York"),
        ("close", "16:15", "America/New_York"),
    }
    actual_windows: set[tuple[Any, Any, Any]] = set()
    for window in scan_windows:
        if not isinstance(window, dict):
            raise ValueError("scan windows must be objects")
        actual_windows.add(
            (window.get("name"), window.get("time"), window.get("timezone"))
        )
    if actual_windows != expected_windows:
        raise ValueError("v1 scan windows must be 09:45 and 16:15 America/New_York")

    horizons = data.get("horizons_trading_days")
    if not isinstance(horizons, list) or not horizons:
        raise ValueError("at least one holding horizon is required")
    if any(not isinstance(value, int) or value not in ALLOWED_HORIZONS for value in horizons):
        raise ValueError("v1 horizons must be selected from 5, 21, 63, and 105")
    if len(horizons) != len(set(horizons)):
        raise ValueError("holding horizons must be unique")
    if data.get("minimum_hold_trading_days") != 1:
        raise ValueError("v1 minimum hold must be one trading day")

    weights = data.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(DEFAULT_WEIGHTS):
        raise ValueError("strategy must define every v0 scoring pillar exactly once")
    if any(not isinstance(weight, (int, float)) or weight <= 0 for weight in weights.values()):
        raise ValueError("strategy weights must be positive numbers")
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("strategy weights must sum to 1.0")

    execution = data.get("execution")
    if not isinstance(execution, dict):
        raise ValueError("execution configuration is required")
    if execution.get("mode") != "paper":
        raise ValueError("live trading is outside v1; execution mode must be paper")
    if execution.get("alpaca_base_url") != ALPACA_PAPER_BASE_URL:
        raise ValueError("only the allowlisted Alpaca paper endpoint is accepted")
    if execution.get("one_open_lot_per_ticker_horizon") is not True:
        raise ValueError("v1 requires open-lot deduplication")

    sizing = data.get("sizing")
    if not isinstance(sizing, dict):
        raise ValueError("sizing configuration is required")
    minimum = sizing.get("minimum_notional_usd")
    maximum = sizing.get("maximum_notional_usd")
    base = sizing.get("base_notional_usd")
    if not all(isinstance(value, (int, float)) for value in (minimum, maximum, base)):
        raise ValueError("sizing notionals must be numbers")
    if not (minimum == 5 and base == 10 and maximum == 15):
        raise ValueError("v1 sizing must retain the accepted $5/$10/$15 bounds")
