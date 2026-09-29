"""Conservative application subset of Alpaca capabilities, shared with the UI."""
import json
from pathlib import Path
from decimal import Decimal as D
from .store import money

CAPABILITIES = json.loads(Path(__file__).with_name("capabilities.json").read_text())


def validate_order(body, metadata, asset, side):
    kind = body.get("order_type", "limit")
    if kind not in CAPABILITIES[asset]["order_types"]:
        raise ValueError("Unsupported order type for this asset")
    tif = body.get("time_in_force", "day" if asset == "stocks" else "gtc")
    if tif not in CAPABILITIES[asset]["time_in_force"] or (asset == "bitcoin" and kind == "stop_limit" and tif != "gtc"):
        raise ValueError("Unsupported time in force for this order")
    notional = money(body["notional"]) if body.get("notional") is not None else None
    if kind == "market" and side == "buy":
        if not notional or body.get("qty") is not None:
            raise ValueError("Market buys require dollar notional, without quantity")
        qty = D(0)  # No fictional estimate stored as a requested broker quantity.
    else:
        if notional is not None:
            raise ValueError("Dollar sizing is supported only for market buys")
        qty = money(body.get("qty"))
    if min(qty.as_tuple().exponent, (notional or D(0)).as_tuple().exponent) < -9:
        raise ValueError("Sizing supports at most nine decimal places")
    fractional = notional is not None or qty != qty.to_integral_value()
    if asset == "stocks" and fractional:
        if not metadata.get("fractionable"):
            raise ValueError("This stock is not fractionable")
        if tif != "day":
            raise ValueError("Fractional stock orders require DAY")
    if asset == "bitcoin" and not notional:
        if qty < D(metadata["min_order_size"]) or qty % D(metadata.get("min_trade_increment") or "0.000000001"):
            raise ValueError("Quantity violates broker minimum/increment")
    price = money(body.get("limit")) if kind in ("limit", "stop_limit") else D(0)
    if kind in ("market", "stop") and body.get("limit") is not None:
        raise ValueError("This order type has no limit price")
    if asset == 'stocks' and price:
        tick = D('.01') if price >= 1 else D('.0001')
        if price % tick:
            raise ValueError('Stock limit price violates broker price precision')
    stop = money(body.get("stop_price")) if kind in ("stop", "stop_limit") else None
    if asset == 'stocks' and stop and stop % (D('.01') if stop >= 1 else D('.0001')):
        raise ValueError('Stock stop price violates broker price precision')
    if notional and asset == 'stocks' and notional < 1:
        raise ValueError('Stock notional requires at least $1')
    if kind == "stop" and side != "sell":
        raise ValueError("Stop-market is supported only for stock exits; use stop-limit for entries")
    if kind == "stop_limit" and ((side == "buy" and price < stop) or (side == "sell" and price > stop)):
        raise ValueError("Stop-limit price must protect the selected side")
    if not stop and body.get("stop_price") is not None:
        raise ValueError("Stop price requires a stop order type")
    if body.get("condition") and kind != "limit":
        raise ValueError("Local conditions require a price-protected limit order")
    return {"qty": qty, "notional": notional, "price": price, "stop": stop, "order_type": kind, "time_in_force": tif}
