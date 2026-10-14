"""Durable authorization, allocation and short execution-command queue."""
from contextlib import contextmanager
from datetime import timedelta
import json
import uuid
from .model import FAMILIES, config, canonical, digest, instant, stamp, money

@contextmanager
def transaction(db):
    if db.in_transaction: raise RuntimeError('Nested execution transaction')
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise

def health(db,component,now,error=None,detail=None):
    with db:
        db.execute('INSERT OR REPLACE INTO experiment_health VALUES (?,?,?,?)',
            (component,stamp(now),str(error)[:500] if error else None,canonical(detail or {})))

def register(db,cfg,now):
    identifier=digest(cfg)
    db.execute('INSERT OR IGNORE INTO experiment_versions VALUES (?,?,?,?,?)',
        (identifier,cfg['asset'],cfg['family'],canonical(cfg),stamp(now)))
    return identifier

def approval_snapshot(db,asset,account):
    """Detect accounting changes while read-only broker preflight is in flight."""
    revision=db.execute('SELECT revision FROM experiment_stock_revision WHERE id=1').fetchone() if asset=='stocks' else db.execute('SELECT revision FROM btc_ledger_revisions WHERE account_id=?',(account,)).fetchone()
    orders=[tuple(r) for r in db.execute('SELECT id,status,filled_qty,filled_notional,qty_fee_adjustment,cash_fee_adjustment FROM experiment_orders WHERE account_id=? ORDER BY id',(account,))]
    fees=[tuple(r) for r in db.execute('SELECT id,applied,cash,quantity FROM experiment_fees WHERE account_id=? ORDER BY id',(account,))]
    allocations=[tuple(r) for r in db.execute('SELECT version_id,budget FROM btc_allocations ORDER BY version_id')] if asset=='bitcoin' else []
    return revision[0] if revision else 0,orders,fees,allocations

def approval_orders_pending(db,asset,account):
    if db.execute("SELECT 1 FROM experiment_orders WHERE account_id=? AND status NOT IN ('filled','canceled','expired','rejected') LIMIT 1",(account,)).fetchone(): return True
    if asset=='bitcoin':
        return db.execute("SELECT 1 FROM btc_orders WHERE status NOT IN ('filled','canceled','expired','rejected') LIMIT 1").fetchone() is not None
    return db.execute("""SELECT 1 FROM paper_orders WHERE status IN ('pending','submitted','accepted','partially_filled')
        UNION ALL SELECT 1 FROM paper_exit_orders WHERE status IN ('pending','submitted','accepted','partially_filled')
        UNION ALL SELECT 1 FROM system_orders o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id
        WHERE v.asset='stocks' AND o.status NOT IN ('filled','canceled','expired','rejected') LIMIT 1""").fetchone() is not None

def preview(db,asset,broker,now,request_id=None,proposal_id=None):
    identifier=digest({'preview_request':request_id}) if request_id else str(uuid.uuid4())
    old=db.execute('SELECT * FROM experiment_batches WHERE id=?',(identifier,)).fetchone()
    if old: return {'id':old['id'],'revision':old['revision'],'plan':json.loads(old['plan_json'])}
    versions=[config(asset,f) for f in FAMILIES]
    if proposal_id:
        proposal=db.execute('SELECT v.config_json FROM experiment_research_proposals p JOIN experiment_versions v ON v.id=p.version_id WHERE p.id=? AND p.asset=?',(proposal_id,asset)).fetchone()
        if not proposal: raise ValueError('Research proposal unavailable')
        proposed=json.loads(proposal[0]); versions=[proposed if c['family']==proposed['family'] else c for c in versions]

    # Network work precedes the transaction. Approval repeats preflight against
    # the same account and asset metadata before any execution authority exists.
    preflight=broker.preflight(config(asset,'trend')['universe'])
    plan={'protocol':'intraday-batch-v1','asset':asset,'account_id':preflight['account_id'],
        'pool':'1000','unallocated':'150','daily_loss':'0.02','drawdown':'0.10',
        'preflight':preflight,'versions':versions,
        'created':stamp(now),'expires':stamp(now+timedelta(days=30)),
        'approval_label':'Unvalidated paper experiment; not profitability qualification'}
    revision=digest(plan)
    with transaction(db):
        for cfg in plan['versions']: register(db,cfg,now)
        db.execute('INSERT INTO experiment_batches(id,asset,revision,plan_json,created,expires,account_id) VALUES (?,?,?,?,?,?,?)',
            (identifier,asset,revision,canonical(plan),stamp(now),plan['expires'],plan['account_id']))
    return {'id':identifier,'revision':revision,'plan':plan}

def approve(db,identifier,revision,broker,now):
    row=db.execute('SELECT * FROM experiment_batches WHERE id=?',(identifier,)).fetchone()
    if not row or row['revision']!=revision: raise ValueError('Preview revision changed')
    if row['approved']: return {'id':identifier,'status':row['status']}
    if now>=instant(row['created'])+timedelta(minutes=30): raise ValueError('Preview expired; generate a fresh preview')
    plan=json.loads(row['plan_json']); current=broker.preflight(plan['versions'][0]['universe'])
    if current!=plan['preflight']: raise ValueError('Account eligibility changed; preview again')
    from .accounting import legacy_cash,experimental_cash
    snapshot=approval_snapshot(db,row['asset'],row['account_id'])
    baseline=legacy_cash(db,row['asset'],row['account_id']); experimental=experimental_cash(db,row['account_id'])
    account=broker.account()
    if account['id']!=row['account_id']: raise ValueError('Account identity changed during preflight')
    from pathlib import Path
    import os
    import sqlite3
    main_path=db.execute('PRAGMA database_list').fetchone()[2]
    manual_path=Path(os.environ.get('STOCK_WATCH_MANUAL_DATABASE') or str(Path(main_path).with_name('manual-paper.db'))) if main_path else None
    if manual_path and manual_path.exists():
        from contextlib import closing
        with closing(sqlite3.connect(manual_path.resolve().as_uri()+'?mode=ro',uri=True)) as manual:
            if manual.execute('SELECT 1 FROM accounts WHERE account_id=?',(account['id'],)).fetchone():
                raise ValueError('Experimental and manual broker identities must be separate')
    if money(account['cash'])<1000: raise ValueError('At least $1,000 cash is required')
    if broker.open_orders() or approval_orders_pending(db,row['asset'],account['id']):
        raise ValueError('Outstanding orders must reconcile before approving a pool')
    from .engine import reconciled
    matched,reason=reconciled(db,broker,row['asset'],account)
    if not matched: raise ValueError('Account preflight: '+str(reason))
    if row['asset']=='bitcoin':
        # Existing allocations remain intact. They cannot also finance this pool.
        committed=sum((money(r[0]) for r in db.execute('SELECT budget FROM btc_allocations')),money(0))
        local=db.execute('SELECT initial_cash FROM btc_accounts WHERE id=?',(row['account_id'],)).fetchone()
        if committed and (not local or money(local[0])-committed<1000):
            raise ValueError('Existing Bitcoin allocations leave less than $1,000 unallocated')
    with transaction(db):
        if approval_snapshot(db,row['asset'],account['id'])!=snapshot or approval_orders_pending(db,row['asset'],account['id']):
            raise ValueError('Account ledger changed during preflight; retry approval')
        fresh=db.execute('SELECT * FROM experiment_batches WHERE id=?',(identifier,)).fetchone()
        if fresh['status']!='preview': raise ValueError('Preview is no longer available')
        if db.execute("SELECT 1 FROM experiment_batches WHERE asset=? AND status IN ('active','paused','exiting','expired')",(row['asset'],)).fetchone():
            raise ValueError('An existing batch still owns this asset pool')
        if not db.execute('SELECT 1 FROM execution_authority WHERE asset=? AND enabled=1',(row['asset'],)).fetchone():
            raise ValueError('The account execution owner has not completed cutover')
        for cfg in plan['versions']:
            version=digest(cfg); instance=digest({'batch':identifier,'version':version})
            db.execute("INSERT INTO experiment_instances(id,batch_id,version_id,budget,cash,state) VALUES (?,?,?,?,?,'collecting')",
                (instance,identifier,version,cfg['allocation'],cfg['allocation']))
        db.execute("UPDATE experiment_batches SET status='active',approved=?,cash_anchor=?,legacy_cash_anchor=?,experiment_cash_anchor=?,state_revision=state_revision+1 WHERE id=?",
            (stamp(now),str(account['cash']),str(baseline),str(experimental),identifier))
    return {'id':identifier,'status':'active'}

def controls(db,body,action,now):
    identifier=body.get('instance_id'); batch_id=body.get('batch_id')
    if not identifier and not batch_id: raise ValueError('Choose a batch or instance')
    with transaction(db):
        rows=db.execute('''SELECT i.*,b.risk_reason,b.status FROM experiment_instances i JOIN experiment_batches b ON b.id=i.batch_id
            WHERE i.id=? OR (? IS NOT NULL AND i.batch_id=?)''',(identifier,batch_id,batch_id)).fetchall()
        if not rows: raise ValueError('Experiment not found')
        if action=='resume' and any(r['risk_reason'] or r['status'] in ('expired','exiting','completed') for r in rows):
            raise ValueError('Risk breach or expiration cannot be reset by resume')
        for row in rows:
            paused=action in ('pause','exit_and_pause') or (action=='exit' and row['paused'])
            exiting=action in ('exit','exit_and_pause')
            db.execute('UPDATE experiment_instances SET paused=?,exit_requested=?,state=?,reason=? WHERE id=?',
                (int(paused),int(exiting),'exiting' if exiting else 'paused' if paused else 'ready','operator_'+action,row['id']))
            db.execute('UPDATE experiment_batches SET state_revision=state_revision+1 WHERE id=?',(row['batch_id'],))
    return {'action':action,'instances':len(rows)}

def dispatch(db,asset,broker,now,actions=None,limit=10):
    actions=actions or ('preview','approve','pause','resume','exit','exit_and_pause')
    placeholders=','.join('?' for _ in actions)
    for row in db.execute(f"SELECT * FROM experiment_commands WHERE asset=? AND status='pending' AND action IN ({placeholders}) ORDER BY created,id LIMIT ?",(asset,*actions,limit)).fetchall():
        try:
            body=json.loads(row['payload_json']); action=row['action']
            if action=='preview': result=preview(db,asset,broker,now,row['id'],body.get('proposal_id'))
            elif action=='approve': result=approve(db,body['batch_id'],body['revision'],broker,now)
            elif action in ('pause','resume','exit','exit_and_pause'): result=controls(db,body,action,now)
            else: raise ValueError('Unknown experiment command')
            status='succeeded'
        except Exception as error:
            status='failed'; result={'error':str(error)[:500]}
        with db:
            db.execute('UPDATE experiment_commands SET status=?,result_json=?,completed=? WHERE id=? AND status=\'pending\'',
                (status,canonical(result),stamp(now),row['id']))
