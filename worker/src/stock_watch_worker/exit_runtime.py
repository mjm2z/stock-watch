"""Fast exit-only ticks, independent of scan collection and outcome evaluation."""
from datetime import datetime, date
import json

from .market_calendar import MarketSession, NEW_YORK
from .paper_lifecycle import reconcile_paper_lifecycle
from .config import load_strategy_document


def activate_exit_policy(connection, strategy_id):
    row = connection.execute("SELECT config_json,config_sha256,status FROM strategy_versions WHERE id=?",
                             (strategy_id,)).fetchone()
    if row is None or row['status'] != 'paper':
        raise ValueError('Exit policy requires a paper strategy')
    strategy = load_strategy_document(json.loads(row['config_json']))
    if strategy.sha256 != row['config_sha256']:
        raise ValueError('Strategy hash mismatch')
    with connection:
        result = connection.execute(
            "INSERT INTO paper_exit_timing_policies(strategy_version_id,policy_version,minutes_before_close) "
            "VALUES (?,'near-close-v1',5) ON CONFLICT DO NOTHING", (strategy_id,))
        if result.rowcount:
            connection.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,payload_json) "
                "VALUES ('paper_exit_policy_activated','strategy_version',?,?)",
                (strategy_id,json.dumps({'policy':'near-close-v1','minutes_before_close':5,
                 'scope':'existing unclosed and future lots; existing broker orders reconciled',
                 'benchmark':'horizon close remains a research benchmark, not an assumed fill'})))


def process_exit_tick(connection, broker, now: datetime):
    active = connection.execute("""SELECT 1 FROM paper_trade_lots l
        JOIN paper_exit_timing_policies p ON p.strategy_version_id=l.strategy_version_id
        WHERE l.status IN ('open','closing') LIMIT 1""").fetchone()
    if active is None:
        return None
    rows = connection.execute("SELECT trading_date,opens_at,closes_at FROM market_sessions "
                              "WHERE provider='alpaca-paper' ORDER BY trading_date").fetchall()
    sessions = tuple(MarketSession(date.fromisoformat(row['trading_date']),
        datetime.fromisoformat(row['opens_at'].replace('Z','+00:00')),
        datetime.fromisoformat(row['closes_at'].replace('Z','+00:00'))) for row in rows)
    today = now.astimezone(NEW_YORK).date()
    if not sessions or today > sessions[-1].trading_date:
        raise ValueError('Exit calendar unavailable or expired; run calendar maintenance')
    session = next((s for s in sessions if s.trading_date == today),None)
    if session is None or not session.opens_at <= now < session.closes_at:
        return None
    result = reconcile_paper_lifecycle(connection,broker=broker,sessions=sessions,
                                      now=now,reconcile_entries=False,managed_only=True)
    failures = connection.execute("""SELECT e.id,e.status FROM paper_exit_orders e
        JOIN paper_trade_lots l ON l.id=e.lot_id
        WHERE l.exit_timing_policy='near-close-v1' AND l.status='closing'
          AND e.status IN ('rejected','canceled','error')""").fetchall()
    if failures:
        raise ValueError('Exit requires reconciliation: '+', '.join(f"{r['id']} ({r['status']})" for r in failures))
    return result
