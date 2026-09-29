# Next-phase release report

This report separates source work, tests, staging and installed operation.

## Current checkpoint

Implementation has passed local verification and is ready for committed Linux
staging. It has not replaced the pending reviewed installation of
`6e7120fe1e9d`. That earlier installer remains the release
owner. At the latest host check on September 29, its journal showed completion
of the main database copy at 01:07 ET, verification of the recovery database, then
auxiliary Bitcoin-history backup at 11:00 ET. Web, feed, execution and manual
services were inactive during that operation. No new deployment was started.

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
Linux staging and installed verification are separate remaining checkpoints.

## Limits and operator prerequisites

Pre-collection manual return history, funding-matched benchmarks, full tax-lot
realized accounting, historical stock membership/corporate-action completeness,
formal uncertainty/DSR/PBO and new ATR/relative-strength rules are not claimed.
System chart inspection does not invent missing historical indicator series.
Legacy stock execution timers remain separate. Telegram's existing parser remains
compatible; expanded browser forms do not imply undocumented Telegram syntax.

Root installation must wait until the existing release owner completes. Confirm
its installed receipt and execution-owner health before considering another stage.
Provision protected credentials and confirm manual setup separately. HomeOps
component registration, watchdog verification and paper-order tests remain
explicit post-install checks; a fixture is not production verification.
