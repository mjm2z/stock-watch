# Systems and Bitcoin release

This release adds paper-only Bitcoin, watch-only blockchain monitoring, and
versioned rule systems for stocks and BTC/USD. The stock scanner, existing lots,
SPY cohort reports, and independent five-minute-before-close exit timer retain
their behavior until a replacement stock system passes explicit activation.

## Status and boundaries

The implementation is opt-in. Installing code does not activate a strategy.
Stock systems need 20 observed market sessions and Bitcoin needs 30 distinct UTC
observation days, recent observations, a completed walk-forward run, exact-ID
confirmation, and account checks. These are operational prerequisites, not proof
of a profitable edge. Parameter changes create immutable versions; no strategy
is automatically promoted. Four simultaneous shadow versions per asset are
allowed through the dashboard.

A separate Alpaca **paper** account with exactly $300 cash, no holdings, and no
open orders is required for Bitcoin activation. The same stock API key is rejected.
All execution URLs are fixed to the paper API. No transfers, signing, private
keys, leverage, shorting, or paid data subscriptions are introduced.

The new broker flows have deterministic client order IDs, durable intents,
partial-fill reconciliation, explicit failed-command history, and an account
identity check on every tick. Fee activities adjust expected BTC quantities.
Unexplained quantity or cash changes block new entries. A 10% drawdown breach
uses conservative modeled equity, cancels entries, attempts exits, and pauses.
A pause can attempt owned-position exits even if entry quotes are unavailable.
Residual balances below the broker's minimum require operator review. Drawdown
thresholds are triggers, not guaranteed fill prices.

Stock activation takes an account-wide cutover lock, requires legacy entries and
broker orders to settle, and disables future legacy entries. Existing stock lots
continue their original exits. Expected broker holdings include both ledgers.
New entries respect shared cash, $300 portfolio, $60 sector, $30 ticker, and
$5–15 order limits. Daily rules enter in the 09:45–10:00 Eastern window and exit
five minutes before the next applicable close, including early closes. Pausing
requests exits during an open session. Pausing does not reactivate legacy entries.
Another stock system cannot replace outstanding positions from a prior system.

## Operator workflow and UI

The Stocks/Bitcoin switch encodes context in URLs. `/` and all existing stock
routes remain available. Systems occupies the old Backtests navigation slot;
`/backtests` still shows legacy experiments. `/systems?asset=bitcoin` contains
Bitcoin versions, jobs, comparisons, observations, and activation commands.
`/bitcoin?view=paper` separates broker fills from modeled performance;
`/bitcoin?view=blockchain` manages public-address watches.

Writes require a configured random `SYSTEMS_OPERATOR_TOKEN` of at least 32
characters and a one-hour signed HttpOnly, SameSite=Strict operator session.
Cookies are Secure when accessed through HTTPS. Origin checks and bounded JSON
bodies protect mutations. The existing trusted-LAN read-access model is unchanged;
use HTTPS for operator login outside a locally trusted connection. Tokens and
broker credentials stay in protected host configuration, never in source control.

Typical workflow: select a template, record its hypothesis, save its bounded
parameters, choose an imported dataset, queue a backtest, compare results, start
shadow observations, and submit the deployment ID for activation checks. A
failed activation remains visible with its reason. Pausing and restarting are
also explicit, audited commands. Restart does not erase the equity high-water
mark; an account still below its risk threshold cannot resume the same risk epoch.

## Dataset and evaluation contract

`stock-watch-systems` is a second CLI; it never dispatches legacy scans. All
commands take `--database PATH` **before** the subcommand. Examples:

```sh
stock-watch-systems --database /var/lib/stock-watch/stock-watch.db init
stock-watch-systems --database /var/lib/stock-watch/stock-watch.db build-dataset \
  --asset stocks --storage /var/lib/stock-watch/data/systems
stock-watch-systems --database /var/lib/stock-watch/stock-watch.db build-dataset \
  --asset bitcoin --start 2022-01-01T00:00:00Z --end 2026-09-01T00:00:00Z \
  --storage /var/lib/stock-watch/data/systems
stock-watch-systems --database /var/lib/stock-watch/stock-watch.db import-dataset \
  /path/to/verified.json --storage /var/lib/stock-watch/data/systems
stock-watch-systems --database /var/lib/stock-watch/stock-watch.db run-next
```

The Bitcoin builder audits the returned range, paginates Alpaca's hourly endpoint,
and can use existing stock credentials for **read-only data**. It does not claim
the requested range was available. The stock builder uses captured daily bars,
sectors, and the stored exchange calendar. Both builders explicitly mark execution
as approximate. Stock exports also flag current-universe survivorship bias and
unverified corporate-action coverage. An approximate dataset is useful for
screening hypotheses, not a reproduction of executable historical prices.

The JSON contract is `schema_version: 1`, `asset: stocks|bitcoin`, a `manifest`
with `provider`, `venue`, and `fidelity`, and chronological `bars`. Each bar has:

- `symbol`, UTC `at` (decision time), `available_at`, positive OHLC values.
- Stock `sector`; `eligible` gives membership eligibility at that time.
- Optional `quote: {at,bid,ask,ask_size?,bid_size?,synthetic?}` strictly after the
  signal. Stocks may supply a separate `exit_quote` for their near-close exit.
- Missing execution quotes skip execution and produce an explicit warning.

Optional inputs: `risk_quotes` with chronological UTC `at,bid,ask` for minute
risk replay; `benchmarks` mapping names to ordered `{at,close}` observations (or
`total_return_index`); `corporate_actions` containing splits (`symbol,at,
available_at,ratio`) or cash dividends (`symbol,at,available_at,amount,pay_at`).
Dividend `at` is the ex-date entitlement instant; payment cash is unavailable
until `pay_at`. Splits adjust owned quantities and the rule's historical prices.
The importing researcher must verify source revision timing, action completeness,
and membership provenance; a manifest assertion alone is not independent proof.

Replay has a closed $300 cash pool, shared exposure limits, fractional precision,
quote-size partial fills when sizes exist, fee/slippage stress, and portfolio
marking. Bitcoin buy fees reduce credited BTC. Raw bar execution without quote
sizes does not model queue priority or market impact. Missing hourly bars reset
indicators. Hourly-only data cannot validate minute-by-minute drawdown controls.
Real quotes covering the intended stock timestamps are needed to reproduce
09:45 and five-minute-before-close execution; daily open/close proxies are labeled.

Evaluation freezes the chosen rules: 24 months training, six validation, three
testing, three-month steps. The latest six months are sealed when enough history
exists (at least 39 months for one complete fold). Insufficient history is labeled;
no shortened fold is passed off as the specified test. No automatic parameter
optimizer is included. Every manually chosen version and run remains auditable.
Fold simulations start flat; chained fold returns are not one continuous live
portfolio. The headline research interval and out-of-sample summaries are separate.
A 30-trade warning is a minimum sample warning, not a statistical independence claim.

Imported datasets and full result artifacts are content-addressed/hashed on disk;
small result summaries, downsampled charts, and the last 100 fills are kept in the
operational database. Exact full evidence is in `<run-id>.result.json` beside the
dataset. The worker verifies dataset/config hashes before running. One job runs
at a time, can be canceled, and a process lock prevents duplicate local workers.
Interrupted jobs become failed on restart; they must be queued again explicitly.

## Blockchain observations

mempool.space is the sole address provider. Requests expose watched addresses to
that provider; labels stay local. Up to 20 checksum-validated mainnet addresses
are supported. Seeds, private keys, xpubs, and testnet are rejected. Balances are
integer-satoshi provider observations, not paper holdings or full wallet balances.

The collector saves chain-tip/block identity, congestion, fees, address indexing
progress, and transactions. It paginates incrementally, deduplicates transactions,
rechecks recent confirmations, detects replaced chain tips, and backs off on
failures. Historical transaction timestamps are not used as historical feature
availability times. Observations are timestamped when seen and retained for
future point-in-time research. No blockchain feature drives orders in this release.

## Installation and rollback

The authoritative application host is now a1347-m (192.168.4.35). The completed
host migration is recorded in `deploy/MIGRATION-a1347-m.md`; do not deploy to
the retired a1347-j StockWatch runtime.

The reviewed release is built and tested in a separate directory under
`/home/mjm2z/stock-watch-releases`. `deploy/install-reviewed-release.py` verifies
its manifest, stops schedules and drains running jobs, creates and verifies a
fresh database backup, retains the full previous runtime and protected config,
then installs the prebuilt application and additive migration 016. It preserves
existing unit definitions and restores only their previously enabled timers.
It installs the independent research, stock-shadow, and watch-only Bitcoin units.
Neither new trading timer is enabled and no strategy is activated.

The installer generates a private operator token when the template is empty.
The token stays in `/etc/stock-watch/systems.env`; it is never printed or committed.
The release receipt in `/opt/stock-watch/installed-release.json` identifies the
revision and retained recovery locations. If installation fails, leave writers
stopped and inspect that recovery directory before restoring the prior runtime;
never replace the authoritative database with a stale migration export.

Populate `/etc/stock-watch/systems.env` using `deploy/systems.env.example`, with
mode 0600 and root ownership. Restart the web service for operator sign-in. Once
Bitcoin data credentials are configured, enable `stock-watch-bitcoin-trading.timer`
to collect prices and execute shadow ticks. Without an activated paper deployment
it cannot place orders. Enable `stock-watch-systems-stocks.timer` for reviewed stock
activation commands. Existing stock timers keep their previous enabled state.

The backtest service has one CPU, 768 MB RAM, low I/O priority, and a one-hour
execution bound. Other new services are isolated with their own timeouts and
memory caps. Inspect their systemd journals plus the UI's durable errors.

To roll back before activation, disable new timers and restore previous application
files; additive tables can remain. After activation, first pause and reconcile all
system-owned orders/positions. Do not remove the ownership bridge or delete the
cutover row while system positions exist. Restoring legacy entry authority requires
an explicit reviewed operational change, not merely restarting an old binary.

## Local verification

Verified with Python 3.12 worker tests, Jest frontend/API-store tests, TypeScript,
the production Next build, and headless Chromium at 390px and 1365px widths.
The browser preview used an isolated `/tmp` database, not production data.
Regression cases include stock entry-authority cutover, shared cash/sector limits,
late data, duplicate records, fee quantities, partial fills, split/dividend
accounting, minute risk exits, stale quote feeds, uncertain submission recovery,
reorg detection, public-provider backoff, operator sessions, and asset isolation.
The public mempool fee endpoint was also checked successfully. These checks do
not establish broker-specific fill quality or strategy profitability; those
require the configured paper account and forward observation period.
