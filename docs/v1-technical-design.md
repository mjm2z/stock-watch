# Stock Watch v1 Technical Design

Status: accepted for implementation
Scope: automated research and paper trading only
Initial deployment: `a1347-j`

## 1. Product objective

Stock Watch evaluates the current S&P 500 twice per US trading day and records
reproducible, evidence-backed signals for long-only fractional stock positions.
Qualifying signals create paper orders automatically. The system measures both
absolute returns and returns relative to SPY over 5, 21, 63, and 105 trading-day
horizons.

The application is an experimental research system, not a live-trading system.
The initial implementation must not be capable of sending orders to a live
brokerage endpoint.

## 2. Accepted product decisions

- Universe: current S&P 500 constituents.
- Direction: long only.
- Instruments: fractional US equities; no options or short positions.
- Scan windows: approximately 09:45 and 16:15 America/New_York on exchange
  trading days.
- Horizons: 5, 21, 63, and 105 trading days.
- Minimum hold: a position cannot close on its entry trading day.
- Base paper notional: USD 10, adjusted between USD 5 and USD 15.
- Execution: every new qualifying opportunity is submitted automatically to a
  paper-only account.
- Deduplication: at most one open lot for a ticker, horizon, and strategy
  version. Repeated signals remain recorded but do not create duplicate lots.
- Initial operating budget: USD 0 per month.
- Host: `a1347-j` using Python, systemd, SQLite, DuckDB/Parquet, and the existing
  Next.js dashboard.

## 3. System boundaries

```text
Alpaca prices/news + SEC filings + FRED/ALFRED + universe snapshot
                              |
                              v
                    ingestion and validation
                              |
                              v
                 point-in-time feature snapshots
                              |
                              v
              versioned score and qualification engine
                       |                  |
                       v                  v
                  backtester       scheduled scan runs
                       |                  |
                       +---------+--------+
                                 v
                     qualified signal ledger
                                 |
                                 v
                  paper-only orders and trade lots
                                 |
                                 v
              dashboard, outcomes, and calibration
```

The LLM is not part of the automated v1 decision path. Automated explanations
come from factor contributions, source links, and deterministic templates.
Paid or local language-model summaries may be added later, but they cannot
change a score or submit an order.

## 4. Deployment architecture

### 4.1 Processes

- `stock-watch-web.service`: standalone Next.js dashboard.
- `stock-watch-worker.service`: durable job runner for ingestion, scoring,
  outcome updates, and paper order reconciliation.
- `stock-watch-dispatch.timer`: runs every five minutes. The dispatcher uses a
  US exchange calendar and creates idempotent opening or closing scan jobs only
  inside the configured windows.
- `stock-watch-maintenance.timer`: reconciles entry/exit fills, captures and
  reconciles Alpaca account positions/non-trade activities, and persists newly
  mature forward outcomes after the opening and closing workflows.
- `stock-watch-backup.timer`: creates a daily recoverable database backup.

The host remains configured in UTC. All market-session decisions are performed
with explicit `America/New_York` timestamps and a real exchange calendar so DST,
holidays, and early closes are handled correctly.

### 4.2 Storage

- SQLite in WAL mode stores configuration, scan runs, signals, jobs, paper
  orders, fills, lots, outcomes, immutable broker snapshots/reconciliations,
  and audit information.
- DuckDB queries partitioned Parquet price, feature, and research datasets.
- Provider responses first land in an immutable, content-addressed gzip JSON
  store; validated transformations then produce the queryable Parquet datasets.
- Historical datasets are immutable by partition. Corrections create a new
  ingestion version instead of silently changing an old backtest.
- The browser's existing localStorage records will eventually be migrated into
  SQLite; localStorage will not be authoritative after the server-backed API is
  introduced.

SQLite is sufficient for this single-user workload. PostgreSQL is an explicit
upgrade path if concurrent writers or multiple users are introduced.

## 5. Zero-cost data policy

### 5.1 Initial providers

- Alpaca Basic: adjusted historical bars, delayed/current snapshots, news, and
  paper execution.
- SEC EDGAR: timestamped filings and XBRL company facts.
- FRED/ALFRED: macroeconomic and point-in-time vintage data.
- A daily versioned S&P 500 membership snapshot from an approved source.

Yahoo Finance remains a chart convenience only and is not authoritative for
backtests or outcome calculation.

### 5.2 Known limitations

- Free Alpaca real-time equities data uses IEX rather than the full SIP feed.
- Reliable historical S&P membership is difficult at zero cost. Backtests made
  only with today's constituents are marked `survivorship_biased=true` and
  cannot support strong performance claims.
- Portfolio snapshots mark stored fill quantities against adjusted daily bars.
  Every paper scan now captures Alpaca account/position/activity state and
  fails closed on unexplained quantity drift or account restrictions. Split
  and other corporate-action evidence is surfaced without silently rewriting
  lots; dividend cash is not yet attributed to individual lots. A dedicated
  paper account is required, and snapshots are not brokerage statements.
- Fundamental field coverage varies between issuers because SEC XBRL tags are
  not perfectly uniform.
- Automated Claude analysis is excluded while the operating budget is zero.

The first paid-data priority is point-in-time membership and fundamentals,
followed by consolidated market data. AI generation is a lower priority.

## 6. Strategy contract

Every strategy version is immutable and contains:

- eligible universe and direction;
- scan windows and horizons;
- feature definitions and weights;
- qualification thresholds and veto rules;
- notional-sizing rules;
- entry, holding, and exit rules;
- assumed transaction costs;
- provider and dataset versions.

Changing any item creates a new strategy version. Signals, backtests, and paper
lots always reference the exact version that created them.

Promotion to paper trading also creates a new immutable version; it does not
update the development or backtest row in place. The operator must explicitly
repeat the new paper version ID, the source hash is revalidated, and creation of
the paper row and its audit event is atomic. The scheduled dispatcher selects
the resulting version through deployment configuration.

### 6.1 Initial score

The transparent heuristic score has six pillars:

| Pillar | Weight |
| --- | ---: |
| Momentum and relative strength | 25% |
| Fundamental quality and growth | 20% |
| Relative valuation | 15% |
| News and catalyst evidence | 15% |
| Market regime | 10% |
| Risk and liquidity quality | 15% |

Each available pillar is normalized to 0-100. Missing pillars reduce data
completeness. The score is the weighted mean of available pillars; qualification
requires at least 80% weighted completeness.

Initial qualification rules:

- opportunity score is at least 75;
- weighted data completeness is at least 80%;
- risk is `low` or `medium`;
- no active veto exists;
- the ticker belongs to the universe at the signal timestamp.

This is called a heuristic confidence score until backtesting can calibrate
actual probabilities. A later model may add `probability_positive` and
`probability_beat_spy`, but only after out-of-sample calibration.

### 6.2 Paper sizing

| Opportunity score | Starting notional |
| --- | ---: |
| 75-79.99 | $7.50 |
| 80-87.99 | $10.00 |
| 88-93.99 | $12.50 |
| 94-100 | $15.00 |

Medium-risk signals receive a 0.85 multiplier. The result is rounded to the
nearest USD 0.50 and clamped to USD 5-15. High-risk signals do not qualify.

Portfolio constraints:

- no more than USD 30 open notional per ticker;
- one open lot per ticker/horizon/strategy version;
- no aggregate cash ceiling during the initial research and paper-calibration
  phase; every qualifying USD 5-15 lot is treated as independently funded;
- rejected orders never get blindly resubmitted; reconciliation first checks
  the broker and the stored idempotency key.

## 7. Signal and execution lifecycle

1. The dispatcher creates an idempotent scan run.
2. The worker freezes the universe and provider timestamps.
3. Data validators reject stale, missing, anomalous, or future-dated inputs.
4. Features and their raw source references are persisted.
5. The strategy produces pillar contributions, score, completeness, risk, and
   vetoes.
6. A signal row is stored whether or not it qualifies.
7. For paper strategies, the worker immutably captures account, position, and
   non-trade activity state and reconciles it with open strategy lots.
8. Each qualified horizon is checked against broker state and open-lot limits.
9. A paper order is created with a deterministic client order ID.
10. The broker response, request ID, order updates, and fills are reconciled.
11. Outcome jobs mark the signal at 5, 21, 63, and 105 trading days.

The paper endpoint is compiled/configured as an allowlisted constant. Supplying
a live Alpaca endpoint is a fatal configuration error.

## 8. Backtesting rules

- Features may use only information published at or before the signal time.
- Opening scans use the prior close, information available overnight, and only
  opening-session data available by the simulated scan time.
- Closing scans execute no earlier than the next permitted price after the
  signal is complete.
- Price series are adjusted consistently for splits, dividends, and spin-offs.
- Each simulation includes configurable spread/slippage assumptions.
- Train, validation, and untouched test windows are chronological and rolling;
  random cross-validation is prohibited.
- Thresholds are selected on validation data and evaluated once on the test
  period.
- Every report states whether its universe is survivorship biased.

The executable v1 backtest path accepts a content-hashed manifest of
point-in-time scored close candidates and adjusted daily stock/SPY bars. It
reapplies the immutable strategy's qualification, veto, sizing, universe, and
open-lot rules; evaluates only chronological test windows; stores validation
metrics separately; and persists every trade and rejection with its dataset
SHA-256. Opening-scan simulation remains disabled until timestamped intraday
inputs are available.

Within each walk-forward split, candidate score thresholds are compared only
on the validation window using an equal-weight objective of the 95% Wilson
lower bounds for positive-return and beat-SPY rates. Point estimates remain in
the audit record, but do not let a small lucky cohort outrank a better-supported
candidate. A threshold must have a minimum validation cohort; an
underpowered split is explicitly labeled and falls back to the immutable
strategy minimum. The chosen threshold is then frozen for that split's
untouched test window.

Untouched test trades also produce empirical reliability reports for the two
accepted success definitions: positive net return and beating SPY. Reports use
95% Wilson intervals and minimum-cohort labels overall, by horizon, by score
band, and by their intersection. They explicitly identify themselves as
selection-conditioned historical frequencies—not calibrated probability
forecasts—so sparse wins cannot be displayed as high-confidence evidence.

Backtest portfolio analytics use the same unlimited-funding convention as the
initial paper-calibration phase. Every accepted confidence-sized lot receives
its own external contribution, subject to the USD 30 concurrent notional cap
per ticker and the duplicate-lot rule. An equal-dollar SPY cohort enters and
exits on the same sessions. A capital-weighted daily return series adjusts for
new contributions and removals; sessions between the first entry and final
exit with no active lots contribute zero return. This is not a self-financing
cash portfolio and must not be presented as one.

The portfolio report includes return on contributed capital, contribution-
matched SPY and excess performance, annualized active return and volatility,
maximum drawdown, Sharpe and Sortino ratios, active-capital exposure, concurrent
lots, and gross traded value relative to average active capital. Annualization
uses 252 sessions and the initial research report assumes a zero risk-free rate
and zero Sortino target.

A restart-safe historical ingestion can populate adjusted Alpaca daily bars
for a frozen universe and SPY. It can also resolve a versioned constituent
timeline and fetch the union of members present during the requested period.
The manifest builder then reuses the production
feature and score functions at rolling close cutoffs, filters SEC observations
by filing date, uses only news published before the persisted exchange-session
close when complete historical news and calendar ingestions are selected,
leaves unavailable news unscored, enforces warm-up
and maximum-horizon coverage, and carries universe/feed limitations into
dataset provenance. Its default five-session stride is for bounded exploratory
runs; strategy-faithful close testing uses a stride of one.

Point-in-time manifests attach an immutable universe snapshot ID to every
signal. The runner rechecks snapshot hashes, universe identity, membership,
effective dates, and the absence of same-day ambiguity before simulation.
This removes current-constituent survivorship bias only when the imported
history itself is complete and its snapshots are not marked biased.

Required results include total and annualized return, SPY excess return, hit
rate, maximum drawdown, volatility, Sharpe/Sortino, turnover, exposure, result
by score bucket, and result by horizon. Once probabilities exist, reports also
include Brier score and calibration curves.

## 9. Outcome definitions

For each signal/horizon the system stores:

- terminal total return;
- terminal return at least 0%, 5%, and 10%;
- whether price touched +5% and +10% before the horizon;
- SPY total return over identical timestamps;
- terminal excess return and whether it beat SPY;
- maximum favorable and adverse excursion;
- modeled costs and net returns;
- data and benchmark versions.

Signal accuracy is reported equal weighted. Portfolio P&L is additionally
reported using actual confidence-adjusted notionals, which makes it possible to
evaluate selection and sizing separately.

## 10. Dashboard information architecture

- Overview: last scans, health, qualified signals, equity curve, drawdown, and
  SPY comparison.
- Signals: all scored observations with filters for scan, horizon, decision,
  score, risk, and freshness.
- Signal detail: pillar contributions, raw inputs, news links, vetoes, strategy
  version, order, and observed outcomes.
- Paper portfolio: orders, fills, lots, realized/unrealized return, exposure,
  and contribution-matched benchmark attribution. Portfolio equity is the sum
  of open marked value and closed proceeds; each filled lot creates an
  equal-dollar SPY cohort so later capital contributions do not inflate
  apparent performance.
- Backtests: experiment comparison, walk-forward windows, score buckets,
  limitations, and reproducibility metadata.
- Operations: latest broker reconciliation and discrepancies, account state,
  job history, provider usage, stale data, failures, and retries.

## 11. Implementation milestones

1. Foundation: strategy contract, schema, migrations, score/sizing core, tests.
2. Data: Alpaca/SEC clients, universe snapshots, immutable price store, data
   validation, and provider fixtures.
3. Research: point-in-time features, backtester, outcome engine, and reports.
4. Automation: exchange calendar, dispatcher, scan orchestration, and paper-only
   Alpaca reconciliation.
5. Dashboard: server-backed APIs and the six dashboard views.
6. Deployment: systemd units, secrets, backups, health checks, and restore test.
7. Calibration: freeze v1, collect forward results, and review after the first
   complete 105-trading-day cohort.

## 12. Promotion gates

No strategy may be described as successful merely because a backtest is
profitable. Promotion from heuristic observation to automated paper execution
requires reproducible tests, an untouched test-period report, documented costs,
and explicit limitations. Live-money execution is outside v1 and requires a
separate design and explicit authorization.
