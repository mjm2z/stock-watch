"""Account-labelled observations and a durable local-time daily digest."""

from datetime import datetime
from decimal import Decimal
import os
from zoneinfo import ZoneInfo
from .store import canonical, notify


def refresh(manual):
    collect_system_events(manual)
    db = manual.db
    now = manual.now()
    for row in db.execute("SELECT * FROM accounts").fetchall():
        try:
            account = manual.account(row["asset"])
            positions = manual.brokers[row["asset"]].positions()
            payload = {
                "asset": row["asset"],
                "account_id": account["id"],
                "at": now,
                "cash": account["cash"],
                "equity": account.get("equity"),
                "positions": positions,
                "unrealized_pl": str(
                    sum(
                        (Decimal(p.get("unrealized_pl", "0")) for p in positions),
                        Decimal(0),
                    )
                ),
            }
            from .accounting import performance

            try:
                payload["performance"] = performance(manual, row, account, positions)
            except Exception:
                payload["performance"] = {
                    "total_pnl": None,
                    "status": "Fee/cash-flow reconciliation unavailable",
                }
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO snapshots VALUES (?,?,?)",
                    (row["asset"], now, canonical(payload)),
                )
                db.execute(
                    "INSERT OR REPLACE INTO health VALUES (?,?,NULL)",
                    ("account:" + row["asset"], now),
                )
        except Exception as error:
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO health VALUES (?,?,?)",
                    ("account:" + row["asset"], now, str(error)[:200]),
                )
                # One notice per account/outage day prevents tick-by-tick message storms.
                notify(
                    db,
                    "outage:"
                    + row["asset"]
                    + ":"
                    + datetime.fromtimestamp(now, ZoneInfo("UTC")).date().isoformat(),
                    "Manual "
                    + row["asset"]
                    + " account unavailable; pending reservations remain. Check StockWatch health.",
                    now,
                )
    local = datetime.fromtimestamp(now, ZoneInfo("America/New_York"))
    scheduled = os.environ.get("STOCK_WATCH_DIGEST_TIME", "20:00")
    if local.strftime("%H:%M") == scheduled:
        snapshots = [
            __import__("json").loads(r["payload"])
            for r in db.execute("SELECT * FROM snapshots")
        ]
        with db:
            notify(
                db,
                "digest:" + local.date().isoformat(),
                "StockWatch daily paper digest\n" + canonical(snapshots)[:3400],
                now,
            )


def collect_system_events(manual):
    """Forward new automation audit events; first startup establishes a baseline."""
    from contextlib import closing
    from .systems import database
    import json

    try:
        with closing(database()) as systems:
            saved = manual.db.execute(
                "SELECT value FROM integration_state WHERE key='system_audit'"
            ).fetchone()
            if not saved:
                latest = systems.execute(
                    "SELECT COALESCE(MAX(id),0) FROM system_audit"
                ).fetchone()[0]
                with manual.db:
                    manual.db.execute(
                        "INSERT INTO integration_state VALUES ('system_audit',?)",
                        (str(latest),),
                    )
                return
            rows = systems.execute(
                "SELECT * FROM system_audit WHERE id>? ORDER BY id LIMIT 100",
                (int(saved[0]),),
            ).fetchall()
            with manual.db:
                for row in rows:
                    if any(
                        word in row["action"]
                        for word in ("order", "fill", "exit", "reject", "pause")
                    ):
                        notify(
                            manual.db,
                            "system-audit:" + str(row["id"]),
                            "StockWatch system "
                            + row["action"]
                            + " · "
                            + row["entity_id"]
                            + "\n"
                            + canonical(json.loads(row["payload_json"]))[:2000],
                            manual.now(),
                        )
                    manual.db.execute(
                        "UPDATE integration_state SET value=? WHERE key='system_audit'",
                        (str(row["id"]),),
                    )
    except Exception:
        # Missing main DB must not prevent unrelated manual-account reconciliation.
        return
