# Stock Watch Worker

The worker owns durable ingestion, research, scanning, scoring, backtesting,
and paper-order orchestration. The Next.js application remains the dashboard.

The implemented research foundation includes the dependency-free score/sizing
and outcome core, injectable Alpaca and SEC clients, versioned universe imports,
immutable compressed raw-data storage, point-in-time technical and SEC
fundamental features, and cost-aware close-signal backtesting. Backtests use
chronological walk-forward splits and are recorded with immutable strategy,
dataset, feature, and universe versions.

Opening-scan backtests are intentionally deferred until timestamped intraday
history is available. Reusing a daily close in a simulated 09:45 scan would
introduce lookahead bias.

Exchange-calendar dispatch and durable job leasing are now implemented. The
dispatcher uses Alpaca's market calendar, including early closes and DST, and
only catches up missed windows for a bounded 20-minute interval. Job execution
supports atomic claims, worker heartbeats, delayed retries, and stale-lease
recovery.

Paper-order intent and reconciliation are also implemented. An immutable intent
is committed before the network request, and each retry first looks up the
deterministic Alpaca client order ID. Orders require an explicitly `paper`
strategy plus an active, fractional asset. The $30 open-notional-per-ticker and
one-lot-per-ticker/horizon limits are checked again immediately before intent
creation.

Full scan execution is now implemented. A durable scan job collects adjusted
daily IEX bars, Alpaca news, and fractional eligibility; loads the latest
point-in-time SEC cache; constructs immutable features; persists a signal for
every configured horizon; and routes qualified paper strategies through the
order lifecycle. Provider responses are written to the immutable raw store
before transformation.

SEC CompanyFacts refresh runs separately from the time-sensitive market scans.
This avoids delaying the opening scan while the SEC client processes hundreds
of issuers under its enforced request-rate limit. Cached documents can contain
newer facts because the extractor independently filters every fact by its SEC
`filed` date at the signal cutoff.

The server-backed dashboard APIs and hardened systemd deployment units are
implemented. See `../deploy/README.md` for the `a1347-j` installation and
restore checklist.

## Dashboard connection

The Next.js server reads the worker SQLite database using Node's built-in
SQLite driver in read-only, query-only mode. Node 22.13 or newer is required.
Point the application at an initialized worker database before starting it:

```bash
export STOCK_WATCH_DATABASE_PATH="/var/lib/stock-watch/stock-watch.db"
npm run build
npm start
```

The overview, signals, portfolio, backtest, and operations pages use the
`/api/dashboard/*` routes. If the environment variable is absent or the file
does not exist, the dashboard displays a setup state and does not create or
modify a database.

## Backtest contract

- A completed closing signal enters at the next available session open.
- The entry session counts as holding day one; the configured horizon exits at
  that session's close.
- SPY uses the identical entry and exit sessions.
- Returns and P&L include configurable round-trip costs.
- Overlapping positions for the same ticker, horizon, and strategy are rejected.
- Concurrent open notional is capped at $30 per ticker across horizons.
- Aggregate capital is unlimited during initial calibration: every accepted
  confidence-sized $5-15 lot is independently funded.
- Missing symbol, future, or benchmark-boundary history is recorded as an
  explicit rejection rather than silently dropped.
- Train, validation, and test ranges are chronological; expanding and rolling
  walk-forward windows are supported.
- Complete input manifests are content-hashed, and identical strategy,
  universe, cost, feature, and dataset inputs reuse the same durable run.
- Untouched test trades report positive-return and beat-SPY rates with 95%
  Wilson intervals overall and by horizon/score cohort. Cohorts below the
  configured observation minimum remain explicitly underpowered.
- Validation threshold selection maximizes the equal-weight 95% Wilson lower
  bounds for those two success rates, while retaining raw point estimates in
  the audit record.
- Portfolio analytics compare the capital-weighted daily return of those fixed
  lots with equal-dollar SPY cohorts on identical entry and exit sessions. They
  report contribution return, excess P&L, drawdown, annualized return and
  volatility, Sharpe/Sortino, exposure, concurrency, and turnover. The model is
  explicitly unlimited external funding, not a self-financing cash portfolio.

The manifest format is documented in
[`../docs/backtest-dataset-v1.md`](../docs/backtest-dataset-v1.md).

Historical research can use complete long-form constituent snapshots through
`import-universe-history`. With `--point-in-time-universe`, both bar backfill
and manifest generation resolve the snapshot effective at each signal date;
the backtester verifies the embedded IDs and hashes against SQLite before
accepting the run. Fixed-current-universe research remains supported but is
explicitly labeled survivorship biased.

`backfill-news` provides a restart-safe historical Alpaca news ingestion using
bounded date windows and symbol chunks. A dataset uses that history only when
its succeeded ingestion ID and a succeeded `backfill-calendar` ingestion are
explicitly passed; otherwise the news pillar remains unavailable. Publication
timestamps are filtered at each provider-supplied session close, including DST
and early closes. The ingestion versions and cutoff policy are recorded in the
manifest.

## Provider environment

```bash
export ALPACA_API_KEY_ID="paper key id"
export ALPACA_API_SECRET_KEY="paper secret"
export SEC_USER_AGENT="Stock Watch monitored-email@example.com"
```

Only Alpaca paper credentials should be used. The order client rejects any base
URL other than `https://paper-api.alpaca.markets`.

## Local verification

Python 3.12 or newer is required, matching the version installed on `a1347-j`.

```bash
cd worker
python3.12 -m unittest discover -s tests -v
python3.12 -m stock_watch_worker.cli init-db --database /tmp/stock-watch.db
```

Set `PYTHONPATH=src` if the package has not been installed:

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
PYTHONPATH=src python3.12 -m stock_watch_worker.cli init-db \
  --database /tmp/stock-watch.db
```

Import an approved current S&P 500 CSV with a `symbol` or `ticker` column:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli import-universe \
  --database /tmp/stock-watch.db \
  --csv /path/to/sp500.csv \
  --effective-at 2026-08-20T20:00:00Z \
  --source "source name" \
  --source-url "https://source.example/list"
```

The CSV may include `Security`/`Name`, `Exchange`, and numeric `CIK` columns.
CIKs are stored with the universe snapshot so SEC fundamentals can be selected
without a symbol-to-company guess.

Refresh active/fractional eligibility for the latest universe snapshot:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli refresh-assets \
  --database /tmp/stock-watch.db
```

Refresh SEC CompanyFacts that are missing or more than 24 hours old:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli refresh-fundamentals \
  --database /tmp/stock-watch.db \
  --data-path /tmp/stock-watch-data
```

Run and persist a close-signal walk-forward backtest from a versioned,
point-in-time scored dataset:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli run-backtest \
  --database /tmp/stock-watch.db \
  --dataset /path/to/backtest-dataset.json \
  --strategy-id sp500-long-v0 \
  --universe-snapshot-id 1 \
  --round-trip-cost-bps 10 \
  --minimum-validation-trades 20 \
  --minimum-reliability-trades 30
```

The worker can first backfill adjusted Alpaca daily bars for a frozen universe
plus SPY, then build the scored manifest from stored bars and SEC CompanyFacts:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli backfill-bars \
  --database /tmp/stock-watch.db \
  --data-path /tmp/stock-watch-data \
  --universe-snapshot-id 1 \
  --start 2018-01-01 \
  --end 2026-08-20

PYTHONPATH=src python3.12 -m stock_watch_worker.cli build-backtest-dataset \
  --database /tmp/stock-watch.db \
  --output /tmp/sp500-close-backtest.json \
  --universe-snapshot-id 1 \
  --start 2019-01-01 \
  --end 2025-12-31
```

The builder defaults to one close signal every five sessions to keep an
initial all-S&P manifest bounded. Set `--signal-stride-sessions 1` for the exact
daily close strategy after checking the estimated signal count and available
memory. The bar backfill must extend at least 105 trading sessions beyond the
last requested signal date and include at least 260 prior sessions.

Run one dispatcher tick. This performs a read-only calendar request and creates
jobs only during the accepted scan grace window:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli dispatch-once \
  --database /tmp/stock-watch.db
```

Claim and process one durable job, including collection and paper-only broker
reconciliation when the referenced strategy has explicitly been promoted:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli work-once \
  --database /tmp/stock-watch.db \
  --data-path /tmp/stock-watch-data
```

Reconcile entry fills, calculate exchange-session exit targets, submit due
fractional paper sells, reconcile exit fills, and persist mature signal
outcomes against SPY. Each run also records an immutable portfolio snapshot
with actual contributed capital, realized/unrealized P&L, and a
contribution-matched SPY value. Before completing, it captures the Alpaca paper
account, positions, and non-trade activities and compares broker quantities
with the sum of open strategy lots:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli maintain-paper \
  --database /tmp/stock-watch.db \
  --data-path /tmp/stock-watch-data
```

Forward outcomes use the next session's open through the configured horizon's
close for both opening and closing signals. This avoids assigning the already
elapsed 09:30 open to a 09:45 signal. Actual paper fills and realized returns
are tracked separately from these standardized signal-quality outcomes. The
portfolio benchmark creates a SPY cohort for each actual filled lot using the
same capital contribution and exit fraction, preventing new $5-15 entries from
being mistaken for investment returns.

New entries fail closed unless the latest broker reconciliation is `matched`
and was captured no earlier than the signal's data cutoff. Every paper scan
performs this capture immediately before scoring and order routing.
Unexpected/manual positions, quantity drift, non-active accounts, or account
trading restrictions block entry creation. Dividend and corporate-action
activities are retained as evidence for discrepancies; v1 does not silently
rewrite lot quantities after a split. A dedicated Alpaca paper account is
therefore required. Dividend cash is not yet attributed to individual lots, so
portfolio snapshots remain research/calibration records rather than an
authoritative brokerage statement.

The checked-in `sp500-long-v0` strategy remains in `development`. It records
signals but cannot create paper-order intents until a deliberate promotion step
creates a new durable paper strategy version. Promotion never mutates the
reviewed source version and requires the new ID to be repeated explicitly:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli promote-strategy \
  --database /tmp/stock-watch.db \
  --source-strategy-id sp500-long-v0 \
  --paper-strategy-id sp500-long-paper-v1 \
  --confirm-paper-trading sp500-long-paper-v1
```

Scheduled deployment selects the result through `STOCK_WATCH_STRATEGY_ID`.
The promotion validates the source configuration hash, timestamps the paper
clone, and records an atomic audit event. Identical retries are safe.

Before scheduled automation is enabled, `deployment-check` fails closed unless
the selected immutable strategy is hash-valid, the latest S&P 500 snapshot has
at least 450 members, and at least 95% of members have both CIK and Alpaca asset
metadata coverage:

```bash
PYTHONPATH=src python3.12 -m stock_watch_worker.cli deployment-check \
  --database /tmp/stock-watch.db \
  --strategy-id sp500-long-v0
```

The implementation is paper-only by design. Live brokerage endpoints are not
accepted by the worker configuration.
