"""Independent stock account owner; Bitcoin invokes tick from its existing owner."""
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import time
import threading
from ..database import connect
from .broker import Broker
from .evidence import connect as connect_evidence
from .ownership import owning
from .store import dispatch, health
from .engine import tick

def legacy_tick(db,now):
    from ..systems.stocks import StockBroker, stock_tick
    from ..exit_runtime import process_exit_tick
    from ..paper_lifecycle import submit_or_reconcile_exit
    from ..paper_orders import submit_or_reconcile_order
    from ..entry_controls import prepare_due_entries, process_deferred_entries
    broker=StockBroker()
    process_exit_tick(db,broker.client,now)
    for r in db.execute("SELECT id FROM paper_exit_orders WHERE status IN ('pending','submitted','accepted','partially_filled') ORDER BY updated_at LIMIT 100").fetchall():
        submit_or_reconcile_exit(db,exit_order_id=r['id'],broker=broker.client,now=now)
    from ..systems.cli import process_commands
    process_commands(db,broker,'stocks')
    stock_tick(db,broker,now)
    prepare_due_entries(db,broker.client,now)
    for r in db.execute("SELECT id FROM paper_orders WHERE status IN ('pending','submitted','accepted','partially_filled') ORDER BY updated_at LIMIT 100").fetchall():
        submit_or_reconcile_order(db,order_id=r['id'],broker=broker.client,now=now)
    process_deferred_entries(db,broker.client,now)

def experiment_tick(db,market,asset,now):
    dispatch(db,asset,None,now,actions=('pause','resume','exit','exit_and_pause'))
    broker=Broker(asset)
    tick(db,market,broker,asset,now)

def start_preflight_worker(path,asset,stop):
    """Read-only broker preflight cannot stall the account's order/exit loop.

    This worker owns a separate SQLite connection. It can freeze/approve a batch
    but never submits, cancels or reconciles an order. Controls stay on the owner.
    One preflight command per 15 seconds also bounds API use.
    """
    def run_preflights():
        connection=connect(path)
        try:
            while not stop.is_set():
                now=datetime.now(timezone.utc)
                try:
                    pending=connection.execute("SELECT 1 FROM experiment_commands WHERE asset=? AND status='pending' AND action IN ('preview','approve') LIMIT 1",(asset,)).fetchone()
                    if pending: dispatch(connection,asset,Broker(asset),now,actions=('preview','approve'),limit=1)
                    health(connection,'preflight:'+asset,now)
                except Exception as error: health(connection,'preflight:'+asset,now,error)
                stop.wait(15)
        finally: connection.close()
    thread=threading.Thread(target=run_preflights,name='paper-preflight-'+asset,daemon=True)
    thread.start()
    return thread

def run(path):
    with Path(str(path)+'.stock-owner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        db=connect(path); market=connect_evidence(str(path)+'.experiment-evidence.db')
        with db: db.execute("UPDATE execution_authority SET enabled=1 WHERE asset='stocks'")
        stop=threading.Event(); preflights=start_preflight_worker(path,'stocks',stop)
        try:
            with owning('stocks'):
                while True:
                    now=datetime.now(timezone.utc)
                    # Independent errors cannot disable the other exit ledger.
                    for name,operation in [('stock-baseline-owner',lambda:legacy_tick(db,now)),('stock-experiment-owner',lambda:experiment_tick(db,market,'stocks',now))]:
                        try: operation(); health(db,name,now)
                        except Exception as error: health(db,name,now,error)
                    time.sleep(5)
        finally:
            stop.set(); preflights.join(timeout=2); db.close(); market.close()

if __name__=='__main__': run(os.environ['STOCK_WATCH_DATABASE_PATH'])
