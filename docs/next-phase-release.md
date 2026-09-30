# Next-phase release report

This report separates source work, tests, staging and installed operation.

## Manual account and monitoring checkpoint: September 30, 14:12 ET

The operator corrected the dedicated manual paper credentials, reran the
provisioning helper successfully, and confirmed the combined setup in Telegram.
The helper verified three distinct paper account identities and an empty
$1,000,000 manual paper account. Telegram account output then reported configured,
reconciled broker cash, separate $1,000 stocks and Bitcoin allocations, no reserved
cash, no positions and zero initial P&L. Private-chat authorization and separate
browser/Autobot service credentials are installed with protected backups.
Account identifiers and secrets are deliberately omitted from this report.

At 14:10 ET, execution health reported healthy automated/manual owners and
configured manual trading; notification polling was healthy and configured.
Coinbase was fresh with healthy retention and zero dropped minute buckets.
The reviewed monitoring helper added the notification API child to the existing
feed/execution checks. HomeOps web and network services restarted successfully;
the collector remained active, and the notification endpoint passed over LAN.
At 14:12 ET, a1347-j's independent watchdog reported HomeOps reachable with zero
failures and no incident. It monitors HomeOps reachability, not each component
directly. No HomeOps backup configuration was changed.

Provisioning fixes `9484aec` and `25ba1ef` preserve unrelated environment syntax
and identify conflicting account roles without disclosing account IDs. Seven
focused helper tests passed locally and on Linux. These operational helper
changes do not replace the installed application revision `c729243`.

An exact user-confirmed paper order, fill reconciliation, activity display and
Telegram trade-event delivery remain unverified. Healthy notification polling
does not establish delivery of a trade event. No test trade was submitted by the
agent. The 16:15 ET stock scan and sustained responsiveness under disk contention
also remain follow-up checks. Earlier unconfigured checkpoints below are history.

## Latest installed checkpoint: full UI release

Revision `c7292434e63ac53523dd2dc7eddfcb1a5aca7fd7` completed installation on
September 30 at 10:13:44 America/New_York. The receipt records database mode,
a verified backup, migration `022_research_inspection`, preserved ledger counts,
and `stock-watch-execution.service` as the Bitcoin execution owner. Recovery is
`/var/backups/stock-watch-releases/20260930T123254Z`; the prior runtime remains
`/opt/stock-watch.before-20260930T123254Z`.

The journal recorded backup completion at 09:13:46, verification continuing until
10:04:04, auxiliary recovery copies, migration 022 at 10:12:59, then “Release
verified” and successful service deactivation at 10:13:44. The later 10:14:09
message about a missing transient systemd unit followed successful completion;
it is not evidence of a failed installation. Do not rerun the installer based
on that message or the monitor's inactive/dead unit state.

At 10:33 ET, all four core services were active. Execution health was healthy,
manual configuration was false, and Coinbase snapshots were fresh with healthy
retention and zero dropped minute buckets. The execution service is enabled;
legacy Bitcoin automation/trading timers are disabled. The scheduled maintenance
job succeeded at 10:24:32 and the worker tick succeeded at 10:33:03. Overall app
health still reports earlier failed stock jobs and a stale operation; a new
successful stock scan has not been established.

LAN requests for Stocks, manual paper and Research exceeded a 12-second check;
Activity returned HTTP 200 but its response did not complete within that limit.
A loopback root request also exceeded eight seconds, and a later execution-health
request timed out after five seconds. The direct independent feed remained fresh.
The web service stayed active with no restarts. Host I/O pressure was elevated
(approximately 78% some / 74% full over ten seconds during the follow-up).
These are unresolved responsiveness findings, not proof of a specific SQL blocker.
Browser interaction, chart controls and complete page verification remain pending.
No paper test orders, strategy activation, account reset or cleanup were performed.

### Follow-up verification, September 30 10:56–11:08 ET

Page responsiveness recovered without a web restart or new application release:
a Stocks HTTP request completed in about 142 ms and manual paper in about 11 ms.
This does not identify or prove resolution of the earlier intermittent stalls.
Read-only Chromium checks at 1440px and 390px covered Stocks, manual paper,
Bitcoin backtesting, Bitcoin Activity and Crypto. All ten navigations returned
HTTP 200, with no JavaScript page errors or horizontal overflow. Screenshots
confirmed the SPY candlestick/volume chart on mobile. The BTC card changed price
and timestamps with stable height under reduced-motion preferences. The manual
workspace clearly showed account setup required, distinct allocations, supported
order controls and unavailable P&L rather than fabricated account values. Browser
verification blocked trading/system mutation requests; no orders were previewed
or confirmed. Additional live checks toggled candlesticks and activity layers,
selected the Bitcoin allocation, and verified Limit/Market/Stop-limit choices
without attempted trading or system mutations. Test elapsed times include intentional rendering waits and are not
endpoint latency measurements.

Worker, dispatcher, exits and maintenance reported successful scheduled runs;
broker reconciliation matched at 10:15 ET. Calendar and CompanyFacts ingestion
also reported success. No newer successful stock scan is established: the next
scheduled scan is September 30 16:15 ET. Old failed/stale operation records have
not been erased or relabelled as successful.

HomeOps originally registered only the main StockWatch page. The reviewed helper
now supports selecting independently ready components and validates their JSON
health state before updating configuration. Three fixture tests verify unrelated
configuration/backup preservation, idempotency, unhealthy-state rejection and
correct API-child registration. Feed and execution checks were installed as
API children of StockWatch, with a protected configuration backup. HomeOps web
and network observer restarted; collector stayed active. Observations at 11:07 ET
show HTTP 200 for feed and execution, approximately 136 ms and 89 ms respectively.
The independent a1347-j HomeOps watchdog is running; its state reported reachable,
zero failures and a fresh observation. It probes HomeOps reachability; direct
per-component probing from a1347-j is not claimed. Notification registration remains
pending because its endpoint reports unconfigured/unhealthy.

The operator confirmed that new manual paper API keys have not yet been generated.
Credential provisioning, exact setup confirmation and end-to-end paper trade tests
therefore remain pending. These are not inferred from successful page rendering.

## Earlier runtime-only installation

At September 29 23:38 ET, runtime-only revision
`80747508849cacd175a11a8326370656a79337e7` installed successfully. The supervised
installer ran from 23:36:27 to 23:38:21, selected `code-only`, recorded no pending
migrations, and created no database backup. Database initialization was skipped.
The previous runtime is `/opt/stock-watch.before-20260930T033641Z`; configuration
and deployment records are under
`/var/backups/stock-watch-releases/20260930T033641Z` (not a fresh database backup).

Post-install verification: web, market-data, execution and manual-paper services
are active; Coinbase reports fresh ticks with healthy retention and zero dropped
minute buckets; automated and manual owners report healthy heartbeats. Manual
configuration is explicitly false. Both legacy Bitcoin timers remain disabled.
The installed receipt confirms the execution owner and preserved ledger counts.
Overall health remains degraded by earlier failed/stale stock operations; host
disk pressure remains elevated. No broker orders or database cleanup were issued.
The new UI/migration 022 remain uninstalled. Active installer polling is no longer
needed; subsequent stock-job recovery and host I/O investigation are separate
follow-up work, not a running backup or migration.

## Full UI release ready for operator installation

The September 29 follow-up verified full release
`c7292434e63ac53523dd2dc7eddfcb1a5aca7fd7` at
`/home/mjm2z/stock-watch-releases/c7292434e63a`. It includes the runtime fixes
and next-phase UI/migration 022. Linux validation passed 96 web tests across
26 suites, eight feed tests, 406 worker tests, type checking, lint (three existing
warnings), production build, wheel packaging and verification of 32,330 files.
The installer preflight passed without changing services or data.

JobWatch autovacuum completed, its jobs table reported zero dead tuples, and its
update counter no longer increased by thousands on idle housekeeping passes.
StockWatch worker, chart and research timer ticks succeeded after the runtime
hotfix. An idle worker tick does not establish that a fresh market scan succeeds;
the earlier failed stock scans and stale operation records remain unresolved.
The host remains I/O constrained; some web health requests timed out during the
Linux build even while the direct feed stayed fresh with healthy retention.
After the build, execution health returned HTTP 200/healthy in approximately
5 ms; manual account configuration remains false.

At this earlier checkpoint the artifact was staged only; it subsequently installed
as recorded above. The reviewed command below is retained for audit, not for
rerunning the completed release. Installation uses the full reviewed
path below, which backs up and verifies data before applying migration 022 and
stops StockWatch services while it works. The earlier two-minute code-only timing
is not an estimate for this migration release. Do not skip its backup or delete
old recovery copies to speed it up.

```bash
ssh -t a1347-m 'sudo systemd-run --unit=stock-watch-release-c7292434e63a --collect /usr/bin/python3 /home/mjm2z/stock-watch-releases/c7292434e63a/deploy/install-reviewed-release.py /home/mjm2z/stock-watch-releases/c7292434e63a'
```

Monitor from this checkout without an active Codex session:

```bash
python3 deploy/monitor-release.py --unit stock-watch-release-c7292434e63a.service --watch
```

After the installer stops, verify its receipt, migration 022, service ownership,
LAN pages, chart controls, live feed and existing automation. Manual configuration
remains a separate operator step. No test orders or account reset are implied.

## Earlier investigation checkpoints

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

At 23:02 ET, a short `pidstat` sample attributed approximately 3.3 MiB/s of
writes to PID 3651026, the user-level `home-ops-backup.service`. It had been
running since September 28 08:33 ET. Its source database was approximately
3.22 GB, its incomplete backup approximately 1.40 GB, and `/proc/3651026/io`
reported approximately 2.71 TB of physical writes. Completed earlier backups
remain present. Repeated online SQLite backup restarts are a plausible explanation,
not directly observed; the copy has no deadline in the inspected backup code.
The user subsequently authorized stopping this backup. At approximately 23:07 ET,
the original attempt was stopped. Its persistent timer immediately launched a
catch-up attempt, which was also stopped. The final MainPID was zero. The current
backup status was atomically recorded as failed/operator-interrupted and
unverified, preserving its run identity. All three completed backup files and
the partial copies were retained. HomeOps monitoring/collector and all four
StockWatch services remained active. The backup timer remains enabled and its
next scheduled run is September 30 around 08:30 ET. The safeguards described
below were subsequently installed without starting another full backup.

The backup process's I/O disappeared from the follow-up process sample, but the
disk remained roughly 95–100% utilized in subsequent five-second samples, with
high I/O pressure and approximately 99 MB dirty memory. Stopping this abnormal
backup removes a demonstrated writer; it has not yet resolved host-wide disk
contention or established that stock execution failures are fixed. Other writes
and pending writeback still require attribution before another long deployment.

A StockWatch source fix avoids acquiring a writer for empty workspace queue
recovery polls. Its regression test holds a competing write lock while both
empty queue scopes return normally. All 406 worker tests passed. This change
is not in installed `6e7120f` or staged `5c374e3`. The feed persistence fix now publishes ticks immediately and moves bounded
minute-aggregate batches to a separate worker thread. Both fixes are included
in the runtime-only release subsequently installed at 23:38 ET.


### Runtime-only remediation, September 29 late evening

HomeOps branch `fix/bounded-self-backup`, revision `740d803`, is pushed. Its
installed backup module hash is
`bf4fceda9ed0a724ec941f8ee70f521ad4500a5b084ec9d6d799a241a7376e47`.
The backup now pins a WAL read snapshot to prevent restarts from concurrent
collection, releases it before verification, has a 15-minute application deadline,
and reports progress/failure. Service limits are 20 minutes start and 30 seconds
stop. The collector, live web service, timer schedule, three completed backups and
previous partial files were preserved. All 120 local tests and four focused Linux
tests passed, including concurrent WAL ingestion. A full production backup has
not yet been run with this fix; fixture success does not establish a new verified
recovery copy. The bounded read snapshot can delay WAL checkpoint progress until
copy completion or cancellation.

The operator's 23:24 ET root I/O sample identified PostgreSQL PID 2645108 as the
largest visible writer (about 3.6 MiB/s average), identified by `ps` as an
autovacuum worker in the JobWatch database. The application database role could
not see its table/progress fields. Read-only table statistics showed about
89 million cumulative `jobs` updates and 5,362 autovacuums, with a live-row
estimate of approximately 5,200. A later active-query sample directly observed
JobWatch lifecycle housekeeping waiting on WALWrite. Its old SQL rewrites all
job active/freshness states each housekeeping pass, even unchanged rows.
JobWatch branch `fix/lifecycle-write-churn`, commit `80ed001`, changes only those
writes and already expired source updates to skip unchanged rows. All 81 tests,
including isolated PostgreSQL regressions, and type checking passed. The user approved installation; the checksum-guarded worker-only hotfix was
installed at 23:34 ET and the worker restarted gracefully as PID 2662890. The
installed source hash is
`4ad20067fe0bf2c221bc4341333b81729c6023cd30054e5292d82c088c4770e4`; the prior
source remains in `src/ingestion.ts.before-893a3a24e563`, and the host has
`lifecycle-hotfix-installed.json`. The web app and database remained online.
Autovacuum has not been disabled or cancelled. The worker heartbeat recovered and processed Spotify/Ashby feeds. An idle
sample left the job-update counter unchanged at 89,153,853. Existing autovacuum
continued and disk utilization remained roughly 92–96% during short initial
samples; host-wide recovery is not yet established.

StockWatch branch `fix/runtime-io` revision
`80747508849cacd175a11a8326370656a79337e7` is pushed and verified at
`/home/mjm2z/stock-watch-releases/80747508849c`. It is based on installed `6e7120f`
and includes feed persistence isolation, idle-queue writer avoidance, extended
SQLite error codes, installer concurrency protection and the chart-cache clock
correction. It excludes migration 022 and new initialization changes. The
installer determines the deployment mode from the actual installed migration
history; with the verified baseline it can install code-only without another
large database backup. Linux validation passed 88 web tests, eight feed tests,
396 worker tests, type checking, lint, production build, wheel packaging and
manifest/preflight verification (32,264 files). The 34 deployment tests passed
locally. It was subsequently installed as recorded at the top of this report; it is
separate from the next-phase UI artifact `5c374e3`.


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

The previous installer has completed. The runtime-only remediation was
installed with the command below. It is retained as an audit record; do not
rerun it to monitor the completed deployment:

```bash
sudo systemd-run --unit=stock-watch-release-80747508849c --collect \
  /usr/bin/python3 /home/mjm2z/stock-watch-releases/80747508849c/deploy/install-reviewed-release.py \
  /home/mjm2z/stock-watch-releases/80747508849c
```

Monitor from the local checkout without an active agent:

```bash
python3 deploy/monitor-release.py --unit stock-watch-release-80747508849c.service --watch
```

The installer prints the deployment plan before stopping services. With unchanged
installed migration history it selects code-only, preserving configuration and
the previous runtime while leaving databases in place. Verify the installed
receipt, LAN access, feed retention/freshness, execution ownership and service
health afterward. This runtime-only installation has completed.

Do not subsequently install the old UI stage `5c374e3`: it predates these runtime
fixes. Re-stage the current main branch for the full UI release after contention
is resolved; its migration 022 still requires the normal verified recovery
backup. Manual trading remains unconfigured until protected credentials and
account setup are confirmed. No paper test draft was confirmed in this iteration.

## Limits and operator prerequisites

Pre-collection manual return history, funding-matched benchmarks, full tax-lot
realized accounting, historical stock membership/corporate-action completeness,
formal uncertainty/DSR/PBO and new ATR/relative-strength rules are not claimed.
System chart inspection does not invent missing historical indicator series.
Legacy stock execution timers remain separate. Telegram's existing parser remains
compatible; expanded browser forms do not imply undocumented Telegram syntax.

The full UI release still needs re-staging, host-health review and operator root
installation. The runtime hotfix receipt and execution-owner health are verified;
stock jobs remain degraded.
Provision protected credentials and confirm manual setup separately. HomeOps
component registration, watchdog verification and paper-order tests remain
explicit post-install checks; a fixture is not production verification.
