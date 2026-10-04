# Independent LEAN validation

## Verified deployment — October 3, 2026

StockWatch release **`992d909e0ec6`** installed at 11:50 Eastern with migration
**027**. Runner **`0aef4311004e11f1d4c3838d7931abb97e686b74`** is installed on
a1347-d. The scoped client was verified as the StockWatch service user; bridge
health also passes through the canonical LAN proxy. Web, market-feed, manual-paper
and execution services are active. Feed, execution and notification health passed
at 11:53 Eastern. Recovery snapshot: `/var/backups/stock-watch-releases/20261003T153421Z`.

The complete historical comparison finished at **11:52:10 Eastern**, using 720
hourly BTC/USD observations from September 1 through October 1 (exclusive), 2026.
The original SMA 20/100 trend version, $300 starting cash and 50% allocation
produced **zero differences** across 720 decisions, six fills and 726 equity
observations. Both engines ended at $300.94564011, with $2.25873657 fees and
3.97684549% sampled maximum drawdown. Original tolerances were unchanged.

This is implementation agreement on retained market observations with synthetic
next-bar execution, not proof of executable fills or profitability. Only three
closed trades occurred; hourly marks cannot reproduce continuous risk execution.
No qualification, activation or broker order was created. See the compact
[evidence record](lean-historical-verification.json), or open the completed run
in the normal Systems library at `/systems?asset=bitcoin` and download its complete report.

The independent runner repository is [stockwatch-lean](https://github.com/mjm2z/stockwatch-lean).
It uses the free LEAN engine directly, without a paid QuantConnect CLI, cloud job,
data subscription or broker credentials. The official image is approximately
14 GB compressed; its expanded runtime consumes additional host storage outside
job retention. Its immutable digest and engine build 18155 identify the runtime;
the registry attestation does not supply a corresponding source commit.

## Workflow

In Crypto → Systems, choose an immutable original Bitcoin trend version and a
registered hourly Bitcoin dataset. Preview the full historical interval, $300
starting cash and dataset cost assumptions, then queue a comparison. An operator
session and healthy configured runner are required. Visual rules, newer Bitcoin
protocols, stocks, partial-fill inputs and unsupported data features are rejected.
This initial adapter is intentionally narrow.

The bridge recomputes StockWatch's baseline in the background and sends only the
validated configuration, dataset and content hashes to LEAN. The runner receives
no StockWatch baseline decisions, broker keys or trading authority. LEAN uses its
own indicators, portfolio and explicit fill/fee models. The comparison covers
ordered decisions, fills, fees, equity and sampled maximum drawdown. Quantity
uses the dataset increment, dollar values a one-cent tolerance and drawdown one
basis point. Missing events and timestamp mismatches are differences. Agreement
is diagnostic evidence and never qualifies or activates a trading system.

The interface includes queue stage, elapsed time, cancellation, metrics, equity
curves, the first reported divergence, paged differences and a downloadable full
report. Charts are sampled for display; full result arrays remain in the report.
Synthetic quotes, bar approximations, gaps and other input limitations remain
visible. A successful comparison cannot establish realistic fills or profitability.

## Ownership and recovery

| Host/service | Responsibility |
| --- | --- |
| a1347-m / `stock-watch-lean.service` | StockWatch baseline, durable intent, SSH submission and comparison |
| a1347-d / `stockwatch-lean.service` | Research queue, fixed algorithm, bounded LEAN containers |
| a1347-j | Existing independent watchdog; no LEAN execution |

The bridge uses a dedicated SSH key and pinned host key. The restricted remote
account accepts only the JSON research protocol over a local Unix socket; it has
no Docker group access. The root supervisor launches only bundled code in a
pinned image with no network, dropped capabilities, a read-only filesystem,
2 CPUs, 3 GiB memory and a 30-minute deadline. Arbitrary algorithms and paths
cannot be supplied through the app.

Stable comparison IDs bind to exact input hashes. Lost submission acknowledgements
are reconciled before another submission. Restarted supervision inspects existing
containers; interrupted or missing execution fails explicitly rather than silently
starting a second run. Cancellation is durable intent and remains pending during
an outage. It never cancels trades or changes system activation.

The integration conservatively allows five unfinished comparisons total and runs
one engine job at a time. Requests/results are bounded at 64 MiB; temporary engine
output is bounded at 500 MiB. Completed artifacts are pruned after 30 days or under
storage pressure, with a 10 GiB target cap on each host. StockWatch retains compact
comparison summaries after artifacts expire. Runner failure logs retain a bounded
tail. Historical trading ledgers and input datasets are outside this policy.

## Deployment and operations

First verify the offline three-event engine proof, then test the actual adapter
against fixtures and a retained Bitcoin dataset. Install the reviewed runner from
a clean pinned checkout using `deploy/install-runner.py` in its repository.
Configure the separately generated research SSH identity using StockWatch's
`deploy/install-lean-client-root.py`. Neither helper takes Alpaca credentials.

Deploy StockWatch only through `deploy/install-reviewed-release.py`, which backs
up before additive migration 027 and stops the bridge during database/runtime
cutover. The bridge can run unconfigured; the UI stays disabled. The read-only
`/api/health/lean` endpoint reports unavailable until configuration and fresh
runner health are present. HomeOps now monitors this endpoint; both user services were restarted after
registration. The independent a1347-j watchdog service was verified active.
This does not constitute an outage-delivery test.

When rolling back to an application release without LEAN support, stop and disable
`stock-watch-lean.service` before switching runtimes. Preserve migration 027 tables
and research artifacts; do not restore an older trading database merely to remove
this research interface. Stop the separate runner only after inspecting active
comparisons and cancellation state.

Monitor the prerequisite proof without keeping an agent occupied:

```sh
ssh a1347-d 'journalctl -fu stockwatch-lean-proof.service'
```

Ctrl-C stops viewing the journal, not the proof. A stopped/transient unit alone is
not proof of success: inspect its exit status and verified result before proceeding.

## Verification and remaining limits

Production staging passed the build, TypeScript, lint (existing unrelated warnings),
121 JavaScript tests, 428 worker tests and 54 deployment tests (one platform skip).
Two subsequent historical-helper tests also passed. The runner has 17 passing unit
tests, plus installed-container baseline, gap and minute-risk drawdown fixtures
with zero differences. Duplicate submission and queued cancellation passed.
The historical run additionally verified dataset acquisition/registration, durable
StockWatch queueing, background baseline, scoped submission, result retrieval and
comparison through the installed application.

Live supervisor and bridge restart recovery, the full 30-minute timeout, and real
outage/recovery notification delivery have passed. Desktop/mobile read-only browser
inspection passed after the Systems mount correction. Authenticated browser
submission/cancellation is deferred until the remaining integrations are set up. Storage/result limits have deterministic
boundary tests; actual host resource exhaustion was not induced. Earlier failed fixture runs and their corrections are
preserved in [historical implementation notes](lean-implementation-checkpoints.md).
The engine proof and synthetic fixtures do not replace market-data limitations.

## Reproducing the historical check

`deploy/run-lean-history-root.py` requires installed release `992d909e0ec6`, a
healthy bridge and an exact helper digest. It launches the helper under the
StockWatch service identity with its protected environment. The helper retains
September hourly data and queues the original immutable trend version. Fixed ID
`f88ac8db-ae06-549e-af58-5ba17958366f` makes repeat invocation return existing work;
conflicting reuse fails. It cannot qualify or activate a system or submit orders.
The helper is committed separately from the installed application runtime.

For a new comparison, use the Systems preview/queue workflow with a supported
registered hourly dataset. An operator session is required for mutations. Read-only
status is available at `/api/lean` and runner health at `/api/health/lean`.
Research SSH files live in `/etc/stock-watch-lean`, independently of root-only
broker configuration. Do not move them back under `/etc/stock-watch`.

## Operational verification follow-up — October 3

The browser walkthrough found that the original LEAN card was mounted only in the
older Systems screen. The normal `/systems?asset=bitcoin` library did not expose it,
and `/crypto?view=systems` incorrectly opened Overview. The corrected mount and
monitoring links were installed in `7f4f4ef4bcd2` at 13:12 Eastern.
The old screen's historical metrics and charts rendered in the deployed browser.
Mobile chart overflow was also found; the installed fix constrains grid children.
The normal Systems library and mobile sizing now pass the deployed browser check.

`deploy/lean-watchdog.py` adds a separate a1347-j research monitor using the existing
protected Telegram transport. It checks each minute, requires three failures and
two successes, preserves 22:00–11:00 Eastern quiet hours, and records uncertain
sends without automatic retry. `deploy/install-lean-watchdog-root.py` verifies its
source hash and healthy baseline before installation. This does not change the
HomeOps watchdog target. The monitor is installed; real outage/recovery delivery passed on October 4
with accepted Telegram receipts 1060 and 1061.
See the [operational verification report](lean-operational-verification.md) for current evidence.

Runner `deploy/verify-operations.py` provides isolated `restart`, `timeout` and
`outage` exercises on a1347-d, with journal progress and an empty-queue prerequisite.
Restart must retain the container identity and exact verified synthetic result.
Timeout retains the full production 30 minutes, requires container cleanup and a
subsequent matching fixture. Outage schedules automatic restoration before a
five-minute runner-only stop; inspect a1347-j incident receipts afterward.
Run scenarios sequentially and leave the research queue idle during verification.
The bridge helper `deploy/verify-lean-bridge-root.py` queues a separate audited
historical replay and restarts only the bridge while it is awaiting LEAN.
The live runner restart passed on October 3 at 13:10:33 Eastern with the same
container and exact retained fixture result. The bridge restart also passed at 13:18:48 with zero comparison differences.
The full timeout test and a repeat passed on October 3, including container
cleanup and matching follow-up work. Real notification delivery passed on October 4; authenticated browser submission
and cancellation are deferred until the remaining integrations are set up.
