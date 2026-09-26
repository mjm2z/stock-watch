"""Bounded-memory, chronological Bitcoin scenario replay using observed quotes.

Backfilled OHLC is exploratory. Only timely, observed bars and executable quote
coverage can qualify; no inferred quote is labelled execution evidence.
"""
from collections import deque
from datetime import timedelta
import hashlib
import heapq
import math
from .engine import canonical, decision, instant
from .history import bar_revisions, quotes
from .timeframes import advance, deadline
from .broker import rounded_quantity

PROFILES = ('base', 'double_fees', 'double_execution', 'delayed_partial', 'combined')
REPLAY_VERSION = 'observed-replay-v2.1'


def source_key(db, config, start, end, cutoff, profile,initial_cash=300.,metadata=None):
    h=hashlib.sha256(canonical([REPLAY_VERSION,config.sha256,start,end,profile,initial_cash,metadata]).encode())
    warm=advance(instant(start),config.timeframe,-max(config.slow,config.entry)-2).isoformat()
    for row in bar_revisions(db,config.timeframe,warm,end,cutoff): h.update(canonical(row).encode())
    for row in quotes(db,start,end,cutoff): h.update(canonical(row).encode())
    return h.hexdigest()


def replay(db, config, start, end, cutoff, profile, trade_sink=None,initial_cash=300.,metadata=None):
    if profile not in PROFILES: raise ValueError('Unknown cost profile')
    begin,finish=instant(start),instant(end)
    warm=advance(begin,config.timeframe,-max(config.slow,config.entry)-2)
    fee=.005 if profile in ('double_fees','combined') else .0025
    slip=.001 if profile in ('double_execution','combined') else .0005
    delayed=profile in ('delayed_partial','combined')
    history=deque(maxlen=252)
    cash,qty,peak,dd,costs,turnover=initial_cash,0.,initial_cash,0.,0.,0.
    pending=None; entered=None; entry_cost=0.; entry_id=None; previous=None
    last_quote=None; last_quote_at=None; coverage_gap=False; approximate=False
    trades=[]; bars_count=0; risk=False; exposure_seconds=0.; last_event=begin
    closed_pnl=0.; trade_count=0; win_count=0
    def bar_events():
        for b in bar_revisions(db,config.timeframe,warm.isoformat(),end,cutoff):
            at=instant(b['at'])
            # Historical rows can support exploratory metrics, never qualification.
            known=at if b.get('historical_approximation') else instant(b['available_at'])
            if known < at: raise ValueError('Bar available before close')
            # Late observations cannot retrospectively introduce old signals.
            yield (max(at,known),1,b)
    def quote_events():
        for q in quotes(db,start,end,cutoff):
            yield (max(instant(q['at']),instant(q['observed_at'])),0,q)
    # Bar timestamps and collection timestamps are monotonic for this collector.
    for at,kind,row in heapq.merge(bar_events(),quote_events(),key=lambda e:e[0]):
        if at>=finish: continue
        if at>=begin:
            if qty: exposure_seconds+=max(0,(at-last_event).total_seconds())
            last_event=at
        if kind==1:
            bar_at=instant(row['at'])
            if previous is not None and bar_at<=previous:
                revised=False
                for index,old in enumerate(history):
                    if old['at']==row['at']:
                        history[index]=row; revised=True; break
                if not revised: coverage_gap=True
                # A correction updates subsequent indicators; it is not a new
                # decision bar and must not generate a second entry decision.
                continue
            if previous is not None and advance(previous,config.timeframe)!=bar_at:
                history.clear(); coverage_gap=True; pending=None
            previous=bar_at; history.append(row)
            approximate |= bool(row.get('historical_approximation'))
            if (at-bar_at).total_seconds()>90: approximate=True
            if at<begin: continue
            if len(history)<max(config.slow,config.entry)+1: coverage_gap=True
            bars_count+=1
            if not pending:
                action,_=decision(config,list(history),qty>=float(metadata['min_order_size']) if metadata else qty>0)
                if action!='hold' and not (action=='buy' and risk):
                    pending={'side':action,'at':at+timedelta(seconds=30 if delayed else 0),
                             'id':bar_at.isoformat(),'remaining':None}
            continue
        bid,ask=float(row['bid']),float(row['ask'])
        if not math.isfinite(bid+ask) or not 0<bid<=ask: coverage_gap=True; continue
        if profile in ('double_execution','combined'):
            mid=(bid+ask)/2; half=ask-mid
            bid,ask=mid-2*half,mid+2*half
        if (at-instant(row['at'])).total_seconds()>90: coverage_gap=True; continue
        if last_quote_at is None:
            if (at-begin).total_seconds()>30: coverage_gap=True
        elif (at-last_quote_at).total_seconds()>30: coverage_gap=True
        last_quote_at=at; last_quote=bid
        equity=cash+qty*bid*(1-fee)*(1-slip)
        peak=max(peak,equity); dd=max(dd,1-equity/peak)
        if dd>=.1: risk=True
        if qty and entered and (risk or at>=deadline(entered,config.holding_count,config.holding_unit)):
            if not pending or pending['side']!='sell': pending={'side':'sell','at':at,'id':entry_id,'remaining':None}
        if not pending or at<=pending['at']: continue
        if pending['side']=='buy' and (at-pending['at']).total_seconds()>90:
            pending=None; continue
        side=pending['side']; price=ask*(1+slip) if side=='buy' else bid*(1-slip)
        if pending['remaining'] is None:
            pending['remaining']=(min(cash,equity*config.allocation)/price if side=='buy' else qty)
            if metadata:
                pending['remaining']=float(rounded_quantity(pending['remaining'],metadata['min_trade_increment']))
                if pending['remaining']<float(metadata['min_order_size']):
                    pending=None; continue
        size=row['ask_size'] if side=='buy' else row['bid_size']
        if size is None or not math.isfinite(float(size)) or float(size)<=0:
            approximate=True; continue
        fill=min(pending['remaining'],float(size))
        if delayed and not pending.get('first_partial'):
            fill*=.5; pending['first_partial']=True
        if side=='buy':
            fill=min(fill,cash/price); cash-=fill*price; qty+=fill*(1-fee)
            entry_cost+=fill*price
            if entered is None: entered=at; entry_id=pending['id']
        else:
            fill=min(fill,qty); cash+=fill*price*(1-fee); qty-=fill
        costs+=fill*price*fee+fill*abs(price-(ask+bid)/2); turnover+=fill*price
        pending['remaining']-=fill
        if pending['remaining']<1e-10:
            pending=None
            if side=='sell':
                pnl=cash+qty*bid*(1-fee)*(1-slip)-initial_cash-closed_pnl; closed_pnl+=pnl
                trade={'id':entry_id,'entered_at':entered.isoformat(),'exit':at.isoformat(),'pnl':pnl,'cost_basis':entry_cost}
                if trade_sink: trade_sink(trade)
                else: trades.append(trade)
                trade_count+=1; win_count+=int(pnl>0)
                if qty<1e-10: qty=0.
                entered=None
                entry_cost=0.
    if last_quote_at is None or (finish-last_quote_at).total_seconds()>30: coverage_gap=True
    if previous!=advance(finish,config.timeframe,-1): coverage_gap=True
    final=cash+qty*(last_quote or 0)*(1-fee)*(1-slip)
    peak=max(peak,final); dd=max(dd,1-final/peak)
    wins=win_count; n=trade_count
    return {'valid':not approximate and not coverage_gap and bars_count>=12 and metadata is not None,
            'net_return':final/initial_cash-1,'drawdown':dd,'trades':trades,'trade_count':trade_count,'trade_win_rate':wins/n if n else None,
            'costs':costs,'turnover':turnover/initial_cash,'exposure':exposure_seconds/(finish-begin).total_seconds(),
            'bars':bars_count,'open_quantity':qty,'approximate':approximate,'coverage_gap':coverage_gap,
            'limitations':['Historical bars or late observations are exploratory'] if approximate else [],
            'unrealized_included':True,'initial_cash':initial_cash,'execution_metadata':metadata}
