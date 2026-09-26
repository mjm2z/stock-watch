# Crypto charts and research library

The live queue showed a chart waiting 87 seconds and then collecting in about one
second. The former one-job-per-minute research scheduler, shared backtest queue,
five-minute cache keys and 15-second UI polling compounded the delay.

`chart-next` now owns chart jobs under its own process lock. A separate five-second
timer runs bounded batches, independent of long backtests. Research and chart
workers never recover or claim each other's jobs. Existing research and trading
timer states stay unchanged. Daily charts reuse an hourly cache; recently cached
matching preset ranges remain visible during refresh. Custom windows require an
exact match. The browser keeps visited ranges and polls pending work every two
seconds, with no overlapping fetches. Cold provider collection still takes time.

The Crypto overview places a researched systems comparison below the price chart.
The isolated header action moves into this section. Empty quotes and decision cards
are omitted from the overview, while paper setup has a contextual next step.
Existing dedicated paper, signals and operations views remain available.

## Reproducible study

Three fixed Bitcoin long-only adaptations: 200-day SMA trend, 20/10-day channel
breakout and RSI(14) 30/70 reversal. Sources and differences from their original
rules appear in each card. These are hypotheses, not recommended investments:

- https://mebfaber.com/timing-model/
- https://www.tradingview.com/support/solutions/43000599828-channel-breakout-strategy/
- https://www.tradingview.com/support/solutions/43000645066-rsi-strategy/

Provider history was collected through the existing market-data API without
requesting credentials or changing operational trading data. The incomplete final
daily candle is excluded. Completed bars become available at their close; modeled
fills use the following open, strictly after the decision. Retained results contain
the input dataset, original chart response, hashes, frozen configurations, fills,
equity curves and warnings. Thirty simulations cover 2022, 2023, 2024, 2025 and
2026 YTD: five base periods and five double-cost runs per system. Stress runs do
not increase independent sample size. All candidates and losing periods are kept.

Every period begins flat with $300 and earlier bars for indicator warmup. Entry
allocation is 25%, with the app's 10% portfolio drawdown pause, twelve-month holding
cap and 100% price profit cap. Fees are 25 bps per side and slippage five bps;
stress doubles both. Terminal positions are marked, not forcibly liquidated.
The comparison benchmark initially invests 25% in BTC, with the same modeled
entry costs, and leaves 75% as zero-yield cash; full BTC is separately labeled.
Neither benchmark uses the strategy's risk pause or re-entry rule, so exposure
and drawdown differences still matter. 2026 YTD is shorter than the other periods.

No parameter search was performed. These are retrospective evaluations, not
unseen live observations or a claim of out-of-sample effectiveness. Comparing
candidates creates selection bias. Every system has fewer than 30 closed trades;
the UI shows this, confidence intervals, risk pauses, costs and mark-to-market
open positions. A high win rate can coexist with a poor or fragile return.

Reproduce using Python 3.12 and the evidence file downloaded from the app:

```sh
PYTHONPATH=worker/src python3.12 worker/scripts/research_bitcoin_library.py \
  lib/research/bitcoin-study-evidence.json /tmp/stockwatch-study-reproduction
```

The study is an immutable bundled research snapshot, separate from user-requested
backtest runs. Copying a system opens an editable draft; saving, publishing,
backtesting and paper activation retain the existing explicit workflows. Copies
use separate browser storage so another unfinished draft is preserved.

## Deployment

`install-crypto-research.py` verifies the reviewed staging hashes, dependencies,
installed source baseline and worker wheel. It retains code, wheel, web build and
receipt for rollback, drains current workers, switches the web build, checks
readiness and enables only the chart collection timer. No database migration or
strategy activation occurs. Root runs the install as a supervised oneshot,
independent of SSH; failures restore code before resuming previous timers.
