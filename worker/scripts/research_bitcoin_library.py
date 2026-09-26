"""Reproduce the curated Bitcoin study without touching any operational database.

Usage: PYTHONPATH=worker/src python3 worker/scripts/research_bitcoin_library.py INPUT OUTPUT_DIR
INPUT is the retained /api/crypto/market/history response, not invented prices.
"""
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from statistics import median

from stock_watch_worker.systems.engine import canonical, instant, replay, validate_dataset
from stock_watch_worker.systems.rules import RuleConfig


def group(op, left, right):
    return {'op': 'all', 'conditions': [{'op': op, 'left': left, 'right': right}]}


def candidates():
    close = {'kind': 'close'}
    definitions = [
        ('sma-200', '200-day trend', 'Trend following',
         'Enter above the 200-day simple moving average; exit below it.',
         'Daily Bitcoin adaptation of moving-average timing; not a replication of the monthly, diversified Faber model.',
         'Meb Faber: timing model FAQ', 'https://mebfaber.com/timing-model/',
         group('gt', close, {'kind': 'sma', 'period': 200}),
         group('lt', close, {'kind': 'sma', 'period': 200})),
        ('channel-20-10', '20/10-day breakout', 'Channel breakout',
         'Enter when the close exceeds the prior 20-day high; exit below the prior 10-day low.',
         'Long-only, close-confirmed 20/10-day adaptation. The cited example uses intrabar stops, a five-bar channel and short reversals.',
         'TradingView: Channel BreakOut Strategy', 'https://www.tradingview.com/support/solutions/43000599828-channel-breakout-strategy/',
         group('gt', close, {'kind': 'prior_high', 'period': 20}),
         group('lt', close, {'kind': 'prior_low', 'period': 10})),
        ('rsi-14', 'RSI reversal', 'Mean reversion',
         'Enter when RSI (14) crosses above 30; exit when it crosses below 70.',
         'Long-only adaptation of the documented RSI reversal: sell to cash instead of reversing short. Thresholds frozen at 30/70.',
         'TradingView: RSI Strategy', 'https://www.tradingview.com/support/solutions/43000645066-rsi-strategy/',
         group('crosses_above', {'kind': 'rsi', 'period': 14}, {'kind': 'number', 'value': 30}),
         group('crosses_below', {'kind': 'rsi', 'period': 14}, {'kind': 'number', 'value': 70})),
    ]
    for identifier, name, family, rules, adaptation, title, url, entry, exit in definitions:
        config = RuleConfig('bitcoin', entry, exit, allocation=.25, holding_count=12,
                            holding_unit='months', stop_loss=1., take_profit=1.)
        yield {'id': identifier, 'name': name, 'family': family, 'rules': rules,
               'adaptation': adaptation, 'source': {'title': title, 'url': url},
               'config': asdict(config), 'version': config.sha256}, config


def dataset(chart):
    if chart.get('status') != 'ready' or chart.get('partial') or chart.get('resolution') != '1Day':
        raise ValueError('Complete daily chart history is required')
    end = instant(chart['requestedEnd'])
    raw = chart['bars']
    rows = []
    for i, bar in enumerate(raw):
        # A bar stamped at its open cannot be used until the following daily close.
        at = instant(bar['at']) + timedelta(days=1)
        if at > end:
            continue
        row = {k: bar[k] for k in ('open', 'high', 'low', 'close', 'volume')}
        row.update(symbol='BTC/USD', at=at.isoformat(), available_at=at.isoformat())
        if i + 1 < len(raw) and instant(raw[i + 1]['at']) == at and at < end:
            price = raw[i + 1]['open']
            row['quote'] = {'at': (at + timedelta(seconds=1)).isoformat(),
                            'bid': price, 'ask': price, 'synthetic': True}
        rows.append(row)
    data = {'schema_version': 1, 'asset': 'bitcoin', 'slippage_bps': 5, 'bars': rows,
            'manifest': {'provider': chart['provider'], 'venue': 'Alpaca US', 'fidelity': 'bar_approximation',
                         'timeframe': '1Day', 'retrieved_at': chart['observedAt']}}
    validate_dataset(data, 'bitcoin')
    if any(instant(b['at']) - instant(a['at']) != timedelta(days=1) for a, b in zip(rows, rows[1:])):
        raise ValueError('Study requires contiguous daily bars')
    return data


def benchmark(data, start, end, allocation):
    rows = [b for b in data['bars'] if instant(start) <= instant(b['at']) <= instant(end)]
    first = next(b for b in rows if b.get('quote'))
    # Same initial decision time and next-open proxy, fee and slippage as strategy.
    paid = first['quote']['ask'] * 1.0005
    quantity = 300 * allocation / paid * .9975
    final = 300 * (1 - allocation) + quantity * rows[-1]['close']
    return final / 300 - 1


def study(chart):
    chart = chart.get('source_chart', chart)
    data = dataset(chart)
    periods = [(str(y), f'{y}-01-01T00:00:00Z', f'{y+1}-01-01T00:00:00Z') for y in range(2022, 2026)]
    periods.append(('2026 YTD', '2026-01-01T00:00:00Z', chart['requestedEnd']))
    if instant(data['bars'][0]['at']) > instant(periods[0][1]) - timedelta(days=251):
        raise ValueError('At least 251 warmup days are required before the first study period')
    if instant(data['bars'][-1]['at']) < instant(periods[-1][2]):
        raise ValueError('History does not cover the complete requested study')
    digest = hashlib.sha256(canonical(data).encode()).hexdigest()
    summaries, evidence = [], []
    for meta, config in candidates():
        windows, full = [], []
        for label, start, end in periods:
            # Include the final completed daily close, never the following execution.
            cutoff = (instant(end) + timedelta(seconds=1)).isoformat()
            base = replay(config, data, start=start, end=cutoff)
            stress = replay(config, data, start=start, end=cutoff, cost_multiplier=2)
            windows.append({'label': label, 'start': start, 'end': end,
                            **{k: base[k] for k in ('net_return', 'maximum_drawdown', 'closed_trades',
                                                   'win_rate', 'win_rate_interval', 'risk_paused', 'average_exposure', 'warnings')},
                            'stress_return': stress['net_return'],
                            'open_positions': len(base['open_positions']),
                            'benchmark_return': benchmark(data, start, end, .25),
                            'btc_return': benchmark(data, start, end, 1.)})
            full.append({'label': label, 'start': start, 'end': end, 'base': base, 'double_cost': stress})
        trades = sum(w['closed_trades'] for w in windows)
        wins = sum(round(w['win_rate'] * w['closed_trades']) for w in windows if w['closed_trades'])
        summary = {**meta, 'windows': windows, 'backtest_count': len(windows) * 2,
                   'period_count': len(windows), 'profitable_periods': sum(w['net_return'] > 0 for w in windows),
                   'closed_trades': trades, 'win_rate': wins / trades if trades else None,
                   'median_return': median(w['net_return'] for w in windows),
                   'worst_drawdown': min(w['maximum_drawdown'] for w in windows)}
        summaries.append(summary)
        evidence.append({**meta, 'runs': full})
    common = {'schema_version': 1, 'study_id': 'bitcoin-daily-2026-09-26-v1',
              'collected_at': chart['observedAt'], 'dataset_sha256': digest,
              'coverage': {'first': data['bars'][0]['at'], 'last': data['bars'][-1]['at'], 'bars': len(data['bars'])},
              'methodology': [
                  'Three fixed rule sets, selected before calculating results; no parameter optimization or discarded losing candidates.',
                  'Five non-overlapping evaluation periods, each starting flat with $300. 2026 is a shorter YTD period. Prior bars provide warmup only.',
                  'Ten backtests per system: five base runs plus five double-cost stress runs. Stress runs are not independent evidence.',
                  'Daily completed-bar decisions, next-day open execution proxy; 0.25% fee and 0.05% slippage per side. Stress doubles both.',
                  '25% portfolio allocation per entry; 10% portfolio drawdown pauses further entries for that period. 12-month holding cap, 100% price profit cap.',
                  'Ending open positions are marked to market, not counted as closed wins. No forced liquidation or exit fee at the period boundary.',
                  'Benchmark: 25% buy-and-hold BTC with 75% idle cash, same initial execution cost model; full BTC is shown separately.',
                  'Daily bars cannot reproduce spreads, liquidity or intraday risk exits. Results are exploratory, retrospective and not forward qualification.',
                  'Comparing three candidates on shared history introduces selection bias. Repeated historical runs do not increase independent sample size.',
              ]}
    return {**common, 'systems': summaries}, {**common, 'systems': evidence, 'dataset': data, 'source_chart': chart}


if __name__ == '__main__':
    raw = Path(sys.argv[1]).read_text()
    summary, evidence = study(json.loads(raw))
    destination = Path(sys.argv[2]); destination.mkdir(parents=True, exist_ok=True)
    (destination / 'bitcoin-study-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (destination / 'bitcoin-study-evidence.json').write_text(canonical(evidence) + '\n')
    for item in summary['systems']:
        print(item['name'], 'runs:', item['backtest_count'], 'closed trades:', item['closed_trades'],
              'win rate:', item['win_rate'], 'median return:', item['median_return'])
