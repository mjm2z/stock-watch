"""Versioned, bounded visual rules. The same pure evaluator serves every engine."""
from dataclasses import dataclass, field, asdict
import math
from statistics import mean
from .engine import digest

OPERANDS={'close','open','high','low','volume','sma','ema','rsi','average_volume','prior_high','prior_low','number'}
OPS={'gt','gte','lt','lte','crosses_above','crosses_below'}

def validate_operand(value):
    if not isinstance(value,dict) or value.get('kind') not in OPERANDS: raise ValueError('Unsupported indicator')
    if value['kind']=='number':
        number=value.get('value')
        if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number): raise ValueError('Finite threshold required')
    elif value['kind'] in {'sma','ema','rsi','average_volume','prior_high','prior_low'}:
        period=value.get('period')
        if isinstance(period,bool) or not isinstance(period,int) or not 2<=period<=250: raise ValueError('Indicator periods must be 2–250')

def validate_group(group,depth=0):
    if not isinstance(group,dict) or group.get('op') not in ('all','any') or depth>1: raise ValueError('Use ALL/ANY groups up to two levels')
    children=group.get('conditions')
    if not isinstance(children,list) or not 1<=len(children)<=8: raise ValueError('Each group needs 1–8 conditions')
    count=0
    for row in children:
        if not isinstance(row,dict): raise ValueError('Condition must be an object')
        if row.get('op') in ('all','any'): count+=validate_group(row,depth+1)
        else:
            if row.get('op') not in OPS: raise ValueError('Unsupported comparison')
            validate_operand(row.get('left'));validate_operand(row.get('right'));count+=1
    if count>8: raise ValueError('At most eight conditions per entry or exit')
    return count

@dataclass(frozen=True)
class RuleConfig:
    asset: str
    entry_rules: dict
    exit_rules: dict
    template: str='visual'
    protocol: str='visual-rules-v1'
    timeframe: str='1Day'
    allocation: float=.1
    holding_count: int=1
    holding_unit: str='days'
    stop_loss: float=.05
    take_profit: float=.1
    # Existing engines use these only to reserve sufficient warmup history.
    fast: int=20
    slow: int=250
    entry: int=250
    exit: int=20
    def __post_init__(self):
        from .timeframes import TIMEFRAMES,deadline,months
        from datetime import datetime,timezone
        if self.protocol!='visual-rules-v1' or self.template!='visual' or self.asset not in ('stocks','bitcoin'): raise ValueError('Unsupported visual system')
        if self.timeframe not in TIMEFRAMES or (self.asset=='stocks' and self.timeframe!='1Day'): raise ValueError('Stocks currently use daily decisions')
        validate_group(self.entry_rules);validate_group(self.exit_rules)
        for n in ('allocation','stop_loss','take_profit'):
            v=getattr(self,n)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<=1: raise ValueError('Sizing and risk values must be between zero and one')
        if self.allocation>(.5 if self.asset=='bitcoin' else 1):raise ValueError('Crypto exposure cannot exceed 50% of its allocation')
        if isinstance(self.holding_count,bool) or not isinstance(self.holding_count,int) or self.holding_count<1:raise ValueError('Positive holding period required')
        anchor=datetime(2023,1,1,tzinfo=timezone.utc)
        if deadline(anchor,self.holding_count,self.holding_unit)>months(anchor,12):raise ValueError('Maximum holding period is twelve months')
        if (self.fast,self.slow,self.entry,self.exit)!=(20,250,250,20):raise ValueError('Visual warmup parameters are fixed')
    @property
    def sha256(self):return digest({'engine':self.protocol,**asdict(self)})

def operand(spec,history):
    kind=spec['kind']
    if kind=='number':return float(spec['value'])
    if not history:return None
    if kind in ('open','high','low','close','volume'):
        value=history[-1].get(kind)
        return float(value) if value is not None and math.isfinite(float(value)) else None
    n=spec['period'];field='volume' if kind=='average_volume' else 'close'
    rows=history[:-1] if kind in ('prior_high','prior_low') else history
    if len(rows)<n:return None
    if kind=='prior_high':return max(float(r['high']) for r in rows[-n:])
    if kind=='prior_low':return min(float(r['low']) for r in rows[-n:])
    if any(r.get(field) is None for r in rows):return None
    values=[float(r[field]) for r in rows]
    if kind in ('sma','average_volume'):return mean(values[-n:])
    if kind=='ema':
        result=mean(values[:n]);alpha=2/(n+1)
        for v in values[n:]:result=alpha*v+(1-alpha)*result
        return result
    if len(values)<n+1:return None
    changes=[b-a for a,b in zip(values,values[1:])]
    gain=mean(max(v,0) for v in changes[:n]);loss=mean(max(-v,0) for v in changes[:n])
    for v in changes[n:]:gain=(gain*(n-1)+max(v,0))/n;loss=(loss*(n-1)+max(-v,0))/n
    return 50. if gain==loss==0 else 100. if loss==0 else 100-100/(1+gain/loss)

def evaluate_group(group,history):
    values=[]
    for row in group['conditions']:
        if row['op'] in ('all','any'):value=evaluate_group(row,history)
        else:
            a,b=operand(row['left'],history),operand(row['right'],history)
            if a is None or b is None:return None
            op=row['op']
            if op.startswith('crosses_'):
                pa,pb=operand(row['left'],history[:-1]),operand(row['right'],history[:-1])
                if pa is None or pb is None:return None
                value=a>b and pa<=pb if op=='crosses_above' else a<b and pa>=pb
            else:value={'gt':a>b,'gte':a>=b,'lt':a<b,'lte':a<=b}[op]
        if value is None:return None
        values.append(value)
    return all(values) if group['op']=='all' else any(values)

def decide(config,history,held):
    # Fixed history length makes recursive indicators identical in every adapter.
    value=evaluate_group(config.exit_rules if held else config.entry_rules,history[-251:])
    if value is None:return 'hold','Waiting for complete indicator history'
    return ('sell' if held else 'buy','Visual rules matched') if value else ('hold','Visual rules not matched')

def risk_exit(config,price,entry_price):
    if getattr(config,'protocol',None)!='visual-rules-v1' or not entry_price:return None
    change=float(price)/float(entry_price)-1
    if change<=-config.stop_loss:return 'System stop loss'
    if change>=config.take_profit:return 'System take profit'
    return None


def position_exit(config,price,entry_price,entered_at,at):
    if getattr(config,'protocol',None)!='visual-rules-v1':return None
    reason=risk_exit(config,price,entry_price)
    if reason:return reason
    if entered_at:
        from .engine import instant
        from .timeframes import deadline
        if instant(at)>=deadline(instant(entered_at),config.holding_count,config.holding_unit):return 'Maximum holding period'
    return None
