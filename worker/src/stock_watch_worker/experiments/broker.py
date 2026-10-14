"""Explicit asset policies on shared paper-only transport."""
import os
from urllib.parse import urlencode, quote
from ..paper_transport import PaperTransport
from .model import money, instant

class Broker(PaperTransport):
    def __init__(self,asset,transport=None):
        if asset not in ('stocks','bitcoin'): raise ValueError('Unsupported account')
        self.asset=asset
        prefix='BITCOIN_' if asset=='bitcoin' else ''
        key=os.environ.get(prefix+'ALPACA_API_KEY_ID'); secret=os.environ.get(prefix+'ALPACA_API_SECRET_KEY')
        if key and asset=='bitcoin' and key==os.environ.get('ALPACA_API_KEY_ID'):
            raise ValueError('Automated stock and Bitcoin accounts must be separate')
        if key and key==os.environ.get('MANUAL_ALPACA_API_KEY_ID'):
            raise ValueError('Manual account must remain separate')
        self.configure(key,secret,transport)

    def account(self):
        account=self.request('GET','/v2/account')
        if account.get('currency')!='USD' or account.get('status')!='ACTIVE' or any(account.get(k) for k in ('trading_blocked','account_blocked','trade_suspended_by_user')):
            raise ValueError('Paper account is not available for trading')
        return account

    def metadata(self,symbol):
        value=self.request('GET','/v2/assets/'+quote(symbol,safe=''))
        if not value.get('tradable') or value.get('status')!='active': raise ValueError(symbol+' is not tradable')
        if self.asset=='stocks' and (value.get('class')!='us_equity' or not value.get('fractionable')):
            raise ValueError(symbol+' is not fractionable equity')
        if self.asset=='bitcoin' and value.get('class')!='crypto': raise ValueError('Crypto metadata required')
        return {'symbol':symbol,'quantity_increment':str(value.get('min_trade_increment','0.000000001')),
            'minimum_quantity':str(value.get('min_order_size','0.000000001')),
            'price_increment':str(value.get('price_increment','0.01'))}

    def preflight(self,symbols):
        account=self.account()
        other='bitcoin' if self.asset=='stocks' else 'stocks'
        other_prefix='BITCOIN_' if other=='bitcoin' else ''
        if os.environ.get(other_prefix+'ALPACA_API_KEY_ID') and Broker(other,self.transport).account()['id']==account['id']:
            raise ValueError('Automated accounts must have different broker identities')
        if os.environ.get('MANUAL_ALPACA_API_KEY_ID'):
            manual=PaperTransport(); manual.configure(os.environ.get('MANUAL_ALPACA_API_KEY_ID'),os.environ.get('MANUAL_ALPACA_API_SECRET_KEY'),self.transport)
            if manual.request('GET','/v2/account')['id']==account['id']: raise ValueError('Manual broker identity must be separate')
        metadata={symbol:self.metadata(symbol) for symbol in symbols}
        for value in metadata.values():
            if any(money(value[k])<=0 for k in ('quantity_increment','minimum_quantity','price_increment')):
                raise ValueError('Invalid broker precision metadata')
        return {'account_id':account['id'],'asset':self.asset,'feed':'iex' if self.asset=='stocks' else 'alpaca-us',
            'metadata':metadata,'paper_host':'paper-api.alpaca.markets'}

    def lookup(self,identifier):
        return self.request('GET','/v2/orders:by_client_order_id?'+urlencode({'client_order_id':identifier}),missing_ok=True)
    def submit(self,request):
        if request.get('side') not in ('buy','sell') or request.get('type') not in ('limit','market') or money(request.get('qty',0))<=0:
            raise ValueError('Invalid paper order')
        if request['side']=='buy' and request['type']!='limit': raise ValueError('Experimental entries require limits')
        return self.request('POST','/v2/orders',request)
    def execution_check(self,request,account_id):
        from datetime import datetime, timezone
        account=self.account()
        if account['id']!=account_id: raise ValueError('Account identity changed before submission')
        if self.asset=='stocks':
            clock=self.request('GET','/v2/clock')
            if not clock.get('is_open'): raise ValueError('Regular session is closed')
        if any(str(o['symbol']).replace('/','')==request['symbol'].replace('/','') and o.get('client_order_id')!=request['client_order_id'] for o in self.open_orders()):
            raise ValueError('Another broker order owns this symbol')
        if request['type']=='limit':
            quote_data=self.execution_quote(request['symbol'])
            now=datetime.now(timezone.utc)
            if not 0<=(now-instant(quote_data['t'])).total_seconds()<=5: raise ValueError('Execution quote is stale')
            bid,ask=money(quote_data['bp']),money(quote_data['ap'])
            if bid<=0 or ask<bid: raise ValueError('Execution quote is invalid')
            price=money(request['limit_price'])
            if request['side']=='buy' and not ask<=price<=ask*money('1.005'): raise ValueError('Entry limit is no longer within allowance')
        if request['side']=='sell':
            owned=sum((money(p['qty']) for p in self.positions() if str(p['symbol']).replace('/','')==request['symbol'].replace('/','')),money(0))
            if owned<money(request['qty']): raise ValueError('Broker holdings cannot cover this exit')
        return datetime.now(timezone.utc),account
    def execution_quote(self,symbol):
        from datetime import datetime, timezone
        path=('/v2/stocks/quotes/latest?'+urlencode({'symbols':symbol,'feed':'iex'})) if self.asset=='stocks' else ('/v1beta3/crypto/us/latest/quotes?'+urlencode({'symbols':symbol}))
        q=self.request('GET',path,data=True)['quotes'][symbol]
        if not 0<=(datetime.now(timezone.utc)-instant(q['t'])).total_seconds()<=5 or money(q['bp'])<=0 or money(q['ap'])<money(q['bp']):
            raise ValueError('Fresh executable quote unavailable')
        return q
    def cancel(self,identifier):
        return self.request('DELETE','/v2/orders/'+quote(identifier,safe=''))
    def positions(self): return self.request('GET','/v2/positions')
    def open_orders(self): return self.request('GET','/v2/orders?status=open&limit=500')
    def calendar(self,start,end,date_type='TRADING'):
        if date_type not in ('TRADING','SETTLEMENT'): raise ValueError('Unsupported calendar')
        return self.request('GET','/v2/calendar?'+urlencode({'start':start,'end':end,'date_type':date_type}))
    def activities(self,after):
        rows=[]; token=None
        for _ in range(20):
            query={'after':after,'direction':'asc','page_size':100,'activity_types':'FILL,CFEE,FEE'}
            if token: query['page_token']=token
            page=self.request('GET','/v2/account/activities?'+urlencode(query))
            rows.extend(page)
            if len(page)<100: return rows
            token=page[-1]['id']
        raise ValueError('Activity pagination incomplete; reconciliation blocked')
