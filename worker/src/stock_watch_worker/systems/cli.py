"""Independent systems commands; never dispatch legacy stock scans."""
from .automation_config import load_config
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import json
import time
from pathlib import Path

from ..database import apply_migrations, connect
from .bitcoin import BitcoinMonitor, validate_address
from .broker import CryptoBroker
from .engine import SystemConfig, canonical
from .research import audit, now_iso, register_dataset, register_version, run_next
from .runtime import activate, start_shadow, tick


def process_commands(db, broker, asset='bitcoin'):
    for row in db.execute("SELECT c.* FROM system_commands c JOIN system_deployments d ON d.id=c.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE c.status='queued' AND v.asset=? ORDER BY c.created_at,c.id",(asset,)).fetchall():
        try:
            deployment = db.execute('SELECT * FROM system_deployments WHERE id=?',(row['deployment_id'],)).fetchone()
            if row['confirmation'] != row['deployment_id']:
                raise ValueError('Deployment confirmation mismatch')
            if row['action'] == 'activate':
                if asset == 'stocks':
                    from .stocks import activate_stock
                    activate_stock(db,row['deployment_id'],broker,row['confirmation'])
                else:
                    activate(db,row['deployment_id'],broker,row['confirmation'])
            elif row['action'] == 'pause':
                with db:
                    db.execute("UPDATE system_deployments SET mode='paused' WHERE id=?",(row['deployment_id'],))
                    audit(db,'operator_pause',row['deployment_id'],{})
            else:
                # Resume is explicit and cannot erase the original equity high-water mark.
                if deployment['mode'] != 'paused' or not deployment['account_id']:
                    raise ValueError('Only a paused paper deployment can resume')
                account = broker.account()
                if asset=='stocks':
                    from .stocks import system_positions
                    owns_positions=bool(system_positions(db))
                else:
                    owns_positions=bool(broker.positions())
                if account['id'] != deployment['account_id'] or broker.open_orders() or owns_positions:
                    raise ValueError('Resume requires the correct account, no system-owned positions, and no open orders')
                if asset=='bitcoin' and float(account['cash'])/deployment['high_water']-1 <= -.1:
                    raise ValueError('Account remains below its risk limit; create a new reviewed version to change the risk baseline')
                with db:
                    db.execute("UPDATE system_deployments SET mode='paper' WHERE id=?",(row['deployment_id'],))
                    audit(db,'operator_resume',row['deployment_id'],{})
            with db:
                db.execute("UPDATE system_commands SET status='succeeded',finished_at=? WHERE id=?",(now_iso(),row['id']))
        except Exception as error:
            with db:
                db.execute("UPDATE system_commands SET status='failed',finished_at=?,error=? WHERE id=?",(now_iso(),str(error)[:500],row['id']))


def stock_shadow(db):
    """Reuse captured daily stock data without making network calls or stock orders."""
    from .engine import decision
    from .runtime import observe
    rows = db.execute("SELECT d.*,v.config_json FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset='stocks' AND d.mode='shadow'").fetchall()
    if not rows:
        return
    session = db.execute("SELECT trading_date,closes_at FROM market_sessions WHERE closes_at<? ORDER BY trading_date DESC LIMIT 1",(now_iso(),)).fetchone()
    if not session:
        return
    universe_row = db.execute('SELECT id FROM universe_snapshots WHERE effective_at<=? ORDER BY effective_at DESC,id DESC LIMIT 1',(now_iso(),)).fetchone()
    universe = universe_row[0] if universe_row else None
    symbols = db.execute('SELECT i.id,i.symbol FROM instruments i JOIN universe_memberships m ON m.instrument_id=i.id WHERE m.snapshot_id=? ORDER BY i.symbol',(universe,)).fetchall()
    for deployment in rows:
        if deployment['last_decision_at'] == session['trading_date']:
            continue
        config = load_config(json.loads(deployment['config_json']))
        state = json.loads(deployment['state_json'])
        held = set(state.get('held',[]))
        positions=state.get('positions',{})
        decisions, stale = [], []
        for instrument in symbols:
            bars = db.execute("SELECT timestamp,open,high,low,close,volume FROM market_bars WHERE instrument_id=? AND timeframe='1Day' AND adjustment='raw' AND substr(timestamp,1,10)<=? ORDER BY timestamp DESC LIMIT 251",
                              (instrument['id'],session['trading_date'])).fetchall()
            if not bars or bars[0]['timestamp'][:10] != session['trading_date']:
                stale.append(instrument['symbol'])
                continue
            history = list(reversed([dict(b) for b in bars]))
            action,reason = decision(config,history,instrument['symbol'] in held)
            if getattr(config,'protocol',None)=='visual-rules-v1':
                from .rules import position_exit
                p=positions.get(instrument['symbol'],{})
                forced=position_exit(config,history[-1]['close'],p.get('price'),p.get('at'),session['closes_at'])
                if forced:action,reason='sell',forced
            if action == 'buy':
                held.add(instrument['symbol']);positions[instrument['symbol']]={'price':history[-1]['close'],'at':session['closes_at']}
            elif action == 'sell':
                held.discard(instrument['symbol']);positions.pop(instrument['symbol'],None)
            decisions.append({'symbol':instrument['symbol'],'action':action,'reason':reason})
        if not decisions:
            observe(db,deployment['id'],now_iso(),'error',{'message':'Latest completed stock session has no usable daily bars'})
            continue
        observe(db,deployment['id'],now_iso(),'shadow',{'session':session['trading_date'],'decisions':decisions,
                'missing_symbols':stale,'note':'Signal observation only; holdings are hypothetical and not a capital-constrained forward portfolio'})
        with db:
            db.execute('UPDATE system_deployments SET last_decision_at=?,state_json=? WHERE id=?',(session['trading_date'],canonical({'held':sorted(held),'positions':positions}),deployment['id']))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='stock-watch-systems')
    parser.add_argument('--database',type=Path,required=True)
    commands = parser.add_subparsers(dest='command',required=True)
    commands.add_parser('init')
    commands.add_parser('run-next')
    commands.add_parser('chart-next')
    commands.add_parser('monitor')
    commands.add_parser('tick')
    commands.add_parser('automation-tick')
    commands.add_parser('automation-data')
    commands.add_parser('stock-shadow')
    commands.add_parser('stock-tick')
    build = commands.add_parser('build-dataset')
    build.add_argument('--asset',choices=['stocks','bitcoin'],required=True)
    build.add_argument('--start')
    build.add_argument('--end')
    build.add_argument('--storage',type=Path,required=True)
    register = commands.add_parser('register')
    register.add_argument('--asset',choices=['stocks','bitcoin'],required=True)
    register.add_argument('--template',choices=['trend','breakout'],default='trend')
    register.add_argument('--hypothesis',default='')
    dataset = commands.add_parser('import-dataset')
    dataset.add_argument('path',type=Path)
    dataset.add_argument('--storage',type=Path,required=True)
    shadow = commands.add_parser('shadow')
    shadow.add_argument('version')
    watch = commands.add_parser('watch')
    watch.add_argument('address')
    watch.add_argument('--label',default='')
    activate_parser = commands.add_parser('activate')
    activate_parser.add_argument('deployment')
    activate_parser.add_argument('--confirm',required=True)
    args = parser.parse_args(argv)
    # Each command family has a process lock. A terminated runner leaves an explicit
    # failed run rather than permanently blocking the job queue.
    lock_name = 'tick' if args.command in ('activate','tick','automation-tick') else args.command
    with Path(str(args.database)+'.systems-'+lock_name+'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        db = connect(args.database)
        try:
            if args.command == 'init':
                print(canonical({'migrations':apply_migrations(db)}))
                for asset in ('stocks','bitcoin'):
                    for template in ('trend','breakout'):
                        register_version(db,SystemConfig(asset,template),'Frozen baseline hypothesis: trend persistence after costs; invalidate on weak out-of-sample results.')
                # Explicit hourly v2 copies preserve every v1 hash and history.
                from .automation_config import BitcoinConfig
                for row in db.execute("SELECT * FROM system_versions WHERE asset='bitcoin'").fetchall():
                    config=json.loads(row['config_json'])
                    if not config.get('protocol'):
                        config['allocation']=min(.5,config['allocation'])
                        register_version(db,BitcoinConfig(**config),'Hourly automation copy of '+row['id']+'; '+row['hypothesis'])
            elif args.command == 'build-dataset':
                from .datasets import bitcoin_dataset,stock_dataset,save_dataset
                if args.asset=='bitcoin' and (not args.start or not args.end):
                    raise ValueError('Bitcoin history requires --start and --end UTC timestamps')
                data=bitcoin_dataset(args.start,args.end) if args.asset=='bitcoin' else stock_dataset(db)
                print(save_dataset(db,data,args.storage))
            elif args.command == 'register':
                print(register_version(db,SystemConfig(args.asset,args.template),args.hypothesis))
            elif args.command == 'import-dataset':
                print(register_dataset(db,args.path,args.storage))
            elif args.command == 'chart-next':
                from .workspace import run_workspace
                # Display collection cannot run a backtest, authorize or place an order.
                for _ in range(10):
                    if not run_workspace(db,args.database,charts_only=True):break
            elif args.command == 'run-next':
                from .workspace import run_workspace
                run_workspace(db,args.database)
                with db:
                    db.execute("UPDATE system_runs SET status='failed',error='Worker interrupted; rerun explicitly',finished_at=? WHERE status='running'",(now_iso(),))
                print(run_next(db))
                if db.execute('SELECT 1 FROM btc_enrollments LIMIT 1').fetchone():
                    from .history import connect_history
                    from .automation_data import backfill_one,health
                    from .evaluation import run_one
                    history=connect_history(str(args.database)+'.bitcoin-history.db')
                    try:
                        try:
                            if db.execute('SELECT 1 FROM btc_enrollments WHERE active=1 LIMIT 1').fetchone():
                                backfill_one(db,history,CryptoBroker(),datetime.now(timezone.utc))
                        except Exception as error: health(db,'backfill',datetime.now(timezone.utc),str(error)[:500])
                        stop=time.monotonic()+45
                        while time.monotonic()<stop and run_one(db,history): pass
                    finally: history.close()
            elif args.command in ('automation-tick','automation-data'):
                # A newly installed collector has no work until observation is enrolled.
                if args.command=='automation-data' and not db.execute('SELECT 1 FROM btc_enrollments WHERE active=1 LIMIT 1').fetchone():
                    return
                from .history import connect_history
                from .automation_data import collect_forward
                from .coordinator import tick as automation_tick
                history=connect_history(str(args.database)+'.bitcoin-history.db')
                try:
                    (automation_tick if args.command=='automation-tick' else collect_forward)(db,history,CryptoBroker(),datetime.now(timezone.utc))
                finally: history.close()
            elif args.command == 'monitor':
                BitcoinMonitor().collect(db)
            elif args.command == 'stock-tick':
                from .stocks import StockBroker, stock_tick
                broker = StockBroker()
                process_commands(db,broker,'stocks')
                stock_tick(db,broker)
            elif args.command == 'stock-shadow':
                stock_shadow(db)
            elif args.command == 'tick':
                broker = CryptoBroker()
                process_commands(db,broker)
                tick(db,broker)
            elif args.command == 'shadow':
                print(start_shadow(db,args.version))
            elif args.command == 'activate':
                activate(db,args.deployment,CryptoBroker(),args.confirm)
            elif args.command == 'watch':
                address = validate_address(args.address)
                with db:
                    if db.execute('SELECT COUNT(*) FROM bitcoin_watch_addresses').fetchone()[0] >= 20:
                        raise ValueError('Maximum 20 watched addresses')
                    db.execute('INSERT INTO bitcoin_watch_addresses(address,label,added_at) VALUES (?,?,?)',(address,args.label[:120],now_iso()))
                    audit(db,'address_added',address,{'provider':'mempool.space'})
        finally:
            db.close()


if __name__ == '__main__':
    main()
