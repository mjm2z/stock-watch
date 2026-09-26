"""Pure rules and cash-constrained replay. No broker or network dependencies.

Dataset timestamps are UTC instants. Each row describes a completed bar and a
subsequent executable quote. Approximate daily data is explicitly exploratory.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import mean

ENGINE_VERSION = 'cash-replay-v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def instant(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('UTC timestamps with an explicit offset are required')
    return result


def positive(value, name):
    if isinstance(value, bool):
        raise ValueError(f'{name} must be positive')
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f'{name} must be finite and positive')
    return result


@dataclass(frozen=True)
class SystemConfig:
    asset: str
    template: str = 'trend'
    fast: int = 20
    slow: int = 100
    entry: int = 55
    exit: int = 20
    allocation: float = .5

    def __post_init__(self):
        if self.asset not in ('stocks', 'bitcoin') or self.template not in ('trend', 'breakout'):
            raise ValueError('Unsupported asset or template')
        for value in (self.fast, self.slow, self.entry, self.exit):
            if isinstance(value, bool) or not isinstance(value, int) or not 5 <= value <= 250:
                raise ValueError('Lookbacks must be integers between 5 and 250')
        if self.fast >= self.slow or self.exit >= self.entry:
            raise ValueError('Fast/exit lookback must be shorter than slow/entry')
        if not math.isfinite(self.allocation) or not .05 <= self.allocation <= 1:
            raise ValueError('Allocation must be between 5% and 100%')

    @property
    def sha256(self):
        return digest({'engine': ENGINE_VERSION, **asdict(self)})


def decision(config, history, held):
    """Completed bars only; breakout thresholds exclude the deciding bar."""
    if getattr(config, 'protocol', None) == 'visual-rules-v1':
        from .rules import decide
        return decide(config, history, held)
    need = config.slow + 1 if config.template == 'trend' else config.entry + 1
    if len(history) < need:
        return 'hold', 'Warming up indicators'
    closes = [float(row['close']) for row in history]
    if config.template == 'trend':
        fast, slow = mean(closes[-config.fast:]), mean(closes[-config.slow:])
        previous_fast = mean(closes[-config.fast-1:-1])
        previous_slow = mean(closes[-config.slow-1:-1])
        buy = fast > slow and previous_fast <= previous_slow
        sell = fast < slow and previous_fast >= previous_slow
        reason = f'SMA({config.fast})={fast:.6g}; SMA({config.slow})={slow:.6g}'
    else:
        high = max(float(row['high']) for row in history[-config.entry-1:-1])
        low = min(float(row['low']) for row in history[-config.exit-1:-1])
        buy, sell = closes[-1] > high, closes[-1] < low
        reason = f'Close={closes[-1]:.6g}; prior high={high:.6g}; prior low={low:.6g}'
    return ('sell' if held and sell else 'buy' if not held and buy else 'hold'), reason


def validate_dataset(data, asset):
    if data.get('schema_version') != 1 or data.get('asset') != asset:
        raise ValueError('Dataset schema or asset mismatch')
    manifest = data.get('manifest', {})
    if not manifest.get('provider') or not manifest.get('venue'):
        raise ValueError('Provider and venue provenance required')
    rows = data.get('bars', [])
    if not rows:
        raise ValueError('Dataset has no bars')
    seen, previous = set(), None
    for row in rows:
        at = instant(row['at'])
        key = (row['symbol'], at)
        if key in seen or (previous is not None and at < previous):
            raise ValueError('Bars must be chronological without duplicate symbol timestamps')
        seen.add(key)
        previous = at
        if asset == 'bitcoin' and row['symbol'] != 'BTC/USD':
            raise ValueError('Only BTC/USD is supported')
        if instant(row['available_at']) > at:
            raise ValueError('Bar was unavailable at the decision timestamp')
        for field in ('open', 'high', 'low', 'close'):
            positive(row[field], field)
        if not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
            raise ValueError('Invalid OHLC range')
        for field in ('quote','exit_quote'):
            if not row.get(field):
                continue
            quote = row[field]
            if instant(quote['at']) <= at:
                raise ValueError('Execution must be strictly after the signal')
            if positive(quote['ask'], 'ask') < positive(quote['bid'], 'bid'):
                raise ValueError('Crossed quote')
        if asset == 'stocks' and not row.get('sector'):
            raise ValueError('Stock sector is required to enforce exposure limits')
    return rows


def replay(config, data, *, cost_multiplier=1, start=None, end=None, canceled=lambda: False,
           starting_cash=300., fee_multiplier=None, execution_multiplier=None):
    """Signals create pending intents; only subsequent quote events can fill them.

    Missing marks are flagged; they are never filled with a fabricated new price.
    Quotes are executable approximations, not a liquidity/partial-fill simulator.
    """
    rows = validate_dataset(data, config.asset)
    starting_cash=positive(starting_cash,'starting_cash')
    cash, peak, drawdown = starting_cash, starting_cash, 0.
    holdings, history, marks, sectors, pending = {}, {}, {}, {}, {}
    events, fills, curve, warnings = [], [], [], set()
    planned, receivables = {}, {}
    cost_multiplier=positive(cost_multiplier,'cost_multiplier')
    if fee_multiplier is not None:fee_multiplier=positive(fee_multiplier,'fee_multiplier')
    if execution_multiplier is not None:execution_multiplier=positive(execution_multiplier,'execution_multiplier')
    fee_rate = positive(data.get('fee_multiplier',1),'dataset fee multiplier') * (.0025 if config.asset == 'bitcoin' else 0.) * (fee_multiplier if fee_multiplier is not None else cost_multiplier)
    slip = positive(data.get('slippage_bps', 5), 'slippage_bps') / 10000 * (execution_multiplier if execution_multiplier is not None else cost_multiplier)
    if data['manifest'].get('fidelity') != 'intraday':
        warnings.add('Coarse execution data: exploratory only')
    risk_quotes = data.get('risk_quotes', []) if config.asset == 'bitcoin' else []
    if config.asset == 'bitcoin' and not risk_quotes:
        warnings.add('Risk replay uses hourly marks; minute-level drawdown execution is not reproduced')
    previous_quote = None
    for quote in risk_quotes:
        timestamp = instant(quote['at'])
        if positive(quote['ask'],'risk ask') < positive(quote['bid'],'risk bid'):
            raise ValueError('Crossed risk quote')
        if previous_quote and timestamp <= previous_quote:
            raise ValueError('Risk quotes must be strictly chronological')
        if previous_quote and (timestamp-previous_quote).total_seconds()>60:
            warnings.add('Minute risk quote coverage contains gaps')
        previous_quote = timestamp
    if risk_quotes and (instant(risk_quotes[0]['at'])>instant(rows[0]['at']) or instant(risk_quotes[-1]['at'])<instant(rows[-1]['at'])):
        warnings.add('Minute risk quotes do not cover the entire signal interval')
    if any(r.get('quote',{}).get('synthetic') or r.get('exit_quote',{}).get('synthetic') for r in rows):
        warnings.add('Synthetic bar execution proxies; historical spread and liquidity unavailable')
    if config.asset == 'stocks' and not data['manifest'].get('corporate_actions_verified'):
        warnings.add('Corporate action coverage is unverified')
    if config.asset == 'stocks' and data['manifest'].get('point_in_time_membership') and any('eligible' not in r for r in rows):
        warnings.add('Point-in-time membership assertions lack per-bar eligibility')
    if config.asset == 'stocks' and not data['manifest'].get('point_in_time_membership'):
        warnings.add('Current-universe selection: survivorship bias')
    for index, row in enumerate(rows):
        events.append((row['at'], 1, index, row))
        if row.get('quote'):
            events.append((row['quote']['at'], 0, index, row))
        if row.get('exit_quote'):
            events.append((row['exit_quote']['at'], -1, index, row))
    for action in data.get('corporate_actions',[]):
        effective=instant(action['at'])
        if instant(action['available_at'])>effective:
            raise ValueError('Corporate action was not available at its effective timestamp')
        if action['type'] not in ('split','cash_dividend'):
            raise ValueError('Unsupported corporate action')
        positive(action['ratio'] if action['type']=='split' else action['amount'],'corporate action')
        events.append((action['at'],-2,-1,action))
        if action['type']=='cash_dividend':
            if not action.get('pay_at') or instant(action['pay_at'])<effective:
                raise ValueError('Dividend requires a payment timestamp on or after its ex-date')
            events.append((action['pay_at'],-3,-1,action))
    for quote in risk_quotes:
        events.append((quote['at'],2,-1,{'symbol':'BTC/USD','quote':quote}))
    momentum, past = {}, {}
    for index,row in enumerate(rows):
        series = past.setdefault(row['symbol'],[])
        series.append(row['close'])
        momentum[index] = series[-1]/series[-21]-1 if len(series)>=21 else 0
    events.sort(key=lambda event: (instant(event[0]), event[1], -momentum.get(event[2],0), event[3]['symbol']))
    paused, fees, turnover, closed, wins = False, 0., 0., 0, 0
    risk_requested = None
    def equity():
        return cash + sum(receivables.values()) + sum(position['qty'] * marks[symbol] for symbol, position in holdings.items())
    for at, kind, index, row in events:
        if canceled():
            raise InterruptedError('Canceled by operator')
        if end and instant(at) >= instant(end):
            break
        symbol = row['symbol']
        trading = not start or instant(at) >= instant(start)
        if kind == -3:
            cash += receivables.pop((symbol,row['at']),0)
            continue
        if kind == -2:
            if row['type']=='split':
                ratio=float(row['ratio'])
                if symbol in holdings: holdings[symbol]['qty']*=ratio
                if symbol in planned: planned[symbol]['remaining']*=ratio
                if symbol in marks: marks[symbol]/=ratio
                history[symbol]=[{**bar,**{key:bar[key]/ratio for key in ('open','high','low','close')}} for bar in history.get(symbol,[])]
            elif trading and symbol in holdings:
                receivables[(symbol,row['at'])] = holdings[symbol]['qty']*float(row['amount'])
            continue
        if kind == 2:
            quote = row['quote']
            marks[symbol] = float(quote['bid'])
            if not trading:
                continue
            value = equity()
            peak = max(peak,value)
            drawdown = min(drawdown,value/peak-1)
            if risk_requested is not None and instant(at)>instant(risk_requested) and symbol in holdings:
                position = holdings.pop(symbol)
                price = float(quote['bid'])*(1-slip)
                amount = position['qty']*price
                fee = amount*fee_rate
                cash += amount-fee
                fees += fee
                turnover += amount
                closed += 1
                wins += amount-fee>position['cost']
                fills.append({'at':at,'symbol':symbol,'side':'sell','qty':position['qty'],
                              'price':price,'fee':fee,'reason':'Minute portfolio drawdown exit'})
                pending.pop(symbol,None)
            if drawdown<=-.10 and not paused:
                paused=True
                risk_requested=at
                pending.clear()
                planned.clear()
            value=equity()
            peak=max(peak,value)
            drawdown=min(drawdown,value/peak-1)
            curve.append({'at':at,'equity':round(value,6),'cash':round(cash,6)})
            continue
        if kind == 1:
            prior = history.setdefault(symbol, [])
            from .timeframes import advance
            if prior and config.asset == 'bitcoin' and advance(instant(prior[-1]['at']),getattr(config,'timeframe','1Hour')) != instant(at):
                warnings.add('Missing hourly bars; indicators restarted after gap')
                prior.clear()
            prior.append(dict(row))
            del prior[:-251]
            marks[symbol], sectors[symbol] = row['close'], row.get('sector', 'Bitcoin')
            if not trading:
                continue
            action, reason = decision(config, prior, symbol in holdings)
            if symbol in holdings:
                from .rules import position_exit
                p=holdings[symbol]
                forced=position_exit(config,row['close'],p.get('entry_price'),p.get('entered_at'),at)
                if forced:action,reason='sell',forced
            value = equity()
            peak = max(peak, value)
            drawdown = min(drawdown, value / peak - 1)
            if config.asset == 'bitcoin' and drawdown <= -.10:
                paused = True
                if risk_quotes and risk_requested is None: risk_requested=at
                pending.clear()
                planned.clear()
                action, reason = ('sell' if symbol in holdings else 'hold'), '10% portfolio drawdown breach'
            if paused and symbol in holdings:
                action = 'sell'
            if action == 'buy' and row.get('eligible') is False:
                action='hold'
            if action != 'hold' and (action != 'buy' or not paused) and symbol not in pending:
                if row.get('exit_quote' if action == 'sell' and row.get('exit_quote') else 'quote'):
                    pending[symbol] = (index, action, reason)
                else:
                    warnings.add('Signal skipped: no subsequent executable quote')
            curve.append({'at': at, 'equity': round(value, 6), 'cash': round(cash, 6)})
        elif trading and symbol in pending and pending[symbol][0] <= index:
            _, action, reason = pending[symbol]
            if (action == 'sell' and row.get('exit_quote') and kind != -1) or (action == 'buy' and kind == -1):
                continue
            quote = row['exit_quote'] if kind == -1 else row['quote']
            price = float(quote['ask'] if action == 'buy' else quote['bid']) * (1 + slip if action == 'buy' else 1-slip)
            if action == 'buy' and (symbol not in holdings or symbol in planned) and not paused:
                exposure = sum(p['qty'] * marks[s] for s, p in holdings.items())
                reserved=sum(p['remaining']*p['price']*(1+fee_rate) for other,p in planned.items() if other!=symbol)
                budget = min(max(0,cash-reserved) / (1 + fee_rate), max(0, equity()*config.allocation - exposure-reserved))
                if config.asset == 'stocks':
                    sector_value = sum(p['qty']*marks[s] for s,p in holdings.items() if sectors[s] == sectors[symbol])
                    budget = min(budget, 15., 30., max(0, 60. - sector_value))
                minimum = float(data.get('minimum_notional', 5))
                increment = positive(data.get('quantity_increment', 1e-9), 'quantity_increment')
                if symbol not in planned:
                    desired=math.floor(budget/price/increment)*increment
                    if desired*price<minimum:
                        pending.pop(symbol,None)
                        continue
                    planned[symbol]={'remaining':desired,'price':price}
                capacity=float(quote.get('ask_size',planned[symbol]['remaining']))
                if not math.isfinite(capacity) or capacity<0: raise ValueError('Invalid ask size')
                qty=min(planned[symbol]['remaining'],capacity,max(0,cash-reserved)/(price*(1+fee_rate)))
                qty=math.floor(qty/increment)*increment
                if qty<=0: continue
                amount=qty*price
                fee=amount*fee_rate
                cash-=amount if config.asset=='bitcoin' else amount+fee
                position=holdings.setdefault(symbol,{'qty':0.,'cost':0.})
                if getattr(config,'protocol',None)=='visual-rules-v1':
                    position['entry_price']=(position.get('entry_price',0)*position['qty']+price*qty)/(position['qty']+qty)
                    position.setdefault('entered_at',at)
                position['qty']+=qty*(1-fee_rate) if config.asset=='bitcoin' else qty
                position['cost']+=amount if config.asset=='bitcoin' else amount+fee
                planned[symbol]['remaining']-=qty
                if planned[symbol]['remaining']<increment:
                    planned.pop(symbol,None)
                    pending.pop(symbol,None)
            elif action == 'sell' and symbol in holdings:
                position = holdings[symbol]
                capacity=float(quote.get('bid_size',position['qty']))
                if not math.isfinite(capacity) or capacity<0: raise ValueError('Invalid bid size')
                qty=min(position['qty'],capacity)
                if qty<=0: continue
                amount=qty*price
                fee=amount*fee_rate
                cash+=amount-fee
                position['realized_proceeds']=position.get('realized_proceeds',0)+amount-fee
                position['qty']-=qty
                if position['qty']<1e-10:
                    closed+=1
                    wins+=position['realized_proceeds']>position['cost']
                    holdings.pop(symbol)
                    pending.pop(symbol,None)
            else:
                pending.pop(symbol,None)
                planned.pop(symbol,None)
                continue
            fees += fee
            turnover += amount
            fills.append({'at': at, 'symbol': symbol, 'side': action, 'qty': qty, 'price': price,
                          'fee': fee, 'reason': reason})
            marks[symbol] = float(quote['bid'])
            value = equity()
            peak = max(peak, value)
            drawdown = min(drawdown, value / peak - 1)
            curve.append({'at': at, 'equity': round(value, 6), 'cash': round(cash, 6)})
    final = equity()
    exposure = mean(1-p['cash']/p['equity'] for p in curve if p['equity']>0) if curve else 0
    net = final/starting_cash-1
    if config.asset == 'stocks' and 'SPY (price return)' not in data.get('benchmarks',{}) and 'SPY' not in data.get('benchmarks',{}):
        warnings.add('SPY benchmark unavailable')
    if closed < 30:
        warnings.add('Fewer than 30 closed trades; performance evidence is limited')
    interval=None
    if closed:
        z=1.959963984540054
        proportion=wins/closed
        center=(proportion+z*z/(2*closed))/(1+z*z/closed)
        half=z*math.sqrt(proportion*(1-proportion)/closed+z*z/(4*closed*closed))/(1+z*z/closed)
        interval={'lower':center-half,'upper':center+half,'method':'Wilson 95%; does not adjust for correlated trades'}
    return {'execution_parameters':{'version':'cash-cost-overrides-v1','fee_rate':fee_rate,'slippage_rate':slip},'win_rate_interval':interval,'engine': ENGINE_VERSION, 'capital_model': 'closed_cash_pool', 'starting_cash': starting_cash,
            'ending_equity': final, 'net_return': net, 'maximum_drawdown': drawdown,
            'fees': fees, 'turnover': turnover/starting_cash, 'average_exposure':exposure,
            'cost_drag_from_fees':fees/starting_cash, 'net_return_above_cash':net, 'closed_trades': closed,
            'win_rate': wins/closed if closed else None, 'risk_paused': paused,
            'open_positions': holdings, 'fills': fills, 'equity_curve': curve,
            'warnings': sorted(warnings), 'evidence': 'exploratory' if warnings or closed < 30 else 'review_required'}
