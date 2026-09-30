# Next-phase release report

This report separates source work, tests, staging and installed operation.

## Current checkpoint

Implementation is committed and pushed. The exact runtime revision
`5c374e316dd900a8f62746587982972f27352596` passed Linux staging at
`/home/mjm2z/stock-watch-releases/5c374e316dd9`, including the reviewed installer's
read-only preflight and verification of 32,327 artifact files. It has not replaced
the installed revision `6e7120fe1e9d26271032ffc55902722dcb345cdf`.
Its receipt records completion at September 29 13:35 ET; the supervised unit
exited successfully at 13:36 ET. Migration 021 was applied, recovery data retained,
and the web, market-feed, execution and manual-paper services are active.
Legacy Bitcoin automation/trading timers are disabled; the execution service is
enabled. The earlier `e7346a4fa798` stage is superseded by `5c374e316dd9`.

The evening follow-up found healthy execution heartbeats and fresh Coinbase
prices, but overall application health remains degraded. Stock worker and
maintenance runs failed with `database is locked`; the scheduled backup timed
out while retaining its previous backup. Fundamentals and universe services also
retain failed states, with their causes not yet verified. Some running operation
records refer to exited processes; they were not rewritten to imply success.
The earlier long-running scan worker has now exited. Host I/O pressure remains
high. Do not declare the application fully healthy or initiate another long
installation before investigating this contention. `sudo -n true` still requires
an operator password; no new installation or database cleanup was performed.

A September 29 22:49 ET bounded kernel-lock sample observed brief writes from
the execution owner and a systems worker, but no sustained blocking writer.
The failure tracebacks locate stock scan writes in feature/signal/assessment
persistence and maintenance writes in signal evaluations. This does not prove
which competing operation caused the earlier failures. Source-only exception
diagnostics now retain SQLite extended codes (405 worker tests passed), and the
read-only lock recorder passed an isolated Linux fixture test. The recorder is
available on the host for operator-root capture; no service restart was performed.
See the runtime guide for the command and the distinction between source,
staged artifact and installed code.

The operator's five-minute capture on September 29 22:54–22:59 ET produced 92
change/heartbeat records. Main-database write ownership moved between execution
PID 2160035 and short-lived worker/systems processes. The longest sampled interval
with unchanged write ownership was approximately 11.1 seconds, below the configured
30-second busy timeout; sampling cannot prove continuous ownership or exclude
short missed locks. No new failed scan appears in the available operation records
for this capture window. Earlier scan failures therefore remain uncorrelated with
a blocking PID. Host I/O pressure remained high throughout. This is evidence
against treating a visible ownership lock as a stuck lock, not proof that prior
contention is fixed. No lock files were deleted and no owners were restarted.


Manual credentials and combined-account setup were still pending at the last
confirmed setup checkpoint. No account reset, strategy activation or end-to-end
paper test order was performed by this iteration. The browser test uses an
isolated database and mocked manual previews, never order confirmations.

## Implemented source

- Shared order capability contract, guided manual ticket, notional market buys,
  fractional stock DAY orders, supported stops, local conditions and protective
  plan controls. Existing budgets/ownership/confirmation boundaries are retained.
- Broker validation outside manual SQLite write locks, revision-guarded commits,
  notional partial-fill reservations, actual fractional protective exits and
  prospective transition history.
- SPY-first stock history with candles/volume, custom ranges/resolution, watchlist
  and normalized comparisons; raw-price scope checks for broker overlays.
- Read-only chart levels, activity markers and inspectors, explicit ownership,
  selected system state and clearly simulated preview levels/fills.
- Research-only immutable snapshots, revision-safe drafts/publication, queued
  previews using the existing replay/rule engine, frozen experiments, attempts,
  interval inspection registry, reviews and deterministic paired demonstration.
- Full-resolution result metrics with bounded display records and hash-verified
  complete artifacts; shared immediate Coinbase SSE consumers; matching favicon.
- Reorganized README and eight technical guides; prior README preserved as archive.

## Verification log

Local verification: 404 worker tests, 96 web tests across 26 suites, six feed tests
and 34 deployment tests passed. Type checking and the production build passed;
lint retains three existing warnings. Desktop (1440px) and mobile (390px) fixture
checks cover Stocks, manual paper, research and Activity, with no JavaScript
errors or horizontal overflow. Chart toggles perform no mutations. Order testing
uses mocked previews and never confirms a broker order. Research tests verify
that the demonstration creates no executable versions, enrollments or orders.
The final Linux artifact passed the same 404 worker, 96 web and six feed tests,
type checking, lint and production build. The additional deployment suite ran
34 tests successfully with one platform-specific skip. Worker wheel packaging,
manifest hashing and read-only installer preflight passed. Installation of this
next-phase artifact remains pending runtime diagnosis and operator root access;
staging did not apply migration 022.

## Installation handoff

Follow the existing owner without continuous agent polling:

```bash
ssh a1347-m 'journalctl -fu stock-watch-release-6e7120fe1e9d'
```

For the actual process step and disk activity, use
`python3 deploy/monitor-release.py --watch` from the local checkout. At the
September 29 12:42 ET follow-up, the installer had advanced to copying the runtime
with rsync; the 11:00 backup journal message was stale. The rotational host disk
was heavily utilized. See the runtime guide for monitoring limits and prospective
optimizations; the running installer and verified stage were not modified.

The previous installer has completed. Resolve the runtime contention above before
starting the next installation. Once service health is reviewed, root access and
the existing market-window guard permit the reviewed installer:

```bash
sudo systemd-run --unit=stock-watch-release-5c374e316dd9 --collect \
  /usr/bin/python3 /home/mjm2z/stock-watch-releases/5c374e316dd9/deploy/install-reviewed-release.py \
  /home/mjm2z/stock-watch-releases/5c374e316dd9
```

Run this on a1347-m. It backs up before migrating; do not use code-only mode for
migration 022. Then verify the new installed receipt, LAN pages, Coinbase SSE,
independent component health, restart behavior and execution ownership. Manual
trading remains unconfigured until protected credentials and account setup are
confirmed. No sudo installation or paper test draft was confirmed in this iteration.

## Limits and operator prerequisites

Pre-collection manual return history, funding-matched benchmarks, full tax-lot
realized accounting, historical stock membership/corporate-action completeness,
formal uncertainty/DSR/PBO and new ATR/relative-strength rules are not claimed.
System chart inspection does not invent missing historical indicator series.
Legacy stock execution timers remain separate. Telegram's existing parser remains
compatible; expanded browser forms do not imply undocumented Telegram syntax.

Root installation must wait for runtime diagnosis and operator root access. The
installed receipt and execution-owner health are verified; stock jobs remain degraded.
Provision protected credentials and confirm manual setup separately. HomeOps
component registration, watchdog verification and paper-order tests remain
explicit post-install checks; a fixture is not production verification.
