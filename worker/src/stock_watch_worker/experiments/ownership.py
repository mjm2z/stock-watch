"""Process-local capability backed by durable account cutover state."""
from contextlib import contextmanager
from contextvars import ContextVar

_owner=ContextVar('stock_watch_execution_owner',default=None)

@contextmanager
def owning(asset):
    token=_owner.set(asset)
    try: yield
    finally: _owner.reset(token)

def allowed(db,asset):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_authority'").fetchone(): return True
    row=db.execute('SELECT enabled FROM execution_authority WHERE asset=?',(asset,)).fetchone()
    return not row or not row[0] or _owner.get()==asset

def experimental_positions(db,asset):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='experiment_positions'").fetchone(): return {}
    from .model import money
    result={}
    for r in db.execute('''SELECT p.symbol,p.quantity FROM experiment_positions p JOIN experiment_instances i ON i.id=p.instance_id
        JOIN experiment_batches b ON b.id=i.batch_id WHERE b.asset=?''',(asset,)):
        result[r['symbol']]=result.get(r['symbol'],money(0))+money(r['quantity'])
    return result

def baseline_block(db,symbol):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='experiment_orders'").fetchone(): return False
    return db.execute("""SELECT 1 FROM experiment_orders o JOIN experiment_instances i ON i.id=o.instance_id
        JOIN experiment_batches b ON b.id=i.batch_id WHERE b.asset='stocks' AND o.symbol=?
        AND o.status NOT IN ('filled','canceled','expired','rejected') LIMIT 1""",(symbol,)).fetchone() is not None

def shares_account(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='experiment_batches'").fetchone() and
        db.execute("SELECT 1 FROM experiment_batches WHERE asset='stocks' AND status IN ('active','paused','expired','exiting')").fetchone())

def baseline_capacity(db,account,amount,exclude):
    """Called under the owner's write lock with an already-fetched account."""
    from .model import money
    import json
    reserved=sum((money(r[0]) for r in db.execute("SELECT reserved FROM experiment_orders WHERE account_id=? AND status NOT IN ('filled','canceled','expired','rejected')",(account['id'],))),money(0))
    reserved+=sum((money(r[0]) for r in db.execute("SELECT notional_usd FROM paper_orders WHERE id!=? AND status IN ('pending','submitted','accepted','partially_filled')",(exclude,))),money(0))
    for row in db.execute("SELECT request_json FROM system_orders WHERE id!=? AND side='buy' AND status NOT IN ('filled','canceled','expired','rejected')",(exclude,)):
        reserved+=money(json.loads(row[0]).get('notional',0))
    return money(account['cash'])-reserved>=money(amount)
