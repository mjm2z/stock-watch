"""Alpaca historical data, news, snapshots, and paper-only execution."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import islice
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlencode

from ..config import ALPACA_PAPER_BASE_URL
from ..http import HttpTransport, UrllibTransport, require_success
from ..market_calendar import MarketSession


ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"
ALPACA_MINIMUM_NOTIONAL_USD = Decimal("5")
ALPACA_MAXIMUM_NOTIONAL_USD = Decimal("15")
ResponseObserver = Callable[[str, Mapping[str, str], Any], None]


@dataclass(frozen=True, slots=True)
class AlpacaCredentials:
    key_id: str
    secret_key: str

    def __post_init__(self) -> None:
        if not self.key_id.strip() or not self.secret_key.strip():
            raise ValueError("Alpaca key id and secret key are required")

    @classmethod
    def from_environment(cls) -> "AlpacaCredentials":
        key_id = os.environ.get("ALPACA_API_KEY_ID", "")
        secret_key = os.environ.get("ALPACA_API_SECRET_KEY", "")
        if not key_id or not secret_key:
            raise ValueError(
                "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are required"
            )
        return cls(key_id=key_id, secret_key=secret_key)


@dataclass(frozen=True, slots=True)
class MarketBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int | None
    vwap: float | None


@dataclass(frozen=True, slots=True)
class NewsArticle:
    id: int
    headline: str
    created_at: str
    updated_at: str | None
    source: str | None
    summary: str | None
    url: str | None
    symbols: tuple[str, ...]
    content: str | None
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AlpacaAsset:
    id: str
    symbol: str
    name: str | None
    exchange: str | None
    status: str
    tradable: bool
    fractionable: bool


@dataclass(frozen=True, slots=True)
class AlpacaAccount:
    id: str
    status: str
    currency: str
    cash: float
    equity: float
    long_market_value: float
    trading_blocked: bool
    account_blocked: bool
    trade_suspended: bool
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AlpacaPosition:
    asset_id: str
    symbol: str
    quantity: float
    market_value: float
    current_price: float
    cost_basis: float
    side: str
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AlpacaAccountActivity:
    id: str
    activity_type: str
    occurred_at: str
    symbol: str | None
    net_amount: float | None
    quantity: float | None
    per_share_amount: float | None
    raw: Mapping[str, Any]


class AlpacaMarketDataClient:
    def __init__(
        self,
        credentials: AlpacaCredentials,
        *,
        transport: HttpTransport | None = None,
        base_url: str = ALPACA_DATA_BASE_URL,
        response_observer: ResponseObserver | None = None,
    ) -> None:
        if base_url.rstrip("/") != ALPACA_DATA_BASE_URL:
            raise ValueError("Alpaca data client only accepts the allowlisted base URL")
        self._credentials = credentials
        self._transport = transport or UrllibTransport()
        self._base_url = ALPACA_DATA_BASE_URL
        self._response_observer = response_observer

    def get_historical_bars(
        self,
        symbols: Sequence[str],
        *,
        timeframe: str,
        start: str,
        end: str,
        adjustment: str = "all",
        feed: str = "iex",
    ) -> list[MarketBar]:
        normalized = _normalize_symbols(symbols)
        if not normalized:
            return []
        if adjustment not in {"raw", "split", "dividend", "spin-off", "all"}:
            raise ValueError("unsupported Alpaca adjustment")
        if feed not in {"iex", "sip", "delayed_sip"}:
            raise ValueError("unsupported Alpaca stock feed")

        params: dict[str, str] = {
            "symbols": ",".join(normalized),
            "timeframe": timeframe,
            "start": start,
            "end": end,
            "adjustment": adjustment,
            "feed": feed,
            "limit": "10000",
            "sort": "asc",
        }
        bars: list[MarketBar] = []
        for data in self._get_pages("/v2/stocks/bars", params):
            raw_bars = data.get("bars", {})
            if not isinstance(raw_bars, dict):
                raise ValueError("Alpaca bars response is malformed")
            for symbol, values in raw_bars.items():
                if not isinstance(values, list):
                    continue
                for value in values:
                    bars.append(_parse_bar(str(symbol), value))
        bars.sort(key=lambda bar: (bar.symbol, bar.timestamp))
        return bars

    def get_news(
        self,
        *,
        start: str,
        end: str,
        symbols: Sequence[str] = (),
        include_content: bool = False,
    ) -> list[NewsArticle]:
        params = {
            "start": start,
            "end": end,
            "sort": "asc",
            "limit": "50",
            "include_content": str(include_content).lower(),
        }
        normalized = _normalize_symbols(symbols)
        if normalized:
            params["symbols"] = ",".join(normalized)

        articles: list[NewsArticle] = []
        for data in self._get_pages("/v1beta1/news", params):
            raw_news = data.get("news", [])
            if not isinstance(raw_news, list):
                raise ValueError("Alpaca news response is malformed")
            articles.extend(_parse_news(item) for item in raw_news)
        return articles

    def get_snapshots(
        self,
        symbols: Sequence[str],
        *,
        feed: str = "iex",
        chunk_size: int = 200,
    ) -> dict[str, Mapping[str, Any]]:
        if feed not in {"iex", "sip", "delayed_sip"}:
            raise ValueError("unsupported Alpaca snapshot feed")
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")

        snapshots: dict[str, Mapping[str, Any]] = {}
        for chunk in _chunks(_normalize_symbols(symbols), chunk_size):
            data = self._get(
                "/v2/stocks/snapshots",
                {"symbols": ",".join(chunk), "feed": feed},
            )
            if not isinstance(data, dict):
                raise ValueError("Alpaca snapshots response is malformed")
            for symbol, snapshot in data.items():
                if isinstance(snapshot, dict):
                    snapshots[str(symbol)] = snapshot
        return snapshots

    def _get_pages(
        self,
        path: str,
        params: Mapping[str, str],
    ) -> Iterator[Mapping[str, Any]]:
        page_params = dict(params)
        while True:
            data = self._get(path, page_params)
            if not isinstance(data, dict):
                raise ValueError("Alpaca paginated response is malformed")
            yield data
            token = data.get("next_page_token")
            if not token:
                break
            if not isinstance(token, str):
                raise ValueError("Alpaca page token is malformed")
            page_params["page_token"] = token

    def _get(self, path: str, params: Mapping[str, str]) -> Any:
        url = f"{self._base_url}{path}?{urlencode(params)}"
        response = self._transport.request(
            "GET", url, headers=self._headers(), timeout=30
        )
        data = require_success("alpaca", response)
        if self._response_observer is not None:
            self._response_observer(path, params, data)
        return data

    def _headers(self) -> Mapping[str, str]:
        return {
            "Accept": "application/json",
            "APCA-API-KEY-ID": self._credentials.key_id,
            "APCA-API-SECRET-KEY": self._credentials.secret_key,
        }


class AlpacaPaperTradingClient:
    """Narrow paper-only order client; a live base URL cannot be supplied."""

    def __init__(
        self,
        credentials: AlpacaCredentials,
        *,
        transport: HttpTransport | None = None,
        base_url: str = ALPACA_PAPER_BASE_URL,
        response_observer: ResponseObserver | None = None,
    ) -> None:
        if base_url.rstrip("/") != ALPACA_PAPER_BASE_URL:
            raise ValueError("only the Alpaca paper endpoint is accepted")
        self._credentials = credentials
        self._transport = transport or UrllibTransport()
        self._base_url = ALPACA_PAPER_BASE_URL
        self._response_observer = response_observer

    def submit_notional_market_buy(
        self,
        *,
        symbol: str,
        notional_usd: Decimal | float | str,
        client_order_id: str,
    ) -> Mapping[str, Any]:
        normalized_symbol = _order_symbol(symbol)
        notional = Decimal(str(notional_usd))
        if not ALPACA_MINIMUM_NOTIONAL_USD <= notional <= ALPACA_MAXIMUM_NOTIONAL_USD:
            raise ValueError("paper notional must be between $5 and $15")
        if not client_order_id.strip():
            raise ValueError("client_order_id is required")

        payload = {
            "symbol": normalized_symbol,
            "notional": format(notional.quantize(Decimal("0.01")), "f"),
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_order_id,
        }
        return self._request("POST", "/v2/orders", payload)

    def submit_fractional_market_sell(
        self,
        *,
        symbol: str,
        quantity: Decimal | float | str,
        client_order_id: str,
    ) -> Mapping[str, Any]:
        normalized_symbol = _order_symbol(symbol)
        parsed_quantity = Decimal(str(quantity))
        if not parsed_quantity.is_finite() or parsed_quantity <= 0:
            raise ValueError("paper sell quantity must be positive")
        quantized = parsed_quantity.quantize(Decimal("0.000000001"))
        if quantized <= 0:
            raise ValueError("paper sell quantity is below fractional precision")
        if not client_order_id.strip():
            raise ValueError("client_order_id is required")

        payload = {
            "symbol": normalized_symbol,
            "qty": format(quantized, "f"),
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_order_id,
        }
        return self._request("POST", "/v2/orders", payload)

    def get_order_by_client_order_id(self, client_order_id: str) -> Mapping[str, Any]:
        if not client_order_id.strip():
            raise ValueError("client_order_id is required")
        path = "/v2/orders:by_client_order_id"
        url = f"{self._base_url}{path}?{urlencode({'client_order_id': client_order_id})}"
        response = self._transport.request(
            "GET", url, headers=self._headers(), timeout=30
        )
        data = require_success("alpaca-paper", response)
        self._observe(path, {"client_order_id": client_order_id}, data)
        if not isinstance(data, dict):
            raise ValueError("Alpaca order response is malformed")
        return data

    def get_market_calendar(
        self, *, start: date | str, end: date | str
    ) -> list[MarketSession]:
        start_value = start.isoformat() if isinstance(start, date) else str(start)
        end_value = end.isoformat() if isinstance(end, date) else str(end)
        try:
            start_date = date.fromisoformat(start_value)
            end_date = date.fromisoformat(end_value)
        except ValueError as error:
            raise ValueError("calendar start and end must be ISO dates") from error
        if start_date > end_date:
            raise ValueError("calendar start must not be after end")
        path = "/v2/calendar"
        url = f"{self._base_url}{path}?{urlencode({'start': start_value, 'end': end_value})}"
        response = self._transport.request(
            "GET", url, headers=self._headers(), timeout=30
        )
        data = require_success("alpaca-paper", response)
        self._observe(path, {"start": start_value, "end": end_value}, data)
        if not isinstance(data, list):
            raise ValueError("Alpaca calendar response is malformed")
        if any(not isinstance(item, dict) for item in data):
            raise ValueError("Alpaca calendar response is malformed")
        return [MarketSession.from_alpaca(item) for item in data]

    def get_assets(
        self, *, status: str = "active", asset_class: str = "us_equity"
    ) -> list[AlpacaAsset]:
        if status not in {"active", "inactive"}:
            raise ValueError("unsupported asset status")
        if asset_class != "us_equity":
            raise ValueError("v1 only supports US equities")
        path = "/v2/assets"
        url = f"{self._base_url}{path}?{urlencode({'status': status, 'asset_class': asset_class})}"
        response = self._transport.request(
            "GET", url, headers=self._headers(), timeout=30
        )
        data = require_success("alpaca-paper", response)
        self._observe(path, {"status": status, "asset_class": asset_class}, data)
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ValueError("Alpaca assets response is malformed")
        return [_parse_asset(item) for item in data]

    def get_account(self) -> AlpacaAccount:
        data = self._get("/v2/account", {})
        if not isinstance(data, dict):
            raise ValueError("Alpaca account response is malformed")
        return _parse_account(data)

    def get_positions(self) -> list[AlpacaPosition]:
        data = self._get("/v2/positions", {})
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ValueError("Alpaca positions response is malformed")
        return [_parse_position(item) for item in data]

    def get_non_trade_activities(
        self, *, after: str | None = None
    ) -> list[AlpacaAccountActivity]:
        params = {
            "category": "non_trade_activity",
            "direction": "asc",
            "page_size": "100",
        }
        if after:
            params["after"] = after
        activities: list[AlpacaAccountActivity] = []
        while True:
            data = self._get("/v2/account/activities", params)
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ValueError("Alpaca account activities response is malformed")
            activities.extend(_parse_account_activity(item) for item in data)
            if len(data) < 100:
                break
            page_token = str(data[-1].get("id", "")).strip()
            if not page_token:
                raise ValueError("Alpaca account activity page is missing its last id")
            params["page_token"] = page_token
        return activities

    def _get(self, path: str, params: Mapping[str, str]) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        response = self._transport.request(
            "GET", f"{self._base_url}{path}{query}", headers=self._headers(), timeout=30
        )
        data = require_success("alpaca-paper", response)
        self._observe(path, params, data)
        return data

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        response = self._transport.request(
            method,
            f"{self._base_url}{path}",
            headers=self._headers(),
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            timeout=30,
        )
        data = require_success("alpaca-paper", response)
        self._observe(path, {key: str(value) for key, value in payload.items()}, data)
        if not isinstance(data, dict):
            raise ValueError("Alpaca order response is malformed")
        return data

    def _observe(self, path: str, params: Mapping[str, str], data: Any) -> None:
        if self._response_observer is not None:
            self._response_observer(path, params, data)

    def _headers(self) -> Mapping[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "APCA-API-KEY-ID": self._credentials.key_id,
            "APCA-API-SECRET-KEY": self._credentials.secret_key,
        }


def _parse_bar(symbol: str, value: Any) -> MarketBar:
    if not isinstance(value, dict):
        raise ValueError("Alpaca bar is malformed")
    try:
        return MarketBar(
            symbol=symbol.upper(),
            timestamp=str(value["t"]),
            open=float(value["o"]),
            high=float(value["h"]),
            low=float(value["l"]),
            close=float(value["c"]),
            volume=float(value["v"]),
            trade_count=int(value["n"]) if value.get("n") is not None else None,
            vwap=float(value["vw"]) if value.get("vw") is not None else None,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Alpaca bar is missing required fields") from error


def _parse_news(value: Any) -> NewsArticle:
    if not isinstance(value, dict):
        raise ValueError("Alpaca news article is malformed")
    try:
        article_id = int(value["id"])
        headline = str(value["headline"])
        created_at = str(value["created_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Alpaca news article is missing required fields") from error

    raw_symbols = value.get("symbols") or []
    if not isinstance(raw_symbols, list):
        raise ValueError("Alpaca news symbols are malformed")
    return NewsArticle(
        id=article_id,
        headline=headline,
        created_at=created_at,
        updated_at=_optional_string(value.get("updated_at")),
        source=_optional_string(value.get("source")),
        summary=_optional_string(value.get("summary")),
        url=_optional_string(value.get("url")),
        symbols=tuple(str(symbol).upper() for symbol in raw_symbols),
        content=_optional_string(value.get("content")),
        raw=value,
    )


def _parse_asset(value: Mapping[str, Any]) -> AlpacaAsset:
    try:
        asset_id = str(value["id"])
        symbol = str(value["symbol"]).strip().upper()
        status = str(value["status"])
        tradable = value["tradable"]
        fractionable = value["fractionable"]
    except (KeyError, TypeError) as error:
        raise ValueError("Alpaca asset is missing required fields") from error
    if not asset_id or not symbol or not isinstance(tradable, bool) or not isinstance(fractionable, bool):
        raise ValueError("Alpaca asset is missing required fields")
    return AlpacaAsset(
        id=asset_id,
        symbol=symbol,
        name=_optional_string(value.get("name")),
        exchange=_optional_string(value.get("exchange")),
        status=status,
        tradable=tradable,
        fractionable=fractionable,
    )


def _parse_account(value: Mapping[str, Any]) -> AlpacaAccount:
    try:
        account_id = str(value["id"]).strip()
        status = str(value["status"]).strip()
        currency = str(value["currency"]).strip()
        booleans = (
            value["trading_blocked"],
            value["account_blocked"],
            value["trade_suspended_by_user"],
        )
    except (KeyError, TypeError) as error:
        raise ValueError("Alpaca account is missing required fields") from error
    if not account_id or not status or not currency or any(
        not isinstance(item, bool) for item in booleans
    ):
        raise ValueError("Alpaca account is missing required fields")
    return AlpacaAccount(
        id=account_id,
        status=status,
        currency=currency,
        cash=_finite_float(value.get("cash"), "account cash"),
        equity=_finite_float(value.get("equity"), "account equity"),
        long_market_value=_finite_float(
            value.get("long_market_value"), "account long market value"
        ),
        trading_blocked=booleans[0],
        account_blocked=booleans[1],
        trade_suspended=booleans[2],
        raw=value,
    )


def _parse_position(value: Mapping[str, Any]) -> AlpacaPosition:
    try:
        asset_id = str(value["asset_id"]).strip()
        symbol = str(value["symbol"]).strip().upper()
        side = str(value["side"]).strip().lower()
    except (KeyError, TypeError) as error:
        raise ValueError("Alpaca position is missing required fields") from error
    quantity = _finite_float(value.get("qty"), "position quantity")
    if not asset_id or not symbol or side != "long" or quantity <= 0:
        raise ValueError("v1 only supports positive long Alpaca positions")
    return AlpacaPosition(
        asset_id=asset_id,
        symbol=symbol,
        quantity=quantity,
        market_value=_finite_float(value.get("market_value"), "position market value"),
        current_price=_finite_float(value.get("current_price"), "position current price"),
        cost_basis=_finite_float(value.get("cost_basis"), "position cost basis"),
        side=side,
        raw=value,
    )


def _parse_account_activity(value: Mapping[str, Any]) -> AlpacaAccountActivity:
    try:
        activity_id = str(value["id"]).strip()
        activity_type = str(value["activity_type"]).strip().upper()
    except (KeyError, TypeError) as error:
        raise ValueError("Alpaca account activity is missing required fields") from error
    occurred_at = str(value.get("transaction_time") or value.get("date") or "").strip()
    if not activity_id or not activity_type or not occurred_at:
        raise ValueError("Alpaca account activity is missing required fields")
    symbol = _optional_string(value.get("symbol"))
    return AlpacaAccountActivity(
        id=activity_id,
        activity_type=activity_type,
        occurred_at=occurred_at,
        symbol=symbol.upper() if symbol else None,
        net_amount=_optional_finite_float(value.get("net_amount"), "activity net amount"),
        quantity=_optional_finite_float(value.get("qty"), "activity quantity"),
        per_share_amount=_optional_finite_float(
            value.get("per_share_amount"), "activity per-share amount"
        ),
        raw=value,
    )


def _normalize_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        value = symbol.strip().upper()
        if not value:
            raise ValueError("symbols cannot contain empty values")
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return tuple(normalized)


def _order_symbol(symbol: str) -> str:
    normalized = _normalize_symbols([symbol])
    if not normalized:
        raise ValueError("symbol is required")
    return normalized[0]


def _chunks(values: Sequence[str], size: int) -> Iterator[tuple[str, ...]]:
    iterator = iter(values)
    while chunk := tuple(islice(iterator, size)):
        yield chunk


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _finite_float(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Alpaca {name} is malformed") from error
    if not math.isfinite(parsed):
        raise ValueError(f"Alpaca {name} is malformed")
    return parsed


def _optional_finite_float(value: Any, name: str) -> float | None:
    return None if value in (None, "") else _finite_float(value, name)
