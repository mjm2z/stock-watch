"""Versioned account performance. Never reinterpret fill-cohort purchases as deposits.

Exact linked snapshot returns require verified flow coverage. A cash flow without
an event valuation invalidates the interval, even if several flows net to zero.
"""
from decimal import Decimal
import json
from .provenance import present, canonical

METHOD = 'account-unitized-observations-v1'
D = Decimal


def link(previous, current, state=None):
    state = dict(state or {'index': 100., 'peak': 100., 'drawdown': 0., 'intervals': 0, 'available': True})
    detail = json.loads(current['details_json'])
    amount = D(current['external_flow'])
    valid = bool(current['flow_coverage'] and current['valuation_complete'] and previous['valuation_complete'])
    valid = valid and D(previous['equity']) > 0 and D(current['equity']) >= 0
    # Nonzero flows need an exact endpoint valuation with an explicit convention.
    if amount or detail.get('flow_events', 0):
        valid = valid and detail.get('flow_timing') == 'end_at_valuation'
    if not valid or not state['available']:
        return {**state, 'available': False, 'reason': 'Incomplete flow coverage or missing cash-flow valuation',
                'return': None, 'maximum_drawdown': None}
    ratio = (D(current['equity']) - amount) / D(previous['equity'])
    if ratio < 0:
        return {**state, 'available': False, 'reason': 'Invalid post-flow equity', 'return': None, 'maximum_drawdown': None}
    index = state['index'] * float(ratio)
    peak = max(state['peak'], index)
    drawdown = min(state['drawdown'], index / peak - 1)
    return dict(index=index, peak=peak, drawdown=drawdown, intervals=state['intervals']+1,
                available=True, reason=None, **{'return': index/100-1, 'maximum_drawdown': drawdown})


def record_mark(db, *, scope, owner, at, equity, cash, flow='0', flow_coverage=False,
                valuation_complete=False, details=None):
    if not present(db, 'performance_marks'):
        return
    for value in (equity, cash, flow):
        if not D(str(value)).is_finite():
            raise ValueError('Nonfinite performance value')
    detail = details or {}
    with db:
        old = db.execute('SELECT * FROM performance_marks WHERE scope=? AND owner_id=? ORDER BY at DESC LIMIT 1', (scope, owner)).fetchone()
        if old and old['at'] >= at:
            return # Idempotent immutable observation; never revise history from a retry.
        current = dict(scope=scope, owner_id=owner, at=at, equity=str(equity), cash=str(cash),
                       external_flow=str(flow), flow_coverage=int(flow_coverage), valuation_complete=int(valuation_complete),
                       details_json=canonical(detail))
        db.execute('INSERT INTO performance_marks VALUES (?,?,?,?,?,?,?,?,?)', tuple(current.values()))
        prior = db.execute('SELECT payload_json FROM performance_results WHERE scope=? AND owner_id=? AND method=?', (scope,owner,METHOD)).fetchone()
        state = json.loads(prior[0]) if prior else None
        result = link(old,current,state) if old else dict(index=100.,peak=100.,drawdown=0.,intervals=0,
                    available=True, reason='At least two complete valuations are required', **{'return':None,'maximum_drawdown':None})
        result.update(scope=scope, owner=owner, method=METHOD, since=state['since'] if state else at,
                      as_of=at, equity=str(equity), cash=str(cash), observations=(state['observations'] if state else 0)+1,
                      valuation='Observed broker snapshots; drawdown between observations is unknown',
                      benchmark={'available':False,'reason':'A funding- and valuation-matched benchmark is not retained'},
                      details=detail)
        detail['return_index'] = result['index'] if result['available'] else None
        db.execute('UPDATE performance_marks SET details_json=? WHERE scope=? AND owner_id=? AND at=?', (canonical(detail),scope,owner,at))
        db.execute('INSERT INTO performance_results VALUES (?,?,?,?,?) ON CONFLICT(scope,owner_id,method) DO UPDATE SET as_of=excluded.as_of,payload_json=excluded.payload_json',
                   (scope,owner,METHOD,at,canonical(result)))


def record_stock_account(db, account, at, activities, matched, newly_observed=()):
    if not present(db,'performance_marks'):return
    old=db.execute("SELECT at FROM performance_marks WHERE scope='stocks_account' AND owner_id=? ORDER BY at DESC LIMIT 1",(account.id,)).fetchone()
    # Activities are read through the existing paginated broker adapter. Unknown
    # cash events block measurement rather than being invented as profit.
    events=[a for a in activities if old and old[0]<a.occurred_at<=at]
    external=[a for a in events if a.activity_type in ('CSD','CSW')]
    ordinary={'DIV','DIVCGL','DIVCGS','DIVNRA','DIVROC','DIVTXEX','INT','FEE','CFEE','SPLIT','MA','SPIN','REORG'}
    unknown=[a.activity_type for a in events if a.activity_type not in ordinary | {'CSD','CSW'}]
    late_flows=[a for a in newly_observed if old and a.occurred_at<=old[0] and a.activity_type not in ordinary]
    flow=sum((D(str(a.net_amount)) for a in external if a.net_amount is not None),D(0))
    record_mark(db,scope='stocks_account',owner=account.id,at=at,equity=account.equity,cash=account.cash,
                flow=flow,flow_coverage=not unknown and not late_flows and all(a.net_amount is not None for a in external),
                valuation_complete=matched,details={'flow_events':len(external),'unknown_activity_types':unknown,'late_cash_events':len(late_flows),
                'flow_timing':'end_at_valuation' if external and all(a.occurred_at==at for a in external) else 'not_valued',
                'source':'Alpaca paper account','currency':account.currency})


def record_bitcoin_account(db, account, at, matched):
    if not present(db,'performance_marks'):return
    old=db.execute("SELECT at FROM performance_marks WHERE scope='bitcoin_account' AND owner_id=? ORDER BY at DESC LIMIT 1",(account['id'],)).fetchone()
    # At most one observation per minute; no network requests or broker mutations.
    if old and old[0][:16]==at[:16]:return
    flows=db.execute('SELECT amount,at FROM paper_cashflows WHERE account_id=? AND at>? AND at<=?',
                     (account['id'],old[0] if old else at,at)).fetchall()
    record_mark(db,scope='bitcoin_account',owner=account['id'],at=at,equity=account['equity'],cash=account['cash'],
                flow=sum((D(r['amount']) for r in flows),D(0)),flow_coverage=matched,valuation_complete=matched,
                details={'source':'Alpaca Bitcoin paper account','currency':account['currency'],
                         'flow_events':len(flows),'flow_timing':'end_at_valuation' if flows and all(r['at']==at for r in flows) else 'not_valued'})
