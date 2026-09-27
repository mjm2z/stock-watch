#!/usr/bin/env python3
"""Read-only entitlement probe. Run with protected service environment; no keys printed."""
from datetime import datetime, timedelta, timezone
import json
import os
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

end=(datetime.now(timezone.utc)-timedelta(days=2)).replace(hour=0,minute=0,second=0,microsecond=0)
headers={'APCA-API-KEY-ID':os.environ.get('ALPACA_API_KEY_ID',''),
         'APCA-API-SECRET-KEY':os.environ.get('ALPACA_API_SECRET_KEY','')}
report={'checked_at':datetime.now(timezone.utc).isoformat(),'results':[]}
for feed in ('iex','sip'):
    params=urlencode({'symbols':'AAPL','timeframe':'1Day','feed':feed,'adjustment':'raw',
                      'start':(end-timedelta(days=7)).isoformat(),'end':end.isoformat(),'limit':10})
    result={'provider':'alpaca','feed':feed,'end':end.isoformat(),'mode':'historical only'}
    try:
        with urlopen(Request('https://data.alpaca.markets/v2/stocks/bars?'+params,headers=headers),timeout=15) as response:
            payload=json.load(response)
        rows=payload.get('bars',{}).get('AAPL',[])
        result.update(accessible=True,bars=len(rows),last_session=rows[-1]['t'] if rows else None,
                      last_volume=rows[-1]['v'] if rows else None)
    except HTTPError as error:result.update(accessible=False,http_status=error.code)
    except Exception as error:result.update(accessible=False,error_type=type(error).__name__)
    report['results'].append(result)
print(json.dumps(report,indent=2))
