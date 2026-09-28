"""Entry pauses and explicit exits do not alter risk pauses or ownership."""

import json
from .engine import canonical
from .research import audit, now_iso


def read(db, version):
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='system_entry_controls'"
    ).fetchone():
        return {}
    row = db.execute(
        "SELECT * FROM system_entry_controls WHERE version_id=?", (version,)
    ).fetchone()
    return dict(row) if row else {}


def request(db, version, action, attribution):
    if action not in ("pause", "resume", "exit", "exit_and_pause"):
        raise ValueError("Unsupported system control")
    row = db.execute("SELECT * FROM system_versions WHERE id=?", (version,)).fetchone()
    if not row:
        raise ValueError("Unknown system version")
    old = read(db, version)
    paused = old.get("paused", 0)
    if action in ("pause", "exit_and_pause"):
        paused = 1
    if action == "resume":
        paused = 0
    at = now_iso()
    with db:
        db.execute(
            """INSERT INTO system_entry_controls VALUES (?,?,?,?,?,?) ON CONFLICT(version_id) DO UPDATE SET
          paused=excluded.paused,exit_requested=excluded.exit_requested,decision_floor=excluded.decision_floor,
          updated_at=excluded.updated_at,attribution_json=excluded.attribution_json""",
            (
                version,
                paused,
                1
                if action in ("exit", "exit_and_pause")
                else old.get("exit_requested", 0),
                at
                if action in ("exit", "exit_and_pause")
                else old.get("decision_floor"),
                at,
                canonical(attribution),
            ),
        )
        audit(db, "operator_" + action, version, attribution)
    return {"version": version, "action": action, "entries_paused": bool(paused)}


def complete_exit(db, version):
    with db:
        db.execute(
            "UPDATE system_entry_controls SET exit_requested=0 WHERE version_id=?",
            (version,),
        )
