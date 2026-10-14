# Intraday paper experiments

Implementation branch: `codex/paper-experiments`, based on installed release
`3d33aec`. Migration 028 is reserved for the independent research desk; this
feature starts at 029. Existing strategy hashes, qualification gates, scanner
limits, ledgers, and the manual account remain authoritative.

## Accepted design

An experimental authorization permits capped, unvalidated forward trials. It
does not count as historical qualification. Versions are immutable; a frozen
batch binds versions, universe, account identity, allocations, approval and a
30-day expiration. Each batch has distinct instances, decisions and positions.
Approve the exact preview revision. New research creates proposals, never edits
an active batch. No LLM, Tab, Instinct or email integration is required.

Each asset group has a $1,000 pool: four $200 strategies, a $50 control and $150
unallocated. Entries reserve at most $50 including allowances. No leverage,
shorting or adding to a position. Stocks allow two positions per instance;
Bitcoin one. Four entries per Eastern day, 30-minute symbol cooldown,
deterministic round-robin selection. Pause entries at 2% daily pool loss or 10%
drawdown including unrealized P/L and controls. Resume must not reset breaches.

Four completed five-minute strategies: EMA20/EMA50 trend; preceding 20-bar
breakout/10-bar exit; Wilder RSI14 crossing above 35 with close above EMA50,
exit at RSI55 or below EMA50; breakout requiring symbol-linked news both
published and first observed in the preceding hour. Stocks: SPY, QQQ, IWM, XLF,
XLK, XLE, AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, XOM. Bitcoin: BTC/USD.
No substitutions for unavailable symbols. Decisions use 250 preceding bars
plus the completed bar, as observed by close+35 seconds. No late entry replay.

Stock entries open+15 to close-30 minutes; maximum hold two hours or close-15.
Bitcoin trades 24/7 with four-hour holds. Stop/take: stocks 1%/2%, BTC 2%/4%.
Daily $10 SPY/BTC controls at 10:05 Eastern with a five-minute entry window,
15-minute hold and identical execution gates; controls excluded from rankings.

Marketable limit entries expire after 60 seconds with maximum 0.5% price
allowance. Exits try a limit, confirm cancellation and final cumulative fill,
then market only the remaining owned quantity during a valid session. Unknown
submission/cancellation retains reservation and prevents replacement. Stock
proceeds remain unavailable until the broker's settlement date, including
bank holidays when stocks trade. Missing settlement evidence blocks reuse.

## Integration contracts

* One owner per automated account; stock and BTC processes are independent.
  Old stock paths produce intents; their IDs, rules and $5–15 caps remain.
* Common fixed-paper transport, account identity, reservations and lifecycle.
  Manual execution remains separate. Exits precede entries; no cross-owner
  position netting. No network calls inside SQLite write transactions.
* Main DB holds authority and execution; a separate asset/feed/symbol-aware
  evidence DB records bar revisions, quotes, receipt times and news. Existing
  Bitcoin history retains its original interpretation. Pin decision evidence.
* Stream IEX equities and Alpaca crypto; one connection per feed. REST backfill
  warms indicators but cannot become historical forward evidence. News polling
  is bounded, deduplicated and independently healthy. SEC/Fed/BLS are research
  context, not directional orders. Never mix IEX and SIP silently.
* Operator-authenticated bounded APIs enqueue execution commands outside the
  research queue. Small Experiments UI supports previews, approval, pause,
  resume, exit and exit-and-pause, state and evidence inspection.
* Shared activity projection covers scanner, older systems, experiments,
  controls and manual. Count fill deltas, not cumulative update events. Daily
  digests use durable cutoffs and catch up after missed exact-minute wakeups.
* Replay shares pure decisions and timing with forward trials; simulated fills
  remain labeled. Compare returns on allocated capital, exposure, drawdown,
  turnover, holding periods, costs, inactivity, news ablation and benchmarks.
  Limit proposals to two predefined single-parameter variants/family/week.

## Rollout and verification

Keep experiments disabled until preflight and frozen batch approval. Quiesce
writers and back up the operational DB, evidence DB, manual/history/market
databases and artifacts. Preserve existing authority and timer states. A
rollback must retain a compatible owner while experiment positions are open.

Test old hash/limit/manual regressions, account and symbol contention, partial
fills, accepted POST timeouts, uncertain cancellation, restarts, remaining-qty
market exits, settlement holidays, late bars/news, feed outages, expiry, risk
pauses, fee reconciliation, replay parity and digest deduplication. Run worker,
web, feed and deployment checks, type-check, lint and production build before
reviewed installation. Observe the first five sessions after approved activation.

## Implemented components

`worker/src/stock_watch_worker/experiments/` contains the immutable protocol,
batch authorization, shared account accounting, execution, evidence, research,
replay and reporting adapters. The original indicator functions are reused.
Migration 029 is additive; it creates no approved batches or funded instances.

The stock owner now drains original scanner and stock-system intents. The
existing Bitcoin owner also runs experiments. Original stock submission paths
defer to the owner after cutover. The manual service retains its own account and
owner. Cash anchors and ledger deltas detect unexplained account changes; fee
provisions are distinct from posted fees. Bitcoin fee reserves do not count as
new strategy positions. Small quantities below a broker's minimum stay attributed
to their original instance and can require later fee reconciliation.

The Experiments view is `/systems?tab=experiments&asset=stocks` (or `bitcoin`).
Its execution queue is separate from `workspace_jobs`. Research replays reuse
the existing research worker and save full, content-addressed SQLite evidence
and execution artifacts under `<database>.systems-data`. Replay uses the same
engine with a broker adapter that has no network methods. It models fills from
subsequent captured quotes, 10 bp slippage and 25 bp crypto fees. Five-second
quote sampling, missing capture periods and shared account capacity limit the
comparison; it grants no profitability qualification. Historical warmup keeps
its historical provenance and cannot supply a past forward decision.

Account preview and approval checks run on a separate connection/thread within
each owner process, capped at one command per 15 seconds. Their broker reads
cannot delay protective exits. Approval checks the ledger again under a write
lock and rejects concurrent accounting changes; pause and exit commands remain
on the execution loop. The preflight worker never submits or cancels orders.

The daily Telegram digest projects actual fills from scanner, legacy systems,
experiments, controls and manual accounts. Its existing durable `digest:date`
identity prevents repeats; it catches up the latest missed cutoff. Unavailable
automated reporting is stated explicitly. Routine automated fills are grouped;
manual confirmations and urgent failures retain the existing outbox transport.

## Setup and activation

1. Run the verification commands below from this release checkout, commit the
   reviewed changes, then run `./deploy/stage-reviewed-release.sh`. Staging
   builds and tests the source on a1347-m and does not install it.
2. Install the verified staging directory with the existing root-reviewed
   installer. It drains writers, backs up all databases/artifacts, applies 029,
   preserves trading authority, and installs `stock-watch-stock-owner`,
   `stock-watch-experiment-feed`, and `stock-watch-experiment-collection` services.
   The existing Bitcoin execution service retains its enabled/disabled setting.
3. Keep separate stock, Bitcoin and manual paper broker identities. Existing
   stock and `BITCOIN_ALPACA_*` credentials are read from the existing environment
   files. New services need no LLM, paid data subscription or email integration.
   Node 22.13+ is required. The collector uses one IEX and one Alpaca US crypto
   WebSocket connection, bounded news paging each minute, historical warmup
   every 15 minutes, and official research feeds hourly. It does not use SIP.
4. Inspect `/api/health/experiments` and the view's health details. Confirm stream
   entitlements, 251 completed bars, symbol eligibility and the settlement
   calendar. Initial collection may need about 30 minutes to bridge the Basic
   historical-data delay. Stock closures and missing IEX bars can take longer.
5. Sign in using existing Operator access, choose **Prepare batch preview**,
   review the exact rules, pool, account and expiry, then approve that revision.
   Preview approval expires after 30 minutes. Approving a batch starts capped
   unvalidated paper trials; it does not modify the old profitability gates.
6. Confirm the next eligible control entry and its exit, then review decisions,
   fills, fees, settlement and the daily digest over five sessions. A missed
   10:05 Eastern control window is recorded, never replayed later that day.

The stock cash model uses the broker's `settlement_date`, or the explicitly
requested **SETTLEMENT** calendar to select the next settlement day. It never
uses the next stock trading day as a substitute. Missing broker dates keep
proceeds unavailable. Account checks and paper simulations remain essential:
[Alpaca calendar API](https://docs.alpaca.markets/us/v1.1/reference/getcalendar-1),
[paper-trading limitations](https://docs.alpaca.markets/us/docs/paper-trading).

Primary research context comes from the existing SEC cache, the
[Federal Reserve feeds](https://www.federalreserve.gov/feeds/feeds.htm), and
[BLS feeds](https://www.bls.gov/feed/). Source documents inform review; their
presence is not directional sentiment. News-breakout only requires timely,
symbol-linked news. Original URLs and publication/receipt times remain available.

Scheduled backups now include auxiliary databases under `auxiliary/` and
verified research artifacts under `research-artifacts/` in the backup root.
An off-host client that currently pulls only `stock-watch-latest` must also sync
those subdirectories to retain the complete recovery set. The restricted rsync
export already permits paths within that root. Never roll back the database to
remove this feature. Keep a compatible execution owner until orders, positions,
fees and settlements have reconciled. A later desk release must retain migration
029 even when it adds the independently reserved migration 028.

## Local verification

```sh
PYTHONPATH=worker/src python3.12 -m unittest discover -s worker/tests -q
python3.12 -m unittest discover -s deploy -p 'test_*.py' -q
npm test -- --runInBand
npm run test:feed
npm run type-check
npm run lint
npm run build
```

Tests cover original behavior plus account/symbol reservations, cumulative-fill
deltas, POST/cancel uncertainty, fee attribution, fee-reserve release, subsequent
Bitcoin entries, settlement holidays, late news/future quotes, loss controls,
engine/replay integration, command authorization and digest cutoffs. A synthetic
1,000-tick idle/missing-feed run on the development Mac took 0.424 seconds (p95
0.68 ms, maximum 11.28 ms). This excludes broker latency and is not a production
throughput measurement. Live account preflight and the first approved control
round trip still require the installed services and operator approval.
