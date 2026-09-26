"""Crypto-only Alpaca adapter. The execution host is not configurable."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
import json
import os
from urllib.parse import urlencode, quote

from ..http import UrllibTransport, require_success
from .engine import instant, positive


class CryptoBroker:
    def __init__(self, transport=None, key=None, secret=None):
        self.transport = transport or UrllibTransport()
        key = key or os.environ.get('BITCOIN_ALPACA_API_KEY_ID','')
        secret = secret or os.environ.get('BITCOIN_ALPACA_API_SECRET_KEY','')
        if not key or not secret:
            raise ValueError('Separate Bitcoin paper credentials are not configured')
        if key == os.environ.get('ALPACA_API_KEY_ID'):
            raise ValueError('Bitcoin must use a separate paper account')
        self.headers = {'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret,'Content-Type':'application/json'}

    def request(self, method, path, body=None, *, data=False, missing_ok=False):
        base = 'https://data.alpaca.markets' if data else 'https://paper-api.alpaca.markets'
        response = self.transport.request(method, base+path, headers=self.headers,
                                          body=json.dumps(body).encode() if body is not None else None, timeout=10)
        if missing_ok and response.status == 404:
            return None
        if method == 'DELETE' and response.status == 204:
            return None
        return require_success('alpaca-crypto-paper',response)

    def account(self):
        account = self.request('GET','/v2/account')
        if account.get('currency') != 'USD' or account.get('status') != 'ACTIVE' or any(account.get(k) for k in ('trading_blocked','account_blocked','trade_suspended_by_user')):
            raise ValueError('Bitcoin paper account is not ready')
        return account

    def positions(self):
        return self.request('GET','/v2/positions')

    def metadata(self):
        asset = self.request('GET','/v2/assets/BTC%2FUSD')
        if asset.get('class') != 'crypto' or not asset.get('tradable'):
            raise ValueError('BTC/USD is unavailable in this account')
        for key in ('min_order_size','min_trade_increment'):
            positive(asset[key],key)
        return asset

    def quote(self, now):
        result = self.request('GET','/v1beta3/crypto/us/latest/quotes?symbols=BTC%2FUSD',data=True)['quotes']['BTC/USD']
        age = (now-instant(result['t'])).total_seconds()
        if not 0 <= age <= 90 or positive(result['ap'],'ask') < positive(result['bp'],'bid'):
            raise ValueError('Bitcoin quote is stale or crossed; new entries blocked')
        return result

    def bars(self, now, hours=300):
        end = now.replace(minute=0,second=0,microsecond=0)
        params = {'symbols':'BTC/USD','timeframe':'1Hour','start':(end-timedelta(hours=hours)).isoformat(),
                  'end':end.isoformat(),'limit':10000,'sort':'asc'}
        result = self.request('GET','/v1beta3/crypto/us/bars?'+urlencode(params),data=True)
        rows = []
        for row in result.get('bars',{}).get('BTC/USD',[]):
            close_at = instant(row['t'])+timedelta(hours=1)
            if close_at > end:
                continue
            rows.append({'symbol':'BTC/USD','at':close_at.isoformat(),'available_at':close_at.isoformat(),
                         'open':row['o'],'high':row['h'],'low':row['l'],'close':row['c'],'volume':row['v']})
        if not rows or instant(rows[-1]['at']) != end:
            raise ValueError('Latest completed hourly bar is unavailable')
        for before,after in zip(rows,rows[1:]):
            if (instant(after['at'])-instant(before['at'])).total_seconds() != 3600:
                raise ValueError('Hourly market data contains a gap')
        return rows

    def lookup(self, client_id):
        return self.request('GET','/v2/orders:by_client_order_id?'+urlencode({'client_order_id':client_id}),missing_ok=True)

    def open_orders(self):
        return self.request('GET','/v2/orders?status=open&limit=500')

    def fees(self, after):
        results, token = [], None
        for _ in range(100):
            params = {'activity_types':'CFEE,FEE','after':after,'direction':'asc','page_size':100}
            if token:
                params['page_token'] = token
            page = self.request('GET','/v2/account/activities?'+urlencode(params))
            results.extend(page)
            if len(page) < 100:
                return results
            token = page[-1]['id']
        raise ValueError('Fee history exceeds pagination limit')

    def submit(self, client_id, side, quantity):
        if side not in ('buy','sell') or Decimal(quantity) <= 0:
            raise ValueError('Invalid order')
        return self.request('POST','/v2/orders',{'symbol':'BTC/USD','side':side,'type':'market',
                    'time_in_force':'gtc','qty':quantity,'client_order_id':client_id})

    def fills(self, after):
        results, token = [], None
        for _ in range(100):
            params = {'after':after,'direction':'asc','page_size':100}
            if token: params['page_token'] = token
            page = self.request('GET','/v2/account/activities/FILL?'+urlencode(params))
            results.extend(page)
            if len(page) < 100: return results
            token = page[-1]['id']
        raise ValueError('Fill activity history exceeds pagination limit')

    def cancel(self, identifier):
        return self.request('DELETE','/v2/orders/'+quote(identifier,safe=''))


def rounded_quantity(amount, increment):
    step = Decimal(str(increment))
    if not step.is_finite() or step <= 0:
        raise ValueError('Invalid quantity increment')
    return str((Decimal(str(amount))/step).to_integral_value(rounding=ROUND_DOWN)*step)
