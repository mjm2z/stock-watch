"""Plain-text Telegram presentation. No broker calls or trading calculations."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

DASHBOARD = "http://stockwatch.home.arpa/manual-paper"
LIMIT = 3900
TERMINAL = {"filled", "canceled", "expired", "rejected"}


def clean(value):
    return " ".join(str(value).split())


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def dollars(value, signed=False):
    value = number(value)
    if value is None:
        return "unavailable"
    try:
        value = value.quantize(Decimal(".01"))
    except InvalidOperation:
        return "unavailable"
    sign = "−" if value < 0 else "+" if signed and value > 0 else ""
    return f"{sign}${abs(value):,.2f}"


def when(value):
    try:
        instant = datetime.fromtimestamp(float(value), ZoneInfo("America/New_York"))
        return instant.strftime("%b %d, %-I:%M %p ET")
    except (ValueError, TypeError, OverflowError, OSError):
        return "time unavailable"


def bounded(lines):
    """Omit whole lines, reserving space for an explicit details notice."""
    lines = [str(line) for line in lines if line is not None]
    footer = "More details in StockWatch.\n" + DASHBOARD
    result = []
    for line in lines:
        candidate = "\n".join([*result, line])
        if len(candidate.encode("utf-16-le")) // 2 > LIMIT - len(footer) - 1:
            return "\n".join([*result, footer])
        result.append(line)
    return "\n".join(result)


def digest(snapshots, instructions, health, now):
    lines = ["StockWatch · Paper · " + when(now)]
    attention = []
    allocations = {}
    for snapshot in snapshots:
        for row in snapshot.get("allocations", []):
            allocations[row["asset"]] = row
        at = number(snapshot.get("at"))
        if at is None or now - float(at) > 300:
            attention.append("Account values are stale; last update " + when(snapshot.get("at")))
    total = Decimal(0)
    complete = True
    positions = 0
    for asset, label in (("stocks", "Stocks"), ("bitcoin", "Bitcoin")):
        row = allocations.get(asset, {})
        pnl = number(row.get("net_pnl"))
        equity = number(row.get("equity"))
        if row.get("unavailable_reason") or pnl is None or equity is None:
            lines.append(label + ": unavailable")
            attention.append(clean(row.get("unavailable_reason") or label + " account data unavailable"))
            complete = False
        else:
            lines.append(f"{label}: {dollars(equity)} · P/L {dollars(pnl, True)}")
            total += pnl
        positions += len(row.get("positions", []))
    lines.append("Total profit/loss since setup: " + dollars(total if complete else None, True))
    pending = [r for r in instructions if r["status"] not in TERMINAL]
    position_label = "position" if positions == 1 else "positions"
    order_label = "order" if len(pending) == 1 else "orders"
    count = f"{positions} {position_label}" if len(allocations) == 2 else "Positions unavailable"
    lines.append(f"{count} · {len(pending)} pending {order_label}")
    if any(r["status"] == "uncertain" for r in pending):
        attention.append("Order status uncertain; reconcile at Alpaca before retrying")
    if any(r.get("error") for r in health):
        attention.append("Service issue; check StockWatch health")
    if attention:
        lines.append("Attention: " + "; ".join(dict.fromkeys(attention)))
    lines.append(DASHBOARD)
    return bounded(lines)


def confirmation(result):
    lines = ["StockWatch · Paper confirmation"]
    if result.get("configured"):
        lines.append("Account ready · Stocks $1,000 · Bitcoin $1,000")
    elif result.get("cancel_requested"):
        lines.extend(["Cancellation requested; awaiting reconciliation.", "Order: " + clean(result["cancel_requested"])])
    elif result.get("system_job"):
        lines.extend(["System action queued; not completed yet.", "Job: " + clean(result["system_job"])])
    elif result.get("protective_plan"):
        status = "Protection active" if result.get("status") == "active" else "Protection cancellation requested"
        lines.extend([status, "Plan: " + clean(result["protective_plan"])])
    elif result.get("instruction"):
        status = "Waiting for trigger" if result.get("status") == "armed" else "Order queued; not filled yet"
        lines.extend([status, "Order: " + clean(result["instruction"])])
    else:
        lines.append("Result unavailable; check StockWatch before retrying.")
    return bounded(lines)


def order_event(row, status, qty, price):
    labels = {"filled": "Filled", "partially_filled": "Partially filled", "canceled": "Canceled", "expired": "Expired", "rejected": "Rejected"}
    title = labels.get(status, clean(status).replace("_", " ").capitalize())
    lines = [f"StockWatch · Paper · {title}", f"{clean(row['symbol'])} · {clean(row['side']).capitalize()}"]
    if number(qty) is not None and number(qty) > 0:
        lines.append(f"Filled so far: {clean(qty)} at ${clean(price)} average")
    else:
        lines.append("No fills reported")
    if status in ("rejected", "expired"):
        lines.append("Review the order before placing a new one.")
    return bounded(lines)


def system_event(action, entity, payload):
    payload = payload if isinstance(payload, dict) else {}
    titles = {
        "order_intent": "Order queued", "bitcoin_order_intent": "Bitcoin order queued",
        "operator_pause": "Entries paused; existing exits continue",
        "operator_exit": "Exit requested", "operator_exit_and_pause": "Exit and pause requested",
        "drawdown_pause": "Entries paused: drawdown limit",
    }
    title = titles.get(action, "System update · " + clean(action).replace("_", " "))
    lines = ["StockWatch · Paper · " + title, "System reference: " + clean(entity)]
    details = []
    for key, label in (("symbol", "Symbol"), ("side", "Side"), ("qty", "Quantity"), ("quantity", "Quantity"), ("price", "Price"), ("reason", "Reason")):
        if payload.get(key) is not None and not isinstance(payload[key], (dict, list)):
            details.append(label + ": " + clean(payload[key]))
    lines.extend(details)
    if action not in titles or "pause" in action or "reject" in action:
        lines.append("Details: http://stockwatch.home.arpa/systems")
    return bounded(lines)
