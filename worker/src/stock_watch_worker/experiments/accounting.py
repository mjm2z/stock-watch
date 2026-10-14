"""Cash reconciliation across original ledgers and experimental instances."""
from datetime import timedelta
from .model import money,stamp

def legacy_cash(db,asset,account):
    if asset=='bitcoin':
        from .legacy_totals import totals
        value=totals(db,account)
        return value['cash_delta']+value['actual_cash']
    revision=db.execute('SELECT revision FROM experiment_stock_revision WHERE id=1').fetchone()[0]
    cached=db.execute('SELECT total FROM experiment_stock_cash_cache WHERE id=1 AND revision=?',(revision,)).fetchone()
    if cached: return money(cached[0])
    total=sum((money(r[0]) for r in db.execute('SELECT notional_usd FROM paper_exit_fills')),money(0))-sum((money(r[0]) for r in db.execute('SELECT notional_usd FROM paper_fills')),money(0))
    for row in db.execute("SELECT o.side,o.filled_qty,o.filled_price FROM system_orders o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset='stocks'"):
        total+=money(row['filled_qty'])*money(row['filled_price'] or 0)*(1 if row['side']=='sell' else -1)
    total+=sum((money(r[0]) for r in db.execute("SELECT net_amount FROM broker_account_activities a WHERE net_amount IS NOT NULL AND activity_type!='FILL' AND NOT EXISTS(SELECT 1 FROM experiment_fee_receipts f WHERE f.id=a.activity_id)")),money(0))
    with db: db.execute('INSERT OR REPLACE INTO experiment_stock_cash_cache VALUES (1,?,?)',(revision,str(total)))
    return total

def experimental_cash(db,account):
    total=money(0)
    for row in db.execute('SELECT filled_notional,side FROM experiment_orders WHERE account_id=?',(account,)):
        total+=money(row['filled_notional'])*(1 if row['side']=='sell' else -1)
    total-=sum((money(r[0]) for r in db.execute('SELECT cash FROM experiment_fees WHERE account_id=? AND applied=1',(account,))),money(0))
    return total

def cash_matches(db,batch,account,now,allow_provisions=True):
    expected=money(batch['cash_anchor'])+legacy_cash(db,batch['asset'],account['id'])-money(batch['legacy_cash_anchor'])+experimental_cash(db,account['id'])-money(batch['experiment_cash_anchor'])
    provision=money(0)
    if batch['asset']=='bitcoin' and allow_provisions:
        provision=sum((money(r[0])*money('.0025') for r in db.execute("""SELECT o.filled_notional FROM experiment_orders o WHERE o.account_id=? AND o.side='sell'
            AND o.updated>=? AND NOT EXISTS(SELECT 1 FROM experiment_fees f WHERE f.order_id=o.id AND f.applied=1)""",(account['id'],stamp(now-timedelta(hours=48))))),money(0))
    return expected-provision-money('.02')<=money(account['cash'])<=expected+money('.02')
