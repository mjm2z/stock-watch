"""Read-only release checks and upcoming paper exit plans; never submits orders."""
import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from stock_watch_worker.market_calendar import MarketSession, utc_iso
from stock_watch_worker.paper_lifecycle import _lot_schedule

parser = argparse.ArgumentParser()
parser.add_argument('--database', required=True)
args = parser.parse_args()
db = sqlite3.connect(Path(args.database).resolve().as_uri()+'?mode=ro', uri=True)
db.row_factory = sqlite3.Row
db.execute('PRAGMA query_only=ON')
versions = {r[0] for r in db.execute('SELECT version FROM schema_migrations')}
assert {'014_news_revisions','015_exit_timing'} <= versions, 'Missing release migrations'
policy = db.execute("SELECT * FROM paper_exit_timing_policies WHERE strategy_version_id='sp500-long-paper-v2'").fetchone()
assert policy and policy['policy_version'] == 'near-close-v1', 'Exit policy is not active'
missing = db.execute('SELECT COUNT(*) FROM news_articles a WHERE NOT EXISTS '
                    '(SELECT 1 FROM news_revisions r WHERE r.article_id=a.id AND r.content_hash=a.content_hash)').fetchone()[0]
assert missing == 0, 'Original article revisions are missing'
sessions = tuple(MarketSession(date.fromisoformat(r['trading_date']),
    datetime.fromisoformat(r['opens_at'].replace('Z','+00:00')),
    datetime.fromisoformat(r['closes_at'].replace('Z','+00:00')))
    for r in db.execute("SELECT * FROM market_sessions WHERE provider='alpaca-paper' ORDER BY trading_date"))
plans = []
for lot in db.execute("""SELECT l.*,i.symbol FROM paper_trade_lots l
    JOIN instruments i ON i.id=l.instrument_id WHERE l.strategy_version_id='sp500-long-paper-v2'
    AND l.status='open' AND l.opened_at IS NOT NULL ORDER BY l.horizon_trading_days,i.symbol"""):
    schedule = _lot_schedule(opened_at=lot['opened_at'],horizon=lot['horizon_trading_days'],sessions=sessions)
    assert schedule, f"Calendar does not cover {lot['id']}"
    submit_at = utc_iso(datetime.fromisoformat(schedule[1].replace('Z','+00:00'))-timedelta(minutes=5))
    plans.append({'symbol':lot['symbol'],'horizon':lot['horizon_trading_days'],
                  'planned_submit_at':submit_at,'reference_close_at':schedule[1],
                  'recorded_target':lot['target_exit_at']})
print(json.dumps({'policy':dict(policy),'original_articles_preserved':True,'exit_plans':plans},indent=2))
db.close()
