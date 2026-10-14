"""Shared, fixed-host paper transport; no configurable live execution URL."""
import json
from .http import UrllibTransport, require_success

class PaperTransport:
    def request(self,method,path,body=None,*,data=False,missing_ok=False):
        if not path.startswith('/') or path.startswith('//'): raise ValueError('Relative API path required')
        base='https://data.alpaca.markets' if data else 'https://paper-api.alpaca.markets'
        response=self.transport.request(method,base+path,headers=self.headers,
            body=json.dumps(body).encode() if body is not None else None,timeout=10)
        if missing_ok and response.status==404: return None
        if method=='DELETE' and response.status==204: return None
        return require_success('alpaca-paper',response)

    def configure(self,key,secret,transport=None):
        if not key or not secret: raise ValueError('Paper credentials are not configured')
        self.transport=transport or UrllibTransport()
        self.headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret,'Content-Type':'application/json'}
