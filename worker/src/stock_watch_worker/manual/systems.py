"""System previews queue durable work for the existing strategy workers."""

from contextlib import closing
from dataclasses import asdict, replace
import json
import os
import sqlite3
from ..systems.automation_config import load_config
from ..systems.engine import canonical, instant
from ..systems.research import now_iso, register_version
from ..systems.operator_controls import request as control_request


def database():
    db = sqlite3.connect(os.environ["STOCK_WATCH_DATABASE_PATH"], timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def inspect():
    with closing(database()) as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT id,asset,template,config_json,hypothesis FROM system_versions ORDER BY created_at DESC LIMIT 100"
            )
        ]


def validate(body):
    allowed = {"action", "asset", "version", "operation", "start", "end", "parameters"}
    if set(body) - allowed:
        raise ValueError("Unsupported system fields")
    operation = body.get("operation")
    if operation not in (
        "pause",
        "resume",
        "exit",
        "exit_and_pause",
        "backtest",
        "start_paper",
        "observe",
        "variant",
    ):
        raise ValueError(
            "Choose pause, resume, exit, exit_and_pause, backtest, start_paper, observe or variant"
        )
    if operation == "start_paper" and body.get("asset") == "stocks":
        from ..systems.stocks import require_qualification_evidence

        require_qualification_evidence()
    with closing(database()) as db:
        row = db.execute(
            "SELECT * FROM system_versions WHERE id=? AND asset=?",
            (body.get("version"), body.get("asset")),
        ).fetchone()
        if not row:
            raise ValueError("Unknown immutable system version")
        config = load_config(json.loads(row["config_json"]))
        if operation == "variant":
            params = body.get("parameters", {})
            if (
                not isinstance(params, dict)
                or not params
                or set(params)
                - {
                    "fast",
                    "slow",
                    "entry",
                    "exit",
                    "allocation",
                    "holding_count",
                    "holding_unit",
                }
            ):
                raise ValueError(
                    "Choose supported template lookback/allocation/holding parameters"
                )
            try:
                variant = replace(config, **params)
            except TypeError as error:
                raise ValueError("Parameter is unsupported by this template") from error
            return {
                **body,
                "account_id": "systems:" + row["asset"],
                "config": asdict(variant),
                "version_hash": variant.sha256,
                "activation": "None; publish an immutable research variant only",
            }
        if operation == "backtest":
            if (
                not body.get("start")
                or not body.get("end")
                or instant(body["start"]) >= instant(body["end"])
            ):
                raise ValueError("Choose UTC start and end timestamps")
        if operation in ("pause", "resume", "exit", "exit_and_pause"):
            allocation = db.execute(
                "SELECT 1 FROM btc_allocations WHERE version_id=?", (row["id"],)
            ).fetchone()
            deployment = db.execute(
                "SELECT * FROM system_deployments WHERE version_id=?", (row["id"],)
            ).fetchone()
            if not allocation and not deployment:
                raise ValueError("System has no deployment/allocation")
            if row["asset"] == "bitcoin" and not allocation:
                raise ValueError(
                    "Legacy Bitcoin controls require migration to the shared coordinator first"
                )
        return {
            **body,
            "account_id": "systems:" + row["asset"],
            "version_hash": row["config_sha256"],
            "semantics": {
                "pause": "Cancel pending entries; existing-position exits continue",
                "exit": "Close owned position and cancel pending entries; only new later decisions can re-enter",
                "exit_and_pause": "Close owned position and prevent future entries",
                "resume": "Allow entries subject to unchanged qualification and risk gates",
            }.get(
                operation,
                "Existing worker checks apply; backtests do not activate systems",
            ),
        }


def dispatch(manual):
    for row in manual.db.execute(
        "SELECT * FROM system_jobs WHERE state='queued' ORDER BY created LIMIT 10"
    ).fetchall():
        try:
            body = json.loads(row["body"])
            preview = validate(body)
            operation = body["operation"]
            with closing(database()) as db:
                # Cross-database delivery uses a stable job ID and durable receipt.
                old = db.execute(
                    "SELECT result_json FROM workspace_jobs WHERE id=?", (row["id"],)
                ).fetchone()
                if old:
                    result = json.loads(old[0] or "{}")
                elif operation in (
                    "pause",
                    "resume",
                    "exit",
                    "exit_and_pause",
                    "variant",
                ):
                    # Receipt and mutation share the same SQLite transaction. Helpers commit,
                    # so controls carry a stable timestamp to prevent duplicate exit barriers.
                    if operation == "variant":
                        result = {
                            "version": register_version(
                                db,
                                load_config(preview["config"]),
                                "Telegram supported-template variant",
                            )
                        }
                    else:
                        existing = db.execute(
                            "SELECT payload_json FROM system_audit WHERE action=? AND entity_id=? AND json_extract(payload_json,'$.manual_job')=? LIMIT 1",
                            ("operator_" + operation, body["version"], row["id"]),
                        ).fetchone()
                        attribution = {
                            "manual_job": row["id"],
                            "attribution": json.loads(row["attribution"]),
                        }
                        result = (
                            {"version": body["version"], "action": operation}
                            if existing
                            and json.loads(existing[0]).get("manual_job") == row["id"]
                            else control_request(
                                db, body["version"], operation, attribution
                            )
                        )
                    with db:
                        db.execute(
                            "INSERT OR IGNORE INTO workspace_jobs(id,kind,payload_json,status,result_json,created_at,finished_at) VALUES (?,?,?,'succeeded',?,?,?)",
                            (
                                row["id"],
                                "telegram_control",
                                canonical(body),
                                canonical(result),
                                now_iso(),
                                now_iso(),
                            ),
                        )
                else:
                    payload = {**body, "action": operation, "requestId": row["id"]}
                    with db:
                        db.execute(
                            "INSERT OR IGNORE INTO workspace_jobs(id,kind,payload_json,created_at) VALUES (?,?,?,?)",
                            (row["id"], operation, canonical(payload), now_iso()),
                        )
                    result = {
                        "job": row["id"],
                        "state": "queued for existing worker qualification/research checks",
                    }
            with manual.db:
                manual.db.execute(
                    "UPDATE system_jobs SET state='forwarded',result=? WHERE id=?",
                    (canonical(result), row["id"]),
                )
        except Exception as error:
            with manual.db:
                manual.db.execute(
                    "UPDATE system_jobs SET state='failed',result=? WHERE id=?",
                    (canonical({"error": str(error)[:300]}), row["id"]),
                )
