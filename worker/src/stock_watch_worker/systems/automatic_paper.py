"""Policy authorization for experimental Bitcoin PAPER entries only.

Order submission remains exclusively owned by the existing paper coordinator.
"""
from decimal import Decimal
import json
from .engine import instant,canonical
from .discovery import policy,event
D=Decimal

def available(db):return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='paper_authorizations'").fetchone())

def eligible(db,version,now):
    if not available(db):return None
    p=policy(db)
    if not p or not p['enabled']:return None
    row=db.execute('''SELECT a.*,t.expires_at,t.status AS trial_status,t.result_json,t.budget AS tested_budget,
        n.active,n.paused,b.started_at,b.budget AS allocated_budget FROM paper_authorizations a
        JOIN discovery_trials t ON t.id=a.trial_id JOIN btc_enrollments n ON n.version_id=a.version_id
        JOIN btc_allocations b ON b.version_id=a.version_id WHERE a.version_id=?''',(version,)).fetchone()
    if not row or row['status']!='active' or row['policy_id']!=p['id'] or not row['active'] or row['paused'] or not row['started_at']:return None
    if row['account_id']!=db.execute('SELECT account_id FROM btc_allocations WHERE version_id=?',(version,)).fetchone()[0]:return None
    if row['trial_status']!='completed' or not row['expires_at'] or instant(row['expires_at'])<=now:return None
    result=json.loads(row['result_json'] or '{}')
    if not result.get('passed') or result.get('scenario_count')!=100 or result.get('scenario_pass_rate',0)<p['threshold']:return None
    if D(row['allocated_budget'])!=D(row['tested_budget']) or D(row['budget'])!=D(row['allocated_budget']):return None
    if D(row['budget'])>D(p['sleeve']):return None
    health=db.execute("SELECT * FROM btc_health WHERE key='data'").fetchone()
    if not health or health['error'] or not 0<=(now-instant(health['at'])).total_seconds()<=120:return None
    return row['trial_id']

def prepare(db,broker,now):
    if not available(db):return
    p=policy(db)
    if not p['enabled']:return
    trials=db.execute("SELECT * FROM discovery_trials WHERE asset='bitcoin' AND status='completed' AND policy_id=? AND expires_at>? AND json_extract(result_json,'$.passed')=1 AND id=(SELECT newest.id FROM discovery_trials newest WHERE newest.version_id=discovery_trials.version_id AND newest.policy_id=discovery_trials.policy_id AND newest.status='completed' ORDER BY newest.finished_at DESC,newest.id DESC LIMIT 1) ORDER BY finished_at,id",(p['id'],now.isoformat())).fetchall()
    if not trials:return
    from .coordinator import reconcile,active_orders
    from .automation_data import health
    try:
        account=broker.account()
        if db.execute("SELECT 1 FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset='bitcoin' AND d.account_id IS NOT NULL").fetchone():raise ValueError('Legacy Bitcoin account ownership requires review')
        local=db.execute('SELECT * FROM btc_accounts').fetchone()
        if not local:
            if broker.positions() or broker.open_orders():raise ValueError('Initial paper setup requires a flat dedicated account')
            cash=D(account['cash'])
            if not cash.is_finite() or not 0<cash<=D(p['pool']):raise ValueError('Set up a separate paper account with a positive balance no greater than the configured $1,000 pool; StockWatch never resets broker balances')
            with db:db.execute('INSERT INTO btc_accounts(id,initial_cash,cash,high_water,created_at) VALUES (?,?,?,?,?)',(account['id'],str(cash),str(cash),str(cash),now.isoformat()))
            local=db.execute('SELECT * FROM btc_accounts').fetchone()
        if local['id']!=account['id'] or local['risk_paused']:raise ValueError('Paper account identity or risk pause blocks authorization')
        if not reconcile(db,broker,account,now):raise ValueError('Reconcile paper cash, positions and fees before authorization')
        if active_orders(db):raise ValueError('Waiting for unsettled paper orders')
        blocked=None
        for trial in trials:
            summary=json.loads(trial['result_json'])
            if summary.get('scenario_count')!=100 or summary.get('scenario_pass_rate',0)<p['threshold']:continue
            version=trial['version_id'];enrollment=db.execute('SELECT * FROM btc_enrollments WHERE version_id=?',(version,)).fetchone()
            if enrollment and (not enrollment['active'] or enrollment['paused']):continue
            db.execute('BEGIN IMMEDIATE')
            try:
                # Serialize capital reservation and recheck policy after any broker reads.
                if policy(db)['id']!=p['id'] or not policy(db)['enabled']:raise ValueError('Policy changed during authorization')
                old=db.execute('SELECT * FROM btc_allocations WHERE version_id=?',(version,)).fetchone()
                auth=db.execute('SELECT * FROM paper_authorizations WHERE version_id=?',(version,)).fetchone()
                if old and not auth:db.rollback();continue # Never take over manual authority.
                if old and (old['risk_paused'] or D(old['budget'])!=D(trial['budget'])):db.rollback();continue
                if not old:
                    cash=D(db.execute('SELECT cash FROM btc_accounts WHERE id=?',(account['id'],)).fetchone()[0])
                    rows=db.execute('SELECT budget FROM btc_allocations').fetchall()
                    reserved=sum((D(r[0]) for r in rows),D(0));budget=D(trial['budget'])
                    if len(rows)>=5 or budget>D(p['sleeve']) or reserved+budget>D(p['pool']) or cash<budget:
                        db.rollback();blocked='Waiting for available paper capital or a system slot';continue
                    if not enrollment and db.execute('SELECT COUNT(*) FROM btc_enrollments WHERE active=1').fetchone()[0]>=5:db.rollback();continue
                    db.execute('INSERT OR IGNORE INTO btc_enrollments(version_id,enrolled_at) VALUES (?,?)',(version,now.isoformat()))
                    db.execute('INSERT INTO btc_allocations(version_id,account_id,budget,cash,high_water,approved_at,started_at) VALUES (?,?,?,?,?,?,?)',
                        (version,account['id'],str(budget),str(budget),str(budget),now.isoformat(),now.isoformat()))
                    db.execute('UPDATE btc_accounts SET cash=? WHERE id=?',(str(cash-budget),account['id']))
                db.execute('INSERT INTO paper_authorizations VALUES (?,?,?,?,?,?,\'active\') ON CONFLICT(version_id) DO UPDATE SET trial_id=excluded.trial_id,policy_id=excluded.policy_id,approved_at=excluded.approved_at,status=excluded.status',
                    (version,trial['id'],p['id'],now.isoformat(),trial['budget'],account['id']))
                db.execute('UPDATE btc_enrollments SET approved_at=COALESCE(approved_at,?) WHERE version_id=?',(now.isoformat(),version))
                db.commit()
                if not auth or auth['trial_id']!=trial['id']:event(db,'bitcoin','automatic_paper_authorized',version,{'trial':trial['id'],'policy':p['id'],'budget':trial['budget'],'mode':'experimental paper','entry':'Next valid signal only'})
            except Exception:db.rollback();raise
        health(db,'automatic-paper',now,blocked)
    except Exception as error:health(db,'automatic-paper',now,str(error)[:500])

def cashflow(db,broker,amount,identifier,now):
    """Explicitly reconcile a real paper deposit/withdrawal; no broker reset call."""
    from .coordinator import active_orders
    value=D(str(amount));p=policy(db);account=broker.account()
    local=db.execute('SELECT * FROM btc_accounts WHERE id=?',(account['id'],)).fetchone()
    if db.execute('SELECT 1 FROM paper_cashflows WHERE id=?',(identifier,)).fetchone():return
    if not value.is_finite() or not local or local['risk_paused'] or active_orders(db) or broker.open_orders() or broker.positions():raise ValueError('Cash-flow reconciliation requires a flat, unpaused, settled account')
    allocations=db.execute('SELECT * FROM btc_allocations').fetchall()
    if any(D(a['quantity']) or a['risk_paused'] for a in allocations):raise ValueError('Existing allocations are not settled')
    expected=D(local['cash'])+sum((D(a['cash']) for a in allocations),D(0))+value
    if abs(D(account['cash'])-expected)>D('.01') or not 0<expected<=D(p['pool']) or D(local['cash'])+value<0:raise ValueError('Cash flow does not reconcile to available capital and pool cap')
    with db:
        db.execute('INSERT INTO paper_cashflows VALUES (?,?,?,?,?)',(identifier,account['id'],str(value),now.isoformat(),'Operator-confirmed paper cash flow'))
        db.execute('UPDATE btc_accounts SET initial_cash=?,cash=?,high_water=? WHERE id=?',
            (str(D(local['initial_cash'])+value),str(D(local['cash'])+value),str(D(local['high_water'])+value),account['id']))
