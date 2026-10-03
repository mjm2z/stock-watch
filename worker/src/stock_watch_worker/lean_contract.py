"""Versioned research-only LEAN interchange; never accepts runnable code or credentials."""
import hashlib
import json
import math
from datetime import datetime, timezone

CONTRACT = 'stockwatch-lean-bitcoin-trend-v1'
MAX_INPUT = 64 * 1024 * 1024

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def utc(value):
    at=datetime.fromisoformat(value.replace('Z','+00:00'))
    if at.tzinfo is None or at.utcoffset().total_seconds()!=0: raise ValueError('Explicit UTC timestamps required')
    return at.astimezone(timezone.utc).isoformat()

def validate(config,data):
    from .systems.engine import SystemConfig, validate_dataset
    if config.get('protocol') or config.get('template','trend')!='trend' or config.get('asset')!='bitcoin':
        raise ValueError('LEAN v1 supports the original Bitcoin trend template only; automated/visual protocols are not supported')
    SystemConfig(**config)
    validate_dataset(data,'bitcoin')
    if data.get('manifest',{}).get('timeframe')!='1Hour': raise ValueError('An explicitly hourly dataset is required')
    if not 1<=len(data['bars'])<=60000:raise ValueError('Use 1–60,000 hourly bars')
    if data.get('corporate_actions'):raise ValueError('Corporate actions are unsupported')
    for row in data['bars']:
        if row.get('exit_quote'):raise ValueError('Separate exit quotes are unsupported in LEAN v1')
        if row.get('eligible') is False:raise ValueError('Eligibility masks are unsupported in LEAN v1')
        for quote in [row.get('quote')]:
            if quote and any(k in quote for k in ('ask_size','bid_size')):raise ValueError('Size-limited partial fills are unsupported in LEAN v1')
    if len(data.get('risk_quotes',[]))>150000:raise ValueError('Minute risk input exceeds the supported bound')
    for name, default in [('slippage_bps',5),('fee_multiplier',1),('quantity_increment',1e-9),('minimum_notional',5)]:
        value=data.get(name,default)
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<=0:raise ValueError('Invalid '+name)
    if .0025*data.get('fee_multiplier',1)>=1:raise ValueError('Fee rate must be below 100%')
    if len(canonical(data).encode())>MAX_INPUT:raise ValueError('LEAN input exceeds 64 MiB')

def compare(baseline,lean,increment):
    """Compare complete ordered evidence, not just end-point performance."""
    differences=[]
    total=0
    def record(kind,index,field,a,b):
        nonlocal total
        total+=1
        if len(differences)<10000:differences.append({'kind':kind,'index':index,'field':field,'stockwatch':a,'lean':b})
    specs={'decisions':{'at':None,'action':None},'fills':{'at':None,'side':None,'qty':increment,'price':.01,'fee':.01},'equity_curve':{'at':None,'equity':.01,'cash':.01}}
    for kind,fields in specs.items():
        left,right=baseline.get(kind,[]),lean.get(kind,[])
        if not isinstance(left,list) or not isinstance(right,list):raise ValueError('Malformed comparison evidence')
        if len(left)!=len(right):record(kind,None,'count',len(left),len(right))
        for i,(a,b) in enumerate(zip(left,right)):
            for field,tolerance in fields.items():
                av,bv=a.get(field),b.get(field)
                if field=='at':av,bv=utc(av),utc(bv)
                if tolerance is None:
                    same=av==bv
                else:
                    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (av,bv)):raise ValueError('Non-finite comparison result')
                    same=abs(av-bv)<=tolerance+1e-12
                if not same:record(kind,i,field,av,bv)
    for field,tolerance in [('ending_equity',.01),('fees',.01),('maximum_drawdown',.0001)]:
        a,b=baseline.get(field),lean.get(field)
        if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (a,b)):raise ValueError('Missing or invalid result metric')
        if abs(a-b)>tolerance+1e-12:record('metrics',None,field,a,b)
    return {'outcome':'differences' if total else 'matched','difference_count':total,'differences':differences,'first_divergence':differences[0] if differences else None,'tolerances':{'quantity':increment,'money':.01,'drawdown':.0001},'contract':CONTRACT}
