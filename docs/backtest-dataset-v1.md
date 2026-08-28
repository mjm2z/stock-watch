# Backtest dataset manifest v1

`stock-watch-worker run-backtest` consumes a self-contained JSON manifest of
point-in-time scored close signals and adjusted daily bars. The complete
canonical JSON document is SHA-256 hashed and stored with the run, so changed
signals, prices, or walk-forward boundaries create a different experiment.

This format intentionally does not accept opening signals. A valid 09:45
simulation requires timestamped intraday inputs; substituting a completed daily
bar would introduce lookahead bias.

## Shape

```json
{
  "schema_version": 1,
  "dataset_version": "sp500-close-2018-2025-v1",
  "feature_set_version": "features-v0",
  "scan_type": "close",
  "provenance": {
    "universe_membership_mode": "point_in_time",
    "universe_snapshots": [
      {
        "id": 12,
        "effective_at": "2023-01-01",
        "content_sha256": "...",
        "survivorship_biased": false
      }
    ]
  },
  "walk_forward": {
    "train_sessions": 504,
    "validation_sessions": 126,
    "test_sessions": 126,
    "step_sessions": 126,
    "expanding": true
  },
  "bars": {
    "SPY": [
      {
        "session": "2018-01-02",
        "open": 267.84,
        "high": 268.81,
        "low": 267.4,
        "close": 268.77,
        "volume": 86655700
      }
    ],
    "AAPL": []
  },
  "signals": [
    {
      "symbol": "AAPL",
      "signal_session": "2023-02-10",
      "horizon_trading_days": 21,
      "opportunity_score": 84.2,
      "data_completeness": 100,
      "risk_level": "low",
      "vetoes": [],
      "universe_snapshot_id": 12
    }
  ]
}
```

Every bar array must cover the future entry/holding window for its signals.
`SPY` is mandatory and supplies both the exchange-session sequence and the
identical benchmark boundaries. Test windows may be adjacent or separated but
cannot overlap (`step_sessions >= test_sessions`).

The signals are scored candidates, not assumed trades. The runner reapplies the
immutable strategy version's minimum score, data-completeness, allowed-risk,
veto, universe-membership, notional-sizing, and duplicate-open-lot rules.
Signals outside all test windows are retained in the dataset hash but excluded
from reported test performance. Validation-window observations are summarized
separately and never mixed into test metrics.

Dataset producers are responsible for constructing every score using only
information published by `signal_session`. A manifest made from today's S&P
500 members must be paired with a snapshot marked `survivorship_biased`; it
cannot be treated as point-in-time constituent history.

For `point_in_time` membership, every signal names its effective snapshot and
the provenance block contains each snapshot's immutable ID, effective time,
content hash, and bias flag. The runner verifies those values against SQLite,
requires all snapshots to belong to the anchor universe, and requires each
signal to use the latest snapshot effective by its session. Missing coverage,
same-day ambiguity, undeclared snapshots, and provenance drift fail the run.

## Build from the worker database

The included builder reuses the production feature/scoring code. It uses only
bars through each close, extracts SEC values whose individual `filed` dates are
not later than that close, and marks historical news unavailable rather than
assuming neutral sentiment unless a completed historical-news ingestion is
explicitly selected.

Constituent history is imported as a long-form CSV. Each effective date must
contain the complete membership, not merely additions and removals:

```csv
effective_at,symbol,name,exchange,cik
2020-01-01,AAPL,Apple Inc.,NASDAQ,320193
2020-01-01,MSFT,Microsoft Corp.,NASDAQ,789019
2020-04-01,AAPL,Apple Inc.,NASDAQ,320193
```

```bash
stock-watch-worker import-universe-history \
  --database /var/lib/stock-watch/stock-watch.db \
  --csv /path/to/sp500-history.csv \
  --universe sp500 \
  --source "licensed-constituent-history"
```

```bash
stock-watch-worker backfill-bars \
  --database /var/lib/stock-watch/stock-watch.db \
  --data-path /var/lib/stock-watch/data \
  --universe-snapshot-id 1 \
  --start 2018-01-01 \
  --end 2026-08-20 \
  --point-in-time-universe

stock-watch-worker backfill-news \
  --database /var/lib/stock-watch/stock-watch.db \
  --data-path /var/lib/stock-watch/data \
  --universe-snapshot-id 1 \
  --start 2018-01-01 \
  --end 2025-12-31 \
  --point-in-time-universe

stock-watch-worker backfill-calendar \
  --database /var/lib/stock-watch/stock-watch.db \
  --data-path /var/lib/stock-watch/data \
  --start 2019-01-01 \
  --end 2025-12-31

stock-watch-worker build-backtest-dataset \
  --database /var/lib/stock-watch/stock-watch.db \
  --output /var/lib/stock-watch/research/sp500-close-v1.json \
  --strategy-id sp500-long-v0 \
  --universe-snapshot-id 1 \
  --start 2019-01-01 \
  --end 2025-12-31 \
  --point-in-time-universe \
  --historical-news-ingestion-id 2 \
  --historical-calendar-ingestion-id 3 \
  --news-lookback-days 3
```

The default five-session signal stride is an exploratory resource bound, not
the exact twice-daily production cadence. Use `--signal-stride-sessions 1` for
daily close evaluation. The command refuses to exceed one million signal rows
unless `--maximum-signals` is deliberately raised. The free IEX feed represents
one exchange rather than consolidated SIP data, and that limitation must remain
attached to resulting performance claims.

Historical news is fetched in bounded date windows and symbol chunks, with all
raw responses captured before transformation. Failed runs are restartable and
deduplicate immutable article IDs. Selecting an ingestion for dataset building
requires succeeded coverage across every universe symbol and the complete
lookback interval. Each close signal uses only articles published during the
lookback and no later than that date's persisted exchange close. A selected
news ingestion therefore requires a selected, succeeded calendar ingestion
covering every evaluated SPY session. DST and early closes come from the
provider rather than weekday assumptions; both ingestion versions remain
attached to dataset provenance.

## Run

```bash
stock-watch-worker run-backtest \
  --database /var/lib/stock-watch/stock-watch.db \
  --dataset /path/to/backtest-dataset.json \
  --strategy-id sp500-long-v0 \
  --universe-snapshot-id 1 \
  --round-trip-cost-bps 10 \
  --minimum-validation-trades 20 \
  --minimum-reliability-trades 30
```

The command persists the immutable run, chronological splits, test trades,
explicit rejection reasons, cost-adjusted outcomes, SPY excess return, results
by horizon and score bucket, unlimited-funding portfolio analytics, and an
audit event. Identical inputs return the existing run instead of duplicating
it. Simulation enforces the configured USD 5-15 lot sizing, one open lot per
ticker/horizon/version, and USD 30 concurrent open notional per ticker. There
is deliberately no aggregate cash ceiling during this calibration phase.

For each walk-forward split, the runner evaluates the strategy's score-band
thresholds on validation observations. It selects the threshold maximizing an
equal-weight objective of the 95% Wilson lower bounds for positive-return and
beat-SPY rates, then freezes that threshold for the untouched test window. The
raw point objective is retained beside the conservative objective for audit.
Thresholds with fewer than
`--minimum-validation-trades` are excluded. If every threshold is underpowered,
the split is labeled accordingly and falls back to the strategy's configured
minimum instead of selecting from noise.

The report separately summarizes only untouched test-fold trades. Positive
return, +5%, +10%, and beat-SPY frequencies include 95% Wilson intervals,
sample counts, and an explicit `underpowered` status until the cohort reaches
`--minimum-reliability-trades`. These empirical overall, horizon, score-band,
and horizon-by-score-band rates are conditioned on the strategy's selection
rules. They are not presented as calibrated per-signal probabilities; Brier
scores and probability calibration curves remain unavailable until a frozen
forecast model exists.

Portfolio metrics model each accepted lot as an independent external capital
contribution. A matched SPY cohort receives the same dollars at the same entry
open and exits on the same session close. Daily returns are capital weighted
across active cohorts and use zero on inactive sessions between the first entry
and final exit, so contributions do not masquerade as performance. Reports
include contribution return and P&L, matched-SPY and excess results, drawdown,
252-session annualized return and volatility, zero-risk-free Sharpe, zero-target
Sortino, exposure, concurrent lots, and gross turnover relative to average
active capital. These results describe unlimited externally funded fixed-lot
cohorts, not a self-financing portfolio with a cash balance.
The portfolio-analytics version is part of the deterministic run configuration,
so changing the accounting model produces a distinct immutable run instead of
silently reusing cached metrics.
