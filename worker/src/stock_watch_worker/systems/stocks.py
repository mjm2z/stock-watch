"""Stock-system cutover and account-wide position ownership.

Legacy lots retain their own independent close timers. The durable control row
only disables legacy entries, including while the replacement system is paused.
"""
from .automation_config import load_config
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
import sqlite3
import uuid

from ..http import ProviderError
from ..providers.alpaca import AlpacaCredentials, AlpacaPaperTradingClient
from .engine import SystemConfig, canonical, decision, instant
from .research import audit, now_iso
from .runtime import TERMINAL, observe


def legacy_entries_disabled(db):
    # Older installations without the additive migration retain their behavior.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_stock_control'").fetchone():
        return False
    return db.execute('SELECT 1 FROM system_stock_control WHERE id=1').fetchone() is not None


def system_positions(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_orders'").fetchone():
        return {}
    rows = db.execute("SELECT o.symbol,SUM(CASE WHEN o.side='buy' THEN CAST(o.filled_qty AS REAL) ELSE -CAST(o.filled_qty AS REAL) END) AS qty FROM system_orders o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset='stocks' GROUP BY o.symbol").fetchall()
    return {r['symbol']:float(r['qty']) for r in rows if float(r['qty']) > 1e-9}


class StockBroker:
    def __init__(self):
        self.client = AlpacaPaperTradingClient(AlpacaCredentials.from_environment())
    def account(self): return self.client.get_account().raw
    def positions(self): return [p.raw for p in self.client.get_positions()]
    def open_orders(self): return self.client._get('/v2/orders',{'status':'open','limit':'500'})
    def lookup(self, identifier):
        try: return self.client.get_order_by_client_order_id(identifier)
        except ProviderError as error:
            if error.status == 404: return None
            raise
    def submit(self, identifier, symbol, side, request):
        if side == 'buy': return self.client.submit_notional_market_buy(symbol=symbol,notional_usd=request['notional'],client_order_id=identifier)
        return self.client.submit_fractional_market_sell(symbol=symbol,quantity=request['qty'],client_order_id=identifier)
    def quote(self, symbol): return self.client.get_entry_context(symbol)
    def cancel(self, identifier):
        from ..http import require_success
        from urllib.parse import quote
        response=self.client._transport.request('DELETE','https://paper-api.alpaca.markets/v2/orders/'+quote(identifier,safe=''),headers=self.client._headers(),timeout=10)
        if response.status != 204: require_success('alpaca-paper',response)


def activate_stock(db, identifier, broker, confirmation, now=None):
    from ..broker_reconciliation import _expected_positions
    now = now or datetime.now(timezone.utc)
    if confirmation != identifier: raise ValueError('Deployment confirmation mismatch')
    deployment = db.execute("SELECT d.*,v.asset FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE d.id=?",(identifier,)).fetchone()
    if not deployment or deployment['asset'] != 'stocks' or deployment['mode'] != 'shadow':
        raise ValueError('Requires a stock shadow deployment')
    observations = db.execute("SELECT payload_json,observed_at FROM system_observations WHERE deployment_id=? AND kind='shadow' ORDER BY observed_at",(identifier,)).fetchall()
    sessions = {json.loads(o['payload_json']).get('session') for o in observations}
    sessions.discard(None)
    if len(sessions)<20 or (now-instant(observations[-1]['observed_at'])).total_seconds()>4*86400:
        raise ValueError('Requires 20 observed market sessions and recent shadow data')
    runs = db.execute("SELECT result_json FROM system_runs WHERE version_id=? AND status='succeeded' ORDER BY finished_at DESC LIMIT 1",(deployment['version_id'],)).fetchone()
    if not runs or not json.loads(runs[0]).get('folds'):
        raise ValueError('A reviewed walk-forward backtest is required')
    account, positions = broker.account(), broker.positions()
    actual = {p['symbol']:float(p['qty']) for p in positions}
    expected = _expected_positions(db)
    if any(abs(actual.get(s,0)-expected.get(s,0))>1e-6 for s in set(actual)|set(expected)):
        raise ValueError('Stock account must reconcile before cutover')
    if system_positions(db):
        raise ValueError('Previous stock-system positions must close before another system replaces it')
    if account.get('trading_blocked') or account.get('account_blocked') or broker.open_orders():
        raise ValueError('Account blocked or orders outstanding; reconcile before cutover')
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM paper_orders WHERE status IN ('pending','submitted','accepted','partially_filled') LIMIT 1").fetchone():
            raise ValueError('Legacy entry intents must settle before cutover')
        if db.execute("SELECT 1 FROM system_deployments d JOIN system_versions v ON v.id=d.version_id WHERE v.asset='stocks' AND d.mode='paper'").fetchone():
            raise ValueError('A stock system is already active')
        db.execute('INSERT INTO system_stock_control VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET deployment_id=excluded.deployment_id,activated_at=excluded.activated_at',(identifier,now.isoformat()))
        db.execute("UPDATE system_deployments SET mode='paper',account_id=?,state_json=? WHERE id=?",(account['id'],canonical({'paper_started_at':now.isoformat()}),identifier))
        audit(db,'stock_entries_replaced',identifier,{'account_id':account['id'],'legacy_lots':'retain original exits'})


def reconcile(db, deployment, broker, *, allow_entries=True, now=None):
    now=now or datetime.now(timezone.utc)
    for order in db.execute('SELECT * FROM system_orders WHERE deployment_id=?',(deployment,)).fetchall():
        if order['status'] in TERMINAL: continue
        found = broker.lookup(order['id'])
        expired=(now-instant(order['created_at'])).total_seconds()>900
        if found is None and order['side']=='buy' and (not allow_entries or expired):
            with db: db.execute("UPDATE system_orders SET status='canceled',updated_at=? WHERE id=?",(now_iso(),order['id']))
            continue
        if found is None:
            request=json.loads(order['request_json'])
            if order['side']=='buy':
                context=broker.quote(order['symbol'])
                quote=context.get('quote')
                if not context['clock'].get('is_open') or not quote: continue
                if not all(math.isfinite(float(quote[k])) and float(quote[k])>0 for k in ('bp','ap')): continue
                if not 0<=(now-instant(quote['t'])).total_seconds()<=120: continue
                if float(quote['ap'])/float(quote['bp'])-1>.01 or float(quote['ap'])<float(quote['bp']): continue
                reference=float(request.get('reference_price',0))
                if reference<=0 or abs(float(quote['ap'])/reference-1)>.05:
                    with db: db.execute("UPDATE system_orders SET status='rejected',updated_at=? WHERE id=?",(now.isoformat(),order['id']))
                    continue
            found = broker.submit(order['id'],order['symbol'],order['side'],request)
        with db:
            db.execute('UPDATE system_orders SET broker_id=?,status=?,filled_qty=?,filled_price=?,updated_at=?,response_json=? WHERE id=?',
                       (found['id'],found['status'],found.get('filled_qty','0'),found.get('filled_avg_price'),now_iso(),canonical(found),order['id']))


def stock_tick(db, broker, now=None):
    from ..broker_reconciliation import _expected_positions
    now = now or datetime.now(timezone.utc)
    at = now.isoformat()
    deployment = db.execute('SELECT d.*,v.config_json,v.config_sha256 FROM system_stock_control c JOIN system_deployments d ON d.id=c.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE c.id=1').fetchone()
    if not deployment: return
    identifier = deployment['id']
    try:
        account = broker.account()
        if account['id'] != deployment['account_id'] or account.get('trading_blocked') or account.get('account_blocked'):
            raise ValueError('Stock account preflight failed')
        # Closed-market ticks still reconcile acknowledgements; never submit unknown intents off-session.
        session = db.execute('SELECT * FROM market_sessions WHERE opens_at<=? AND closes_at>? ORDER BY opens_at DESC LIMIT 1',(at,at)).fetchone()
        if not session: return
        entry_window=instant(session['opens_at'])+timedelta(minutes=15)<=now<instant(session['opens_at'])+timedelta(minutes=30)
        reconcile(db,identifier,broker,allow_entries=deployment['mode']=='paper' and entry_window,now=now)
        if deployment['mode']=='paused':
            for order in db.execute("SELECT * FROM system_orders WHERE deployment_id=? AND side='buy'",(identifier,)):
                if order['status'] not in TERMINAL and order['broker_id']: broker.cancel(order['broker_id'])
        if broker.open_orders(): return
        actual = {p['symbol']:float(p['qty']) for p in broker.positions()}
        expected = _expected_positions(db)
        if any(abs(actual.get(s,0)-expected.get(s,0))>1e-6 for s in set(actual)|set(expected)):
            raise ValueError('Stock position mismatch; systems entries blocked')
        own = system_positions(db)
        previous = db.execute('SELECT * FROM market_sessions WHERE trading_date<? ORDER BY trading_date DESC LIMIT 1',(session['trading_date'],)).fetchone()
        if not previous: raise ValueError('Previous stock session unavailable')
        config = load_config(json.loads(deployment['config_json']))
        if config.sha256 != deployment['config_sha256']: raise ValueError('Immutable strategy hash mismatch')
        # Signal on the previous completed daily bar. New entries at 09:45;
        # rule exits at five minutes before today's actual session close.
        buy_window = instant(session['opens_at'])+timedelta(minutes=15) <= now < instant(session['opens_at'])+timedelta(minutes=30)
        sell_window = instant(session['closes_at'])-timedelta(minutes=5) <= now < instant(session['closes_at'])
        universe_row = db.execute('SELECT id FROM universe_snapshots WHERE effective_at<=? ORDER BY effective_at DESC,id DESC LIMIT 1',(at,)).fetchone()
        universe = universe_row[0] if universe_row else None
        instruments = db.execute('SELECT i.id,i.symbol,c.sector FROM instruments i LEFT JOIN instrument_context c ON c.instrument_id=i.id WHERE i.active=1 AND (i.id IN (SELECT instrument_id FROM universe_memberships WHERE snapshot_id=?) OR i.symbol IN (SELECT symbol FROM system_orders WHERE deployment_id=?)) ORDER BY i.symbol',(universe,identifier)).fetchall()
        candidates = []
        for instrument in instruments:
            bars = db.execute("SELECT * FROM market_bars WHERE instrument_id=? AND timeframe='1Day' AND adjustment='raw' AND substr(timestamp,1,10)<=? ORDER BY timestamp DESC LIMIT 251",(instrument['id'],previous['trading_date'])).fetchall()
            if not bars or bars[0]['timestamp'][:10] != previous['trading_date']: continue
            history = list(reversed([dict(b) for b in bars]))
            action,reason = decision(config,history,instrument['symbol'] in own)
            if instrument['symbol'] in own and getattr(config,'protocol',None)=='visual-rules-v1':
                from .rules import position_exit
                entry=db.execute("SELECT filled_price,created_at FROM system_orders WHERE deployment_id=? AND symbol=? AND side='buy' AND CAST(filled_qty AS REAL)>0 ORDER BY created_at DESC LIMIT 1",(identifier,instrument['symbol'])).fetchone()
                if entry:
                    forced=position_exit(config,history[-1]['close'],entry['filled_price'],entry['created_at'],at)
                    if forced:action,reason='sell',forced
            if deployment['mode']=='paused': action = 'sell' if instrument['symbol'] in own else 'hold'
            momentum = history[-1]['close']/history[-21]['close']-1 if len(history)>=21 else 0
            candidates.append((action,-momentum,instrument['symbol'],instrument,reason))
        for action,_,symbol,instrument,reason in sorted(candidates,key=lambda x:(x[0]!='sell',x[1],x[2])):
            if action=='hold' or (action=='buy' and (not buy_window or deployment['mode']!='paper')) or (action=='sell' and not sell_window and deployment['mode']!='paused'): continue
            client_id = 'sys-'+uuid.uuid5(uuid.NAMESPACE_URL,f'{identifier}:{session["trading_date"]}:{symbol}:{action}').hex
            if db.execute('SELECT 1 FROM system_orders WHERE id=?',(client_id,)).fetchone(): continue
            context = broker.quote(symbol)
            quote = context.get('quote')
            if not context['clock'].get('is_open') or not quote: continue
            age = (now-instant(quote['t'])).total_seconds()
            if not all(math.isfinite(float(quote[k])) and float(quote[k])>0 for k in ('bp','ap')): continue
            if not 0<=age<=120 or float(quote['ap'])<float(quote['bp']): continue
            if action=='buy' and (float(quote['ap'])/float(quote['bp'])-1)>.01: continue
            if action=='sell':
                qty = min(own.get(symbol,0),actual.get(symbol,0))
                if qty<=0: continue
                request = {'qty':str(Decimal(str(qty)).quantize(Decimal('0.000000001')))}
            else:
                if not instrument['sector']: continue
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    # Original notional caps include legacy lots plus new reserved/filled buys.
                    legacy = db.execute("SELECT i.symbol,c.sector,l.entry_notional_usd amount FROM paper_trade_lots l JOIN instruments i ON i.id=l.instrument_id LEFT JOIN instrument_context c ON c.instrument_id=i.id WHERE l.status IN ('pending','open','closing')").fetchall()
                    entries = [(r['symbol'],r['sector'],float(r['amount'])) for r in legacy]
                    for s,q in system_positions(db).items():
                        sector = db.execute('SELECT c.sector FROM instrument_context c JOIN instruments i ON i.id=c.instrument_id WHERE i.symbol=?',(s,)).fetchone()
                        avg = db.execute("SELECT filled_price FROM system_orders WHERE symbol=? AND side='buy' AND filled_price IS NOT NULL ORDER BY created_at DESC LIMIT 1",(s,)).fetchone()
                        entries.append((s,sector[0] if sector else None,q*float(avg[0]) if avg else 300))
                    for pending in db.execute("SELECT o.* FROM system_orders o JOIN system_deployments d ON d.id=o.deployment_id JOIN system_versions v ON v.id=d.version_id WHERE v.asset='stocks' AND o.side='buy' AND o.status NOT IN ('filled','canceled','expired','rejected','replaced')"):
                        sector = db.execute('SELECT c.sector FROM instrument_context c JOIN instruments i ON i.id=c.instrument_id WHERE i.symbol=?',(pending['symbol'],)).fetchone()
                        entries.append((pending['symbol'],sector[0] if sector else None,float(json.loads(pending['request_json'])['notional'])))
                    amount = min(15.,300*config.allocation-sum(e[2] for e in entries),30-sum(e[2] for e in entries if e[0]==symbol),60-sum(e[2] for e in entries if e[1]==instrument['sector']),float(context['account']['cash']))
                    if amount<5: continue
                    request={'notional':round(amount,2),'reference_price':float(quote['ap'])}
                    db.execute('INSERT INTO system_orders(id,deployment_id,symbol,side,request_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',(client_id,identifier,symbol,action,canonical(request),at,at))
            if action=='sell':
                with db:
                    db.execute('INSERT INTO system_orders(id,deployment_id,symbol,side,request_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',(client_id,identifier,symbol,action,canonical(request),at,at))
            reconcile(db,identifier,broker,now=now)
            observe(db,identifier,at,'decision',{'symbol':symbol,'action':action,'reason':reason})
            # One outstanding order at a time; reserve capital before subsequent symbols.
            if broker.open_orders(): break
        observe(db,identifier,at,'portfolio',{'account_equity':account.get('equity'),'cash':account.get('cash'),'positions':own,'reconciled':True})
    except Exception as error:
        observe(db,identifier,at,'error',{'message':str(error)[:500]})
