"""Frozen experiment protocol and pure decisions shared by replay and execution."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from zoneinfo import ZoneInfo
from ..systems.rules import evaluate_group, operand

NY = ZoneInfo('America/New_York')
UNIVERSE = ('SPY','QQQ','IWM','XLF','XLK','XLE','AAPL','MSFT','NVDA','AMZN','GOOGL','META','JPM','XOM')
FAMILIES = ('trend','breakout','reversal','news_breakout','control')
TERMINAL = ('filled','canceled','expired','rejected')

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def instant(value):
    result = datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if result.tzinfo is None:
        raise ValueError('An aware timestamp is required')
    return result.astimezone(timezone.utc)

def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')

def money(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError('A finite decimal is required') from error
    if not result.is_finite():
        raise ValueError('A finite decimal is required')
    return result

def config(asset, family, variant=0):
    if asset not in ('stocks','bitcoin') or family not in FAMILIES or variant not in (0,1,2):
        raise ValueError('Unsupported experiment')
    return dict(protocol='intraday-experiment-v1', asset=asset, family=family,
        timeframe='5Min', feed='iex' if asset=='stocks' else 'alpaca-us',
        universe=list(UNIVERSE) if asset=='stocks' else ['BTC/USD'], warmup=251,
        decision_delay=35, max_entry='10' if family=='control' else '50',
        allocation='50' if family=='control' else '200', entries_per_day=4,
        max_positions=2 if asset=='stocks' else 1, cooldown_minutes=30,
        holding_minutes=15 if family=='control' else 120 if asset=='stocks' else 240,
        stop='0.01' if asset=='stocks' else '0.02', take='0.02' if asset=='stocks' else '0.04',
        allowance='0.005', limit_seconds=60, control_time='10:05', control_window_minutes=5,
        trend_fast=(15 if variant==1 else 25 if variant==2 else 20) if family=='trend' else 20,
        breakout_period=(15 if variant==1 else 25 if variant==2 else 20) if 'breakout' in family else 20,
        rsi_entry=(30 if variant==1 else 40 if variant==2 else 35) if family=='reversal' else 35,
        settlement='broker-calendar' if asset=='stocks' else 'immediate', variant=variant)

def indicator(kind, period=None):
    return {'kind':kind, **({'period':period} if period else {})}

def comparison(left, op, right):
    return {'left':left,'op':op,'right':right}

def signal(cfg, bars, held, fresh_news=False):
    if len(bars)<251:
        return 'hold','collecting',{}
    bars=bars[-251:]
    close=indicator('close'); ema20=indicator('ema',cfg['trend_fast']); ema50=indicator('ema',50)
    rsi=indicator('rsi',14); number=lambda x: {'kind':'number','value':x}
    family=cfg['family']
    if family=='trend':
        rules=[comparison(close,'lt',ema20)] if held else [comparison(ema20,'gt',ema50),comparison(close,'gt',ema20)]
        op='all'
    elif family in ('breakout','news_breakout'):
        rules=[comparison(close,'lt',indicator('prior_low',10))] if held else [comparison(close,'gt',indicator('prior_high',cfg['breakout_period']))]
        op='all'
    elif family=='reversal':
        rules=[comparison(rsi,'gte',number(55)),comparison(close,'lt',ema50)] if held else [comparison(rsi,'crosses_above',number(cfg['rsi_entry'])),comparison(close,'gt',ema50)]
        op='any' if held else 'all'
    else:
        return 'hold','scheduled_control',{}
    values=[{'left':operand(r['left'],bars),'op':r['op'],'right':operand(r['right'],bars)} for r in rules]
    matched=evaluate_group({'op':op,'conditions':rules},bars)
    evidence={'conditions':values,'operator':op,'fresh_news':fresh_news}
    if matched and family=='news_breakout' and not held and not fresh_news:
        return 'hold','waiting_news',evidence
    return ('sell' if held else 'buy','signal',evidence) if matched else ('hold','waiting_signal',evidence)

def boundary(now):
    return datetime.fromtimestamp(int(now.timestamp())//300*300,timezone.utc)

def entry_session(asset, now, session):
    return asset=='bitcoin' or bool(session and instant(session['opens'])+timedelta(minutes=15)<=now<instant(session['closes'])-timedelta(minutes=30))

def trade_session(asset, now, session):
    return asset=='bitcoin' or bool(session and instant(session['opens'])<=now<instant(session['closes']))

def exit_deadline(cfg, entered, session):
    deadline=entered+timedelta(minutes=cfg['holding_minutes'])
    if cfg['asset']=='stocks':
        if not session: raise ValueError('Stock calendar unavailable')
        deadline=min(deadline,instant(session['closes'])-timedelta(minutes=15))
    return deadline

def exit_reason(cfg, position, bid, now, expired=False, requested=False):
    if money(position['quantity'])<=0: return None
    if requested: return 'operator_exit'
    if expired: return 'batch_expired'
    if position['exit_due'] and now>=instant(position['exit_due']): return 'holding_deadline'
    entry=money(position['cost'])/money(position['quantity'])
    if bid is not None and entry>0:
        change=money(bid)/entry-1
        if change<=-money(cfg['stop']): return 'stop_loss'
        if change>=money(cfg['take']): return 'take_profit'
    return None
