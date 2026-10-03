# StockWatch

As verified on **October 2, 2026 at 22:33 Eastern**, production on a1347-m runs
SEC company-information release **`67e2ba9`**, installed at 20:01 Eastern with
migration **025** and the company-context timer enabled. Web, feed, execution and
manual-paper services were active; feed, execution and notification checks passed.
The verified recovery snapshot is `/var/backups/stock-watch-releases/20261002T224616Z`.

The next source change adds inline SEC filing excerpts, exact-accession financial
facts, hidden vertical scrollbar tracks and a reviewed port-free routing helper.
**These additions require a new application installation and a separate proxy
activation; they are not yet verified live.** See [inline filings and LAN routing](docs/inline-filings-and-routing.md).

Completed cleanup reclaimed about **201 GiB** from old builds, abandoned backups
and redundant recovery databases. Storage maintenance subsequently reduced the
main database from **48.01 GB to 3.84 GB**, preserving 11,569 observations backed
by 681 unique CompanyFacts bodies. A fresh recovery backup was retained; the host
reported about **252 GiB available** after installation. All four core services
were active, and feed, execution and notification health checks passed. General
health remains degraded by a pre-maintenance Alpaca calendar timeout and an older
scanner operation with a stale heartbeat; broker reconciliation is matched. These
scanner warnings remain follow-up work, not a failed storage installation.

Manual account credentials, Telegram authorization and combined-account setup are
confirmed. End-to-end paper order/fill and Telegram trade-notification delivery
tests remain outstanding; no UI verification implicitly authorizes a test trade.
Historical deployment evidence, including HomeOps and JobWatch changes, remains in
the [dated release report](docs/next-phase-release.md). Prior healthy checks are
observations at their recorded times, not a claim of continuous current health.

StockWatch is a local research and **paper trading** application for US stocks,
ETFs and BTC/USD. It combines instrument charts, immutable rule-based systems,
historical research, forward observations, separate manual allocations, and
broker reconciliation. It does not enable real-money trading, leverage, short
sales, options, or automatic account resets.

The application runs on **a1347-m, port 3001**. Coinbase observations, execution,
manual paper instructions and web requests have separate process boundaries.
**a1347-j is the independent watchdog**, not a second execution host.
[Autobot](https://github.com/mjm2z/autobot) is the Telegram interface; StockWatch
owns trading validation, reservations, order intent and accounting.

## Source, verification and installation are different

The installed application includes the manual paper ticket, instrument charts,
system research and backtesting, activity records, and matching app/favicon artwork.
Migrations through SEC company context **025** are installed; filing-details migration **026** is pending installation. A build, fixture test or screenshot establishes
source behavior, not installation or broker connectivity.

Current setup instructions are here and in the linked guides. Dated release reports
retain historical evidence; the [archived README](docs/readme-history-before-next-phase.md)
is not a current deployment instruction. Verify the installed receipt and health
before marking a staged capability operational.

The operator created one dedicated Alpaca paper account with **$1,000,000
simulated cash**. The provisioning helper verified its identity differs from both
automated accounts, and the operator confirmed the combined setup through
Telegram. Initial cash reconciled with no positions or reservations. StockWatch
allocates **$1,000 to manual stocks and
$1,000 to manual Bitcoin**, with a **$100 entry cap including a 1% fee allowance**.
The broker's larger cash balance does not enlarge either application budget.
Code can be deployed while manual trading remains visibly **unconfigured**.

## Find your way around

Choose **Stocks** or **Crypto** in the sidebar. Navigation retains the selected
asset where the view supports it.

| View | What it answers |
| --- | --- |
| Overview | Instrument history, performance scope, current sources and operating status |
| Paper trading | Manual orders and instructions; automated portfolios; scanner paper trades |
| Systems | Edit rules, inspect a draft, publish an immutable version and inspect actual authority |
| Backtesting | Historical runs, research snapshots, experiment plans, comparisons and reviews |
| Activity | What changed, when, for which account/system, and the retained event evidence |
| Signals / Research | Scanner output and contextual research, separate from execution authority |
| Operations | Data capabilities, jobs, reconciliation, feed/owner/notification health and blockers |

An operator session is required for mutations. Reading charts or changing layer
visibility does not publish, enroll, authorize, pause, amend or cancel anything.
Research cancellation affects research only. Submitted, filled, qualified and
authorized are different states.

## Paper trading: Stocks and Bitcoin

Open **Paper trading → Manual allocation**. The ticket identifies the allocation,
remaining unreserved cash, session, symbol, side, order type and time in force.
Stocks and Bitcoin use the same dedicated broker account but separate durable
budgets and position attribution. Automated balances and positions cannot be
spent or sold from the manual ticket.

| Instruction | Stocks | Bitcoin | Sizing / important behavior |
| --- | --- | --- | --- |
| Limit (default) | DAY; whole shares may use GTC | GTC or IOC | Quantity and explicit maximum buy/minimum sell price |
| Market buy | Fractionable asset, DAY, regular session | GTC or IOC | Dollar notional only; fee allowance must fit the $100 cap |
| Market sell | Owned quantity; fractional DAY | Owned quantity, GTC or IOC | No guaranteed price; no shorting |
| Stop-limit | DAY; whole shares may use GTC | GTC only | Explicit stop and limit; activation is not a guaranteed fill |
| Stop-market exit | Stock sells only | Unsupported | Owned quantity; buy stops use stop-limit instead |
| Local above/below | Limit instruction, regular-session evaluation | Limit instruction using fresh Coinbase trigger observations | Host required; fresh Alpaca execution validation; 0.5% maximum buy allowance above trigger |
| Protective exit plan | Actual attributable entry fills | Actual attributable entry fills | Optional stop-loss/take-profit, locally managed; not broker-atomic OCO |

Fractional stock orders require current broker `fractionable` eligibility and
DAY. The UI and backend share a capability document; unsupported combinations
are rejected, not silently converted. This is a conservative application subset
of [Alpaca fractional trading](https://docs.alpaca.markets/us/docs/fractional-trading)
and [crypto orders](https://docs.alpaca.markets/us/docs/crypto-orders).
Extended hours, broker bracket/OCO and trailing orders are outside this release.

### Preview, then confirm

1. Select the allocation and complete the ticket. For example, a $50 market buy
   reserves $50.50 including the fee allowance; it does not promise a quantity.
2. Click **Preview order**. Inspect account identity, type, quantity/notional,
   price, timing, reservation and any already-satisfied trigger condition.
3. Confirm the exact preview within two minutes. Changing the form invalidates
   its displayed preview. A confirmation binds draft revision, user and chat and
   can be used only once.
4. Follow the instruction through intent/armed, submission, broker state and
   cumulative fills. Inspect an instruction to request cancellation or attach
   a protective plan. Cancellation is a request until reconciled.

The server rechecks identity, eligibility, ownership, quotes and reservations.
Network requests occur outside manual SQLite write locks; a transactional state
revision rejects validation that raced with a reservation or account change.
The worker persists intent before POST and uses a stable client-order ID. An
uncertain submission retains its reservation and is looked up; it is never
blindly reposted. A stock market instruction that misses the regular session
before dispatch is rejected locally instead of waiting to become tomorrow's
market order.

Local entries expire after 24 hours by default. Protective plans continue until
the position closes or the user explicitly cancels the plan. Fractional stock
protective exits use actual filled quantity and DAY; expired children reconcile
before replacements. Broker-held limits may continue during a StockWatch outage;
local triggers and protective plans need the host online.

Manual broker P&L is labelled as **combined-account reconciliation**. Prospective allocation
returns use each $1,000 budget and retain minute valuations with observed drawdown.
They are not calculated against the $1,000,000 broker balance. Missing fee,
cash-flow or position evidence is unavailable, not zero. Complete tax-lot
realized P&L and funding-matched allocation benchmarks remain limitations.

## Charts and live BTC

The Stocks overview starts with a searchable chart. Search by company name or ticker;
select a result (or submit an exact matching ticker) to add it. Up to **five symbols
including SPY** can be selected. The list above the chart is also the color legend:
spinners identify individual history requests and the × buttons remove symbols.
Selections are saved in this browser, independently of the research watchlist.

A single stock supports candles, hollow candles, lines, and OHLC bars. Adding another
stock switches to colored lines and initially selects percentage comparison; the
**$ / %** control switches between actual adjusted prices and percentage change.
Explicit scale choices are retained while the page is open. Percentage comparisons
start at the first shared observed timestamp; the baseline stays fixed while loading
older data within the navigation session. Missing observations are not invented.
Removing stocks leaves the line style selected. Volume is hidden when entering a
multi-stock comparison; Show volume exposes separately labelled volume panes.

The installed chart-control refinement (`7563c75`) passed local/browser and Linux
staging verification. Its reviewed stage is
`/home/mjm2z/stock-watch-releases/7563c751b286`:
Show volume / Hide volume use plain green text in either state; Crypto places its
style selector and Reset view below the ranges, matching Stocks. History feedback
uses a fixed-height right-aligned area so errors do not move the plot. A pending or
failed request pauses minute-window refresh; interrupted Bitcoin collection gets
one automatic retry before requiring Retry. Existing bars stay visible. TradingView
attribution moves from individual charts to a single app-footer link.

The **Company information** release `67e2ba9` is installed from its reviewed
stage at `/home/mjm2z/stock-watch-releases/67e2ba9211a0`. It follows chart selections and shows SEC filings, annual reported
financials with source links, and earnings-related 8-K disclosures. Funds use an
issuer-filings view without corporate earnings metrics. Collection is asynchronous,
with bounded storage and reuse of existing SEC facts; it cannot submit trades or
change research qualification. See the [SEC company information guide](docs/sec-company-information.md)
for exact coverage, freshness, limitations, worker operation and rollout.

Stock ranges include 6M, 5Y, 10Y and 30Y. These are requested windows, not promises of
provider coverage. Only returned bars are plotted; partial-history notices identify
limited coverage. Daily requests are bounded to 12,000 bars and finer resolutions to
6,000. The overview requires verified adjusted Alpaca history; it will not relabel
provider-defined fallback prices as adjusted. Custom dates open a floating calendar
panel. Both selected dates are included; the API receives UTC boundaries with an
exclusive end, capped at now for today. Apply commits the range; Cancel leaves it alone.

Overview charts omit order ownership, simulated overlays, and the detailed data table.
Their removal does not cancel orders, alter systems, or delete evidence. Other trading
and research workspaces remain available for those records. Raw broker price levels
are not drawn against adjusted stock prices. Chart controls use the same styling in
Stocks and Crypto; dropdown arrows have consistent inset spacing throughout the app.

Market prices appear immediately below the Stocks chart. Execution monitoring and
paper performance share the next row. Performance keeps **Automated stocks** and the
**Manual stocks allocation** separate: equity, return, observed drawdown and as-of time.
The manual row uses its allocation valuation, never the combined broker account's
$1,000,000 balance. These summaries refresh every minute. Scanner fill-cohort cards and
highest-ranked signals are hidden on Overview; historical calculations and records are
retained. Research coverage sits beside Recent scans on wide screens and stacks on mobile.

The Crypto header contains a compact **BTC/USD** Coinbase badge. Its green Live status
requires a fresh feed; disconnects retain the last price with Stale/Reconnecting status.
It still consumes the event stream without adding display polling or throttling.
Historical candles remain separate Alpaca data. Source details are available on the
badge tooltip/accessibility label. The sidebar uses the same green arrow artwork as the
favicon with a versioned URL so a cached older icon cannot survive a new page load.

The selected-stock legend grows horizontally in a fixed-height row (scrollable on
narrow screens), so adding tickers does not push the chart down. Stock resolution
is chosen automatically from the range; the style selector and Reset view share
one toolbar row. Research coverage is always expanded, with an external heading
aligned with Recent scans. The compact Bitcoin badge places BTC/USD and feed status
on its top row and the larger, left-aligned price immediately below.

### Expanding chart history

Pan or zoom beyond loaded history to request older/newer adjacent intervals after
200ms of interaction quiet. The chart retains its prices and viewport while a small
corner spinner says **Loading history…**. Duplicate requests share work; abandoned
requests are canceled. Different resolutions replace the window instead of mixing
candles, and larger intervals automatically use coarser bars. Overview navigation
shows **Custom view**; Reset view restores the selected preset. Explicit custom
calendar intervals stay bounded until another range is selected. Empty intervals
stop repeat requests and show a coverage notice; failures provide Retry.

These history requests do not throttle the Coinbase Live badge. Coinbase Advanced
Trade `ticker` and `heartbeats` flow through the separate collector and SSE proxy;
each distinct received price is published without application display debounce.
Screen readers are not interrupted on every tick.

Stocks display history is cached in memory: 64 MiB server-side and a shared 16 MiB,
32-entry browser LRU. Crypto response payloads are disposable database cache entries,
retained for at most two days with a 64 MiB logical payload cap. Expired/oversized
entries are evicted during reads/writes. Raw chart bars are much smaller than SEC
CompanyFacts documents; 6,000 JSON bars at 100–200 bytes each are approximately
0.6–1.2 MB before overhead. This is an illustration, not a production measurement.
Cache deletion frees reusable SQLite pages; it does not itself shrink the file.
Research datasets, execution observations and audit evidence are outside this policy.

The updated interface uses restrained green actions, selections and focus rings in
both themes, with neutral backgrounds. Profit/loss and warning colors keep their
meaning; comparison series retain distinct colors. Crypto Overview omits the system
research teaser and setup promotion; those workflows remain in Systems/Backtesting
and Paper trading. Network conditions is a compact three-metric research card.

Coinbase observations are venue-specific. **Alpaca remains authoritative for
executable quotes, orders, balances, fills and fees.** Coinbase ticks are not
spliced into Alpaca historical candles. Heartbeat age over three seconds,
observation age over five seconds, invalid data or discontinuities make the feed
unavailable for new dependent triggers. Reconciliation, authorized exits and
holding deadlines continue through periodic Alpaca checks during feed outages.
No Coinbase-price fill or guaranteed latency is promised.

## Systems: inspect before publication

The visual editor builds bounded ALL/ANY rule groups from supported prices,
volume, SMA, EMA, RSI, average volume and prior high/low operands. Stock decisions
remain daily; Bitcoin supports its existing minute-through-monthly timeframes.
A chart's display resolution does not change a system's decision cadence.

**Edit → Inspect → Historical preview → Evidence review → Publish immutable
version → Separately observe/authorize.**

Drafts use optimistic revisions: an old browser cannot overwrite a newer saved
draft silently. Inspection freezes a non-executable research snapshot and queues
bounded worker work over a selected retained dataset. It does **not** require a
version in the executable library. The same Python replay/rule evaluator supplies
rule truth values after completed-bar timing, gap resets and stock split treatment.
The UI shows true/false/unavailable, input values, completed bar, warmup history
and the next expected boundary where evidence supports it. These are simulated
rules on retained bars, not current live signals.

Historical preview freezes configuration, engine/data identity, interval, capital
and costs. Editing the draft or interval marks the displayed result outdated.
Metrics are calculated before sampling; complete content-addressed evidence is
available through a hash-verified download. Display curves retain at most 600
points and fill lists at most 200. Existing backtesting can prepare new research
data explicitly; editing a draft does not fetch years of prices.

Preflight separates basic inputs, warmup, scored coverage, fold feasibility,
data-treatment quality and execution authority. Basic stock inputs do not prove
historical membership or corporate-action coverage. Publication and completed
backtests never inherit preview authority because previews have none.

## Experiments and learning

Backtesting includes a research workspace for frozen baseline/candidate plans.
Create snapshots, then preregister the hypothesis, mechanism, primary outcome,
risk constraint, selection rule, review point, dataset, interval and optional
parent experiment. Queue the pair separately. Retain failed attempts, explicit
retries and cache reuse; cached results retain their original age and are not
new independent evidence.

Compare net return, drawdown, fees, exposure, turnover and trade coverage under
matching dataset, engine, period, timeframe, capital and cost assumptions. An
incompatible pair cannot produce a winner. Record a conclusion and next test
without granting order authority. Amend a plan through a linked new experiment;
review history is additive. The existing 100-scenario authorization stress
protocol is not 100 independent strategy trials.

Displayed intervals are recorded as inspected across the asset, conservatively
covering copied configurations and unknown legacy lineage. Subsequent selection
cannot call those intervals untouched holdouts. Continuous $1,000 replay is
shown separately from the existing $300 flat-start fold protocol. DSR/PBO,
calibrated probabilities and formal time-series uncertainty are unavailable
until their required selection/return inputs are supported.

A deterministic example compares daily BTC breakout entry 55 / exit 20 with
entry 55 / exit 10; all other configuration is identical. Its criteria are frozen
before the replay. The fixture is conspicuously labelled **demonstration, not
investment evidence**, with a blocked real-data plan. It never creates executable
versions or enrollments. ATR and relative-strength hypotheses are inventoried in
the research guide; this release adds no paid data or broad optimizer.

## Signals and scanner records

Research coverage links open the Signal ledger with the exact scan and rejection
reason. A loading shell appears immediately. Database reads execute in a bounded
two-worker pool, identical requests share work, and results use an 8 MiB/64-entry,
15-second cache. The page selects signal IDs before enriching the 50-row page;
scan-scoped reason options avoid unrelated ledger scans. The new scan/rank index
requires migration 024. Cold reads have a 15-second deadline and surface unavailable
states rather than blocking web health checks. Local fixture timings are recorded
in the release report; production cold latency is not yet measured.

**Scanner paper trades** are positions created by the earlier scheduled stock
scanner, with their own attribution and exit policies. They remain managed and
are not obsolete just because newer Systems workspaces exist. **Browser simulator ·
This device only** is a separate local sandbox, not the configured Alpaca account.
Older evaluations retain explicit methodology/freshness warnings. Fill-cohort
returns exclude idle cash and must not be presented as whole-account performance.
No records, scanner services or existing exits were removed by this UI release.

## Activity, operations and recovery

Activity records future instruction/order state transitions with stable IDs,
ownership, source timestamps and retained evidence. Filter by asset, scope,
symbol, account, owner, event, status and dates; cursor pages default to 50 and
cap at 200. Original ledgers retain older fills; the new table does not invent
historical transitions. Clicking chart events or table rows is read-only.

Operations separates data quality, research evidence, operational readiness and
execution authority. Feed, execution-owner and notification checks are independent.
“No qualifying decision” is not a worker failure. An unconfigured manual account
or Telegram token must not appear operational merely because code is installed.

Autobot's existing `/stockwatch` guided commands use the loopback scoped service.
It receives no broker credentials. Allowed Telegram user **and** chat IDs are
required. Browser operator authentication is separate. Existing commands and
system-control distinctions are documented in the [paper operations guide](docs/live-paper-operations.md):
exit permits the next new qualifying decision; exit-and-pause prevents new entries;
pause entries retains owned exit management. Existing Telegram parser capabilities
remain as documented there; the expanded browser ticket does not imply that all
new forms have new Telegram command syntax.

Notifications use a durable outbox. Partial fills aggregate, repeated outages
are suppressed, and uncertain sends are recorded rather than blindly repeated.
The digest defaults to 20:00 America/New_York. Report fallback sources are not
execution inputs. Manual-account setup and notification delivery must be verified
separately after protected configuration is supplied.

## Run and verify locally

Requires Node.js 22.13+ and Python 3.12+. Configure paths/tokens in protected
local environment files; never commit secrets. Keep fixture databases separate
from production data and do not run execution workers against real credentials
for UI checks.

```sh
npm ci
npm run dev                         # web on 3001
npm run type-check
npm run lint
npm test -- --runInBand
npm run test:feed
PYTHONPATH=worker/src python3.12 -m unittest discover -s worker/tests
npm run build
```

`app/icon.svg` is the canonical app mark. `python3 deploy/generate-icons.py`
(requires `rsvg-convert`) generates the matching ICO and Apple PNG variants.
The SVG, browser favicon and app brand must be reviewed together.

Deployment uses `deploy/stage-reviewed-release.sh` and the reviewed release
installer. Commit tested source first. Stage, build the wheel, verify the manifest
and run the read-only installer check before requesting root installation.
Back up before pending migrations, preserve artifact stores and manual ledgers, drain
the previous owner and reconcile outstanding orders during cutover. Never run a
second installer while a healthy backup/migration owns the release. Rolling back
code must not reset accounts, delete evidence, reactivate paused entries or start
a competing owner. Complete storage maintenance and verify its receipt/health before
installing this UI release. The installer refuses weekdays 09:30–16:00 Eastern.
Storage migration 023 needs a full verified backup and offline compaction and can
take hours. Older code requires its matching pre-migration database for rollback.
See [storage maintenance](docs/guide/storage.md#storage-maintenance).

`npm run dev`, `npm test` and `npm run build` compile the Signals read worker into
`.signal-worker/`. Include that generated directory in reviewed release artifacts;
do not start production from a source-only archive. It reads the configured
`STOCK_WATCH_DATABASE_PATH` without write access or broker requests.

## Technical and operational guides

- [Architecture and ownership](docs/guide/architecture.md)
- [Storage, provenance and bounded APIs](docs/guide/storage.md)
- [Market data, time and freshness](docs/guide/data-time.md)
- [Rules, drafts and preview semantics](docs/guide/rules-preview.md)
- [Research, comparisons and experiments](docs/guide/research.md)
- [Orders, allocations and accounting](docs/guide/orders-accounting.md)
- [UI, chart inspection and activity](docs/guide/ui-charts.md)
- [Runtime, deployment and recovery](docs/guide/runtime.md)
- [Existing live-paper operations and Telegram command reference](docs/live-paper-operations.md)
- [Correctness audit](docs/correctness-release-audit.md) and [stock evidence readiness](docs/stock-evidence-readiness.md)
- [Historical architecture and development notes](docs/readme-history-before-next-phase.md)
