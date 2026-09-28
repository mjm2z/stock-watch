# Live observations and manual paper operations

This document describes the September 2026 implementation. Installation, credential
provisioning, and confirmed paper trades are separate milestones. Consult the release
report for what actually ran: [September 28 release state](live-paper-release-2026-09-28.md).
Missing configuration never selects an automated account.

## Architecture and boundaries

- **a1347-m:** StockWatch web, Coinbase collector, Bitcoin execution coordinator, manual
  paper owner/API, and [Autobot](https://github.com/mjm2z/autobot).
- **a1347-j:** independent HomeOps watchdog. It remains outside the application host.
- `stock-watch-market-data.service`: Node public WebSocket collector; no trading
  credentials, account access, or broker order methods.
- `stock-watch-execution.service`: supervised Bitcoin coordinator using the existing
  durable `btc_orders`, allocation ownership, qualification gates, and risk thresholds.
- `stock-watch-manual-paper.service`: loopback API and one serialized executor for both
  distinct manual accounts. It owns `manual-paper.db`; automated ledgers stay separate.
- Existing stock scan/entry/exit services retain their current scheduling. This release
  does **not** consolidate those stock services into a new account-wide daemon.
- Next.js proxies public Coinbase snapshots/events. Browser mutations require the
  existing same-origin operator session and a separate browser service credential.
- Autobot understands structured commands only. It holds a scoped StockWatch token,
  never an Alpaca key. All previews, confirmations, reservations, and intents live in
  StockWatch, including Telegram user/chat attribution.

## Coinbase Live Price

The card above the historical Bitcoin chart connects to
`/api/crypto/live?stream=1`. The first SSE event is a current snapshot, followed by
immediate distinct price changes. There is no price polling, debounce, or display
throttling. Browser rendering remains frame-limited. Numeric dimensions are stable,
changes use a fixed-width arrow, and the price is not an ARIA live region. There are
no animations, including under reduced-motion preferences. Historical chart controls
and Alpaca candle labels remain separate.

The upstream is `wss://advanced-trade-ws.coinbase.com`, subscribed separately to
public `ticker` and `heartbeats` for `BTC-USD`. `ticker_batch` is not used. Coinbase
can batch cascading matches; this is every distinct received price, not a promise
of every underlying exchange trade. See [Coinbase endpoints](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-endpoints).

Each event includes an ID, connection generation, Coinbase timestamp, local receipt
milliseconds, heartbeat timestamp, source age, and freshness/status. Live protocol
inspection confirmed that sequence numbers advance across the entire connection,
including subscription acknowledgements. Gaps, repeats, regressions, invalid prices,
and invalid timestamps make the feed unavailable and cause a fresh subscription.
Heartbeats older than three seconds and observations older than five seconds are
unavailable to new event-dependent triggers. Disconnects retain the last price with
Reconnecting/Stale; an Alpaca fallback is never labelled Coinbase.

Reconnect uses capped exponential delay with jitter. A new generation must receive
fresh data and heartbeats before becoming live. SSE clients receive snapshots rather
than tick replay. The collector allows at most 128 clients; a client with more than
64 KiB queued is disconnected to bound memory and receives a fresh snapshot when it
reconnects. The loopback listener is fixed to `127.0.0.1:3012`.

`market-data.db` is separate from the application database. It retains 90 days of
minute OHLC aggregates and seven days of one diagnostic row per minute. It does not
store raw ticks. Active order audit records retain the associated observation and
Alpaca quote independently of feed retention. Minute diagnostics are sampled; they
are not a complete latency distribution.

A read-only 12-second verification on September 28 recorded 27 fresh events in one
connection generation. First/last sampled source ages were 90 ms and 3 ms. These
samples are not latency guarantees, and they do not measure order execution.

## Execution and recovery

Coinbase is an observation/trigger venue. Alpaca is authoritative for executable
quotes, account identity, balances, orders, fills, and fees. No Coinbase-price fill
is implied.

The Bitcoin daemon holds the same process lock as legacy Bitcoin CLI execution.
Feed changes wake exit evaluation, coalesced to at most one evaluation per two
seconds. Completed-bar strategy decisions remain scheduled separately, approximately
30 seconds apart. A ten-second periodic path continues during feed outages;
authorized exits, reconciliation, and holding deadlines do not require Coinbase.
Price risk checks use Alpaca quotes at most five seconds old. HTTP delays and broker
rate limits can extend every interval.

Order intent precedes submission; broker client IDs remain stable. Existing Bitcoin
reconciliation retains its established lookup-before-retry behavior. Manual orders
are even more conservative: after an uncertain POST, a missing lookup does not
prove rejection. They retain cash/quantity reservations and require reconciliation;
the owner does not blindly repost. Canceling an uncertain instruction preserves its
reservation until the broker outcome is known.

Manual audit records distinguish source-event age, receipt-to-dispatch delay,
trigger-to-dispatch processing, and broker acknowledgement. System observations
retain source/receipt and dispatch timestamps. Broker acknowledgements are not fills.

The installer drains the previous timer owner before replacing an enabled Bitcoin
coordinator timer. It refuses a cutover with a competing enabled legacy Bitcoin
trading timer. It does not start execution where the coordinator was disabled.
Continuous services are stopped before consistent backups; timers are restored
except for the replaced coordinator. Rollback must stop the new daemon before
restoring a legacy timer. Never enable both owners. Never restore an old database
over newly accumulated fills.

## Manual account setup

Provision two fresh **Alpaca paper** accounts, one for stocks and one for Bitcoin.
Alpaca [documents](https://docs.alpaca.markets/us/docs/paper-trading) a $100,000
default for new paper accounts. If its creation form offers a $1,000 starting
balance, that is also supported. StockWatch
confirms a separate **$1,000 virtual allocation per account**, with a **$100 entry cap
including a 1% reservation allowance**. Broker cash may be higher; it is never
treated as StockWatch spending authority. The remaining allocation falls as broker
cash is spent, and external deposits do not increase its $1,000 ceiling. Actual fees
are broker-dependent; the allowance is not a quoted fee. Setup verifies actual
account IDs differ from each other and both automated account identities. At least
$1,000 broker cash and empty positions/orders are required. The setup preview shows
both broker cash and the $1,000 allocation, and a cash change requires a new preview.
Each account requires its own preview and confirmation. Nothing resets an account.
Use the account selector at the upper left of the Alpaca dashboard and choose
**Open New Paper Account**. Name the two accounts clearly and generate separate API
keys while each is selected. Record the account IDs and verify that all four IDs
including the existing automated accounts differ. If Alpaca's account limit prevents
two more under one login, use a separate Alpaca paper login for the additional
account; do not reuse or delete either automated account. Alpaca staff has
[described a three-paper-account limit per login](https://forum.alpaca.markets/t/feature-request-more-paper-trading-accounts/18125).

In root-owned mode-0600 `/etc/stock-watch/systems.env`, configure:

```dotenv
MANUAL_STOCKS_ALPACA_API_KEY_ID=...
MANUAL_STOCKS_ALPACA_API_SECRET_KEY=...
MANUAL_BITCOIN_ALPACA_API_KEY_ID=...
MANUAL_BITCOIN_ALPACA_API_SECRET_KEY=...
STOCK_WATCH_AUTOBOT_TOKEN=<random-at-least-32-characters>
STOCK_WATCH_BROWSER_SERVICE_TOKEN=<different-random-at-least-32-characters>
STOCK_WATCH_TELEGRAM_USER_ID=<allowed-human-user-id>
STOCK_WATCH_TELEGRAM_CHAT_ID=<allowed-chat-id>
STOCK_WATCH_DIGEST_TIME=20:00
```

The existing automated account credentials remain untouched. Configure Autobot's
protected `.env` with the **Autobot token only**, the same allowed user ID, and its
existing `TELEGRAM_CHAT_ID`. The client fixes its service URL to
`http://127.0.0.1:3013` and rejects remote destinations and redirects. Do not reuse the
browser credential as the Autobot token. Tokens and broker keys are never committed.

The manual workspace is `/manual-paper`. It displays the same drafts, instructions,
fill observations, protective plans, account labels, and attribution as Telegram.
Browser operator sign-in is independent of Telegram authorization. In the absence
of credentials it displays Unconfigured and cannot silently borrow system accounts.

## Telegram commands and exact confirmation

Start with `/stockwatch` for help and Prices/Accounts/Orders buttons. Both allowed
user **and** chat must match before any StockWatch operation is requested.

```text
/stockwatch prices
/stockwatch accounts
/stockwatch positions
/stockwatch orders
/stockwatch activity
/stockwatch pnl
/stockwatch setup stocks
/stockwatch setup bitcoin
/stockwatch buy stocks XYZ 1 25.00
/stockwatch sell stocks XYZ 1 26.00
/stockwatch buy bitcoin BTC/USD 0.0005 80000.00
/stockwatch above bitcoin BTC/USD 0.0005 80000.00 80400.00
/stockwatch below stocks XYZ 1 25.00 25.12
/stockwatch stop-limit sell stocks XYZ 1 24.00 23.90
/stockwatch cancel stocks <instruction-id>
/stockwatch protect stocks <entry-instruction-id> 23.00 28.00
/stockwatch cancel-plan stocks <entry-instruction-id>
```

Examples are syntax only, not suggested trades or current executable prices. Buy
and sell use explicit price-protected limits. Stock limits use whole shares and DAY;
Bitcoin limits use broker increments and GTC. Broker stop-limit orders are supported;
plain crypto stops, short sales, leverage, options, market orders, fractional stock
limits, and combinations of local conditions with broker stops are rejected. See
[Alpaca crypto order support](https://docs.alpaca.markets/us/docs/crypto-orders).

A mutation first produces a preview. Its single-use token expires in two minutes
and binds to the exact draft hash, human user, and chat. Revisions require a new
preview. StockWatch rechecks account identity, reservations, ownership, metadata,
and fresh quotes before committing, then validates again before submission. Stable
Telegram update IDs make preview retries idempotent; reused confirmation callbacks
cannot produce another intent. If a preview reply is lost, request a new preview;
the token is not silently reissued. No natural-language trading interpretation runs.

Local entry conditions expire after 24 hours by default. Already-satisfied
conditions are disclosed. Triggered buy limits may be no more than 0.5% above the
trigger; the preview fixes that limit. Recovery checks the current fresh condition,
expiry, cash/quantity reservation, and limit protection. Missed ticks are never
replayed. Stocks use batched IEX quotes every five seconds during regular sessions,
explicitly labelled as IEX rather than consolidated SIP. Bitcoin custom triggers
use Coinbase, followed by fresh Alpaca execution validation.

## Protective exits

Attach a protective plan to an entry instruction using stop loss, take profit, or
both (`null` omits one threshold). It covers actual filled quantities, including
partial fills, not the original requested quantity. This version supports one
isolated entry per account/symbol for an active plan and rejects conflicting manual
trades until the plan and any pending exit settle. Broader lot-netting is not inferred.

When a current fresh trigger is satisfied, the plan latches the exit, cancels any
remaining entry, waits for broker acknowledgement, and sizes one GTC sell limit
from actual ownership. The limit is at most 0.5% below the fresh Alpaca bid. It may
not fill after a gap. A triggered exit remains authorized during subsequent
Coinbase outages, but still requires an executable Alpaca quote. Plans have no
24-hour expiry: they remain until the position closes or the user confirms
`cancel-plan`. Canceling a child order alone is rejected because the plan would
otherwise recreate it. Cancellation waits for uncertain or outstanding child orders
before releasing ownership. Dust below the broker minimum produces an actionable
notice. This is application management, not broker-atomic OCO.

## Systems and research

```text
/stockwatch systems
/stockwatch system variant bitcoin <version> fast 10
/stockwatch system backtest stocks <version> 2022-01-01T00:00:00Z 2026-01-01T00:00:00Z
/stockwatch system observe bitcoin <version>
/stockwatch system start_paper bitcoin <version>
/stockwatch system pause bitcoin <version>
/stockwatch system resume bitcoin <version>
/stockwatch system exit bitcoin <version>
/stockwatch system exit_and_pause bitcoin <version>
```

Only parameters supported by the selected template are accepted. Publishing creates
an immutable version; a backtest never activates it. Existing qualification,
forward-observation, risk, and allocation checks remain in the strategy workers.
System actions operate in system accounts, independent of manual-account setup.
Legacy Bitcoin deployments must be migrated to the shared coordinator before these
new control commands can manage them.

- **Pause entries:** cancel pending entries while retaining ordinary position exits.
- **Exit:** cancel pending entries and close owned exposure; later qualifying
  completed-bar decisions may re-enter. A durable decision cutoff prevents reuse
  of the bar preceding the explicit exit.
- **Exit & pause:** close exposure and block further entries until resume.
- **Resume:** remove this entry pause; do not clear risk limits or grant qualification.

Requests and attribution are durable in the manual database, then forwarded with
stable IDs into the existing workspace. Controls have durable audit identities so
interruption cannot reapply an old exit after a later command.

## Accounting and data quality

The UI distinguishes broker unrealized P&L, equity, and reconciled total P&L. Total
P&L is shown only when cumulative fills, posted fee activities, cash, and quantities
reconcile against the confirmed $1,000 baseline. External cash flows, corporate
actions, delayed fill/fee posting, or unowned activity withhold that number pending
review. There is no automated deposit/reset workflow or tax-lot realized-P&L report.
Fee observations are durable and keyed by account/activity ID.

Stock replay now adjusts split quantities, entry-price/stop basis, pending-order
quantity and reference price, indicator OHLC and volume, and momentum history.
Dividend identities deduplicate exact repeats and reject conflicting identities;
distinct same-day events remain distinct. Ex-date entitlement precedes payment,
including equal timestamps. Receivables are paid once. New stock datasets/results
carry `stock-actions-v2`; historical results and immutable strategy hashes are not
rewritten. Bitcoin's engine identity remains `cash-replay-v1`.

Preflight SQL runs in bounded worker threads, not synchronously in Next.js. At most
two inspections run; matching requests coalesce, at most 32 interval/path entries
are retained, and results have a 60-second cache lifetime with database/WAL revision
checking on refresh. Checking/stale/unavailable states disable submission. Dataset
workers still validate their own inputs. The SQL materializes reusable CTEs to avoid
repeating the same raw-bar joins. Query-plan inspection selected the existing
covering `market_bars_lookup`; an experimental partial index was not selected, so
no speculative index was shipped. Cached latency is measured separately from the
full inspection; production timings still require the installed dataset.

An unauthenticated source-access probe to Alpaca corporate actions returned HTTP
401. This demonstrates authentication is required, **not** paid-account entitlement
or historical coverage. Protected production credentials need an operator-assisted
probe. Corporate-action coverage and point-in-time membership remain unverified;
stock qualification remains blocked. No paid data purchase or fabricated membership
was performed.

## Notifications and health

StockWatch has a durable outbox. Autobot claims before sending, acknowledges accepted
messages, and records uncertain sends without blindly retrying. Unsent partial-fill
updates for an order are superseded by the newest cumulative observation. Account
outage notices are suppressed to one per account/day. Daily digest defaults to
20:00 America/New_York, configurable by `STOCK_WATCH_DIGEST_TIME`. It reports
account-labelled snapshots. A downtime-spanning digest is not replayed later.

Independent endpoints:

- `/api/health/market-feed`: Coinbase freshness and connection status.
- `/api/health/execution`: Bitcoin owner and manual owner heartbeats.
- `/api/health/notifications`: notification polling and unresolved uncertain sends.

Unconfigured notification delivery is not reported healthy. These endpoints must
be added to HomeOps and monitored through the independent a1347-j watchdog after
installation; merely committing endpoint code does not register external monitors.

## Deployment and rollback

Use the reviewed StockWatch release installer. Migration 021 is additive and changes
no existing account, allocation, order, or immutable system definition. Before
migration the installer drains writers and makes verified backups of the main DB,
Bitcoin history, manual DB and market DB when present, plus retained artifacts.
Continuous services are stopped explicitly so they cannot make the backup inconsistent.

Build/test the exact revision on Linux, generate `reviewed-release.json`, run
`install-reviewed-release.py <staging-path> --check`, then perform the root install
outside regular US market hours. Its receipt records revision and backup evidence.
Autobot must be committed/pushed and deployed through `scripts/deploy-a1347.sh`; do
not scp/rsync Autobot source. Restart/verify its bot process using its existing service
workflow and confirm the installed revision. Never execute a test paper order without
an explicitly confirmed test draft.

After install verify LAN chart/card placement, SSE updates, collector restart,
execution ownership, protected configuration, and independent health registration.
For rollback: stop the new execution/manual/feed services, retain all current
ledgers, restore only compatible prior code/config, reconcile outstanding broker
orders, and enable exactly the previous execution owner. Older installers cannot
downgrade across unapplied migration history. Do not overwrite live data with backups.
