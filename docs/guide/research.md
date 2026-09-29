# Research and controlled experiments

[Application guide](../../README.md)

An experiment freezes its question, mechanism, baseline/candidate snapshot IDs,
asset, retained dataset, interval, primary outcome, risk constraints, selection
rule, review point, cost convention and capital. An amendment is a new record
linked to its parent. Reviews append conclusions and explanations; they never
modify the frozen plan or change trading authority.

Three dimensions remain independent:

- Job: queued, running, succeeded, failed or canceled, with retained errors.
- Conclusion: unreviewed, invalid inputs, not supported, inconclusive,
  promising historically or supported by additional forward evidence.
- Authority: these records are research-only. Existing live system authority is
  determined by its own policy and ownership records, not a reviewer label.

Attempts link to actual workspace jobs and snapshots. An explicit retry is an
attempt, not automatically independent evidence. Identical completed work may
reuse its original artifact and timestamp. Inspected intervals are recorded
asset-wide to conservatively cover copied configurations and unknown lineage.
Legacy search counts remain unknown; no retrospective claim of complete trial
history is made. The existing 100 stress scenarios are execution/authorization
stress profiles, not 100 independent strategies.

Comparable pairs require the same dataset, engine, period, costs, capital and
decision timeframe. The UI shows net return, drawdown, fees, turnover, exposure,
trade coverage and net trade metrics. Continuous-account curves do not reset
high-water marks at fold boundaries. The existing flat-start fold report remains
separate. Full-resolution metrics precede display sampling. Sparse marks cannot
establish between-observation drawdowns.

**Worked demonstration:** create the daily BTC breakout 55/20 versus 55/10
example. It freezes the hypothesis that a shorter exit may reduce drawdown at
the expense of turnover. Criteria require better net return without worse
drawdown; fewer than 30 closed trades is inconclusive. The deterministic 730-day
fixture is not market data and is labelled at dataset, plan and result levels.
Inspect both attempts, retain the result, record an inconclusive or other
supported conclusion, then create a deliberate linked revision. The real-data
plan remains blocked until suitable retained daily observations and matching
cost/coverage evidence are verified. No system is published or activated.

| Existing / candidate input | Category | Boundary |
| --- | --- | --- |
| SMA/EMA, prior high/low, RSI | Return hypotheses | Existing versioned rules; compare under frozen costs and dates |
| Volume / average volume | Liquidity/context and hypothesis input | Missing or incomparable volume remains unavailable |
| Stop loss, holding deadline, drawdown | Risk controls | Preserve live thresholds; simulations do not authorize changes |
| Spread, fees, dispatch timing | Execution diagnostics | Not interchangeable bullish votes |
| Feed heartbeat and worker health | Operational health | Not a return predictor |
| ATR-normalized exits | Candidate risk/return experiment | Deferred until an explicit versioned rule and paired test are implemented |
| Relative strength vs SPY/BTC | Candidate return hypothesis | Requires aligned historical series, treatment and availability evidence |

No broad optimizer, paid data purchase, hidden natural-language trading parser or
automatic promotion is included. Formal time-block uncertainty, DSR/PBO and
calibrated probabilities remain unavailable without adequate aligned return,
selection and holdout inputs. Benchmark price returns are not labelled total
returns; manual allocation returns are never divided by the broker's $1M cash.
