# Bitcoin systems automation

> Historical release document. Migration 019 adds a separate experimental historical
> qualification path without the 30-day forward prerequisite. Existing allocations
> are preserved rather than replaced by funding. See the [current README](../README.md)
> for policy, account limits, and distinctions between the two paths.

Bitcoin Systems (`/systems?asset=bitcoin`) now provides scheduled research and a
shared, separately funded Bitcoin **paper** account. Stock systems, legacy stock
paper trading, v1 strategy hashes, and earlier Bitcoin results remain intact.
Earlier Bitcoin deployments are available through the “Earlier research and
deployments” link. Migration 017 is additive. `stock-watch-systems init` creates
explicit hourly v2 copies of older Bitcoin versions without enrollment, approval,
funding, or activation.

## Operator workflow

1. Create a version with a hypothesis, rule lookbacks, decision timeframe,
   maximum holding period, and position size. Versions are immutable.
2. Start research collection. Up to five versions can be enrolled simultaneously.
   Unfunded research uses a conservative $60 reference budget, the allocation
   available when five systems share $300. Retire unfunded research to free a slot;
   its history remains available.
3. Approve a version once by entering its full identifier. Approval authorizes
   future qualified paper entries; approval alone does not fund or place orders.
4. Select approved versions and confirm `FUND BITCOIN PAPER`. The coordinator
   validates the separate account and assigns equal allocations, totaling at most
   $300. Losses can reduce this amount; excess account profits remain unallocated.
   Research for a funded version uses its actual allocation. A budget change
   blocks entries until a scheduled evaluation validates the new amount.
5. Review qualification, scenario progress, cached/new counts, forward days,
   account commands, health, order fills, and each entry's evaluation ID.

Initial funding requires exactly $300 cash, no positions, and no open orders.
Reallocation requires settled orders, a flat account, reconciled cash, and no risk
pause. Legacy Bitcoin deployments that retain an account ID block shared funding;
there is deliberately no automatic transfer of their positions or ownership.
Pausing entries preserves exits. Retiring research requires removing its funding
allocation first. Approval is retained for an unchanged version.

## Timing

Decision timeframes are 1 minute, 5 minutes, 15 minutes, 1 hour, 4 hours, 1 day,
1 week, and 1 calendar month. Holdings independently span one minute through
12 calendar months. Weeks start Monday UTC; month arithmetic clamps to the last
valid day, including leap years. The first partial fill starts the holding clock.
Rule exits and risk limits can close positions earlier.

| Process                                         | Cadence                                                    |
| ----------------------------------------------- | ---------------------------------------------------------- |
| Shared collection and forward observation       | Target every 10 seconds                                    |
| Account reconciliation, risk, deadlines, orders | Target every 10 seconds, separate service                  |
| Decisions                                       | Once per completed decision bar                            |
| Minute/hour research                            | Daily, 00:15 UTC                                           |
| Daily-bar research                              | Monday, 00:15 UTC                                          |
| Weekly/monthly research                         | First of month, 00:15 UTC                                  |
| Forward-history continuity audit                | Hourly, cached between checks                              |
| Historical backfill                             | One paginated provider page per research-worker invocation |

Timers wait ten seconds after each completed invocation, preventing overlap even
when an API call is slow. Ten seconds is a service target, not a fill guarantee. API latency, missing data,
service downtime, or broker outages can delay checks and exits. Duplicate
submissions use the same durable client ID and are looked up before retrying.
Unknown submission outcomes retain their reservation even after entry eligibility
expires. One failed order does not stop reconciliation of other systems' orders.

## Evidence and qualification

Each evaluation freezes its version, cash budget, cutoff, and execution metadata.
It creates **20 deterministic chronological windows × five cost profiles = 100
scenarios**. Each window spans at least 12 decision bars and twice the maximum
holding duration, plus indicator warmup. Windows expand as forward history accumulates; placement does not depend on
profitability. Overlap is reported and at least five nonoverlapping windows are
required. Profiles are base costs; double fees; double spread/slippage; delayed
execution with partial fills; and combined adverse costs.

Entry qualification requires:

- All 100 scenarios complete with valid observed bars, current execution
  constraints, and executable quote coverage. Replay observes bar availability,
  consumes only subsequent quotes, resets indicators on gaps, and excludes
  retrospective corrections from earlier decisions.
- At least 30 unique completed trade entries, deduplicated across windows and
  excluding duplicate stress-profile trades.
- At least 60% profitable base windows and positive median base return.
- Positive mean net return for every cost profile and no scenario drawdown above
  10%. Open positions are marked conservatively and reported separately.
- At least 30 elapsed calendar days of forward observations, observations on
  30 distinct UTC dates, recent data, and no unresolved forward gap exceeding
  two hours. A shadow portfolio reserves costs and uses subsequent observed quotes.

Reported historical trade win rate and its Wilson interval are descriptive, not
predictions. Overlapping outcomes remain dependent. A high win rate alone cannot
qualify a version. Returns include fees, spread/slippage, and marked open positions.
The UI reports exposure, turnover, costs, profitable windows, independent windows,
unique trades, scenario pass rate, and limitations.

New research with insufficient evidence stays in Collecting. A previously
qualified system suspends on failed, expired, or unhealthy evidence. A fully
observed performance failure also requires two consecutive passing scheduled
suites before qualification. Approval persists through suspension. Entry checks
also validate approval, operator pause, budget, and current evidence expiry.
Intraday evidence expires after 36 hours; daily-bar evidence after eight days;
weekly/monthly evidence at the next monthly review plus 48 hours.

Historical OHLC backfill is explicitly exploratory and cannot, on its own,
qualify execution. The collector builds actual quote and availability history
prospectively. Long lookbacks and long holding periods may need much more than
30 days of collection; some configurations can remain research-only for years.
A 100-scenario counter does not override insufficient history. The current
backfill adapter does not synthesize historical executable quotes or silently
substitute another trading venue.

## Account ownership, fees, and risk

A single coordinator owns the Bitcoin account. SQLite transactions reserve cash
and quantities per version, and permit one outstanding intent per allocation.
A version cannot sell another version's quantity. Each entry records its
qualification evaluation and reason; cumulative partial fills apply only their
new quantity and notional. Position size is capped at 50% of its sleeve's equity.
Idle sleeve cash is not loaned to another system.

Both the account and each sleeve have a persistent 10% drawdown threshold. A
breach pauses entries, cancels pending buys, and attempts to close owned tradable
positions. Existing sells and holding deadlines continue through research/data
qualification failures. Hard risk pauses require an explicit reactivation
request; reactivation does not erase high-water marks or bypass a remaining
breach. Residual Bitcoin below the broker minimum is retained and reported;
funding changes remain blocked while the broker account holds it.

Alpaca's documented base taker fee is reserved at 25 bps. Buy fees are denominated
in BTC and sell fees in USD. Actual fill activities and fee activities are stored
separately. Fees with an order ID are attributed directly. When the broker gives
only an aggregate daily fee, the coordinator waits for the completed UTC day and
complete fill activity, then allocates that fee proportionally to actual credited
BTC quantities or USD sale proceeds. The method is recorded for audit; it is an
accounting allocation, not a claimed broker-provided per-order charge. Unknown
assets, unowned fills, incomplete fee ownership, external account activity, and
unexplained balances block entries. Conservatively reserved fees cover the
posting delay; higher actual fees apply immediately and lower-fee reserves are
released only after settlement and exact account reconciliation.

Sources: [Alpaca crypto fees and order constraints](https://docs.alpaca.markets/us/docs/crypto-trading),
[Alpaca fill and non-trade activity fields](https://docs.alpaca.markets/us/docs/account-activities).

## Installation and operations

Application deployment is separate from implementation. Resolve the authoritative
application host during the existing server migration before running the installer.
Do not enable services in an inactive migration staging tree.

After installing this release on the active host:

```sh
sudo /opt/stock-watch/deploy/install-systems-root.sh
```

The installer applies migration 017, creates unapproved hourly copies, and installs
both new service/timer pairs. It does not enable the new Bitcoin trading or data
timers automatically. Configure the existing protected
`/etc/stock-watch/systems.env` with separate Bitcoin paper credentials and the
operator token, then enable collection and the paper coordinator:

```sh
sudo systemctl enable --now stock-watch-bitcoin-data.timer stock-watch-bitcoin-automation.timer
systemctl status stock-watch-bitcoin-data.timer stock-watch-bitcoin-automation.timer
journalctl -u stock-watch-bitcoin-data -u stock-watch-bitcoin-automation -u stock-watch-systems-research --no-pager -n 80
```

Enabling the coordinator alone cannot authorize orders: approval, funding,
qualification, reconciliation, fresh data, and risk checks are still required.
Do not disable a coordinator that is managing open positions merely to pause
entries; use the UI pause control so exits remain active.

The existing research service handles v1 work and v2 scenarios under one CPU and
768 MB. Each scenario is resumable from its immutable cutoff after interruption;
content hashes cover configuration, capital, execution metadata, bars, and quotes.
Historical cursors and the disk-backed trade-deduplication store bound memory.
Market history lives beside the configured app database as
`<database>.bitcoin-history.db`; trade artifacts live at
`<database>.bitcoin-history.db.trades.db`. These databases need their own consistent
SQLite backups; the existing stock database backup alone does not include them.
The data and execution services use separate locks from research and higher
scheduling priority. The updater preserves previously enabled timers.

Local validation covers UTC calendar boundaries, immutable v1/v2 hashes,
100-scenario accounting, source-aware reuse, missing bars, subsequent-quote
execution, deduplication, qualification expiry/recovery, concurrent reservations,
partial fills, unknown submission outcomes, fee attribution, outage exits, UI
permissions, and a five-system/500-scenario fixture with interleaved application
writes. This is a software/load fixture, not evidence of profitable trading or a
production soak test.
