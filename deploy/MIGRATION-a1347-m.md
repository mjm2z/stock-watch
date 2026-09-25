# Application consolidation: a1347-m

## Execution status — 2026-09-25

Production cutover **started after market hours on September 25**. JobWatch's
source web and worker LaunchAgents are disabled/unloaded; a final consistent
15-table dump is retained on the M4 and transferred to a1347-m. All restored
table fingerprints matched; target web and worker are enabled and running.
LAN and loopback readiness, stale-worker HTTP 503 before activation, healthy
worker HTTP 200 afterward, and supervised web restart passed. JobWatch is now
authoritative at http://192.168.4.35:3020 (DNS handoff is still pending).
Do not restart its source without carrying authoritative data back.
Radar's managed cron block was backed up and removed, jobs drained, and source
server stopped. Its final snapshot and mutable-file archive are in progress in
`radar-final-20260925T195808` on a1347-d; shared PostgreSQL/Data Engine remain up.
HomeOps and StockWatch sources, DNS and backup policies are unchanged.
Connectivity was restored after switching
Wi-Fi; SSH now succeeds to all four servers. All four reject noninteractive sudo
with "a password is required". The user ran runtime preparation successfully:
Node 24.16.0 and PostgreSQL 16.15 are installed on a1347-m; PostgreSQL listens
on localhost. The user also completed separate app/rehearsal database provisioning.
StockWatch's disabled destination installation
and protected source configuration export have completed successfully.
StockWatch's seven production timers are active; do not interrupt market hours.

Verified at 11:00–11:07 ET on September 25: app-access service is enabled and
active, and finalized-backup directory ACL grants mjm2z read/traverse only.
Temporary fixed-response probes passed on all four app ports from loopback,
the M4, and a1990; probes were then stopped. Nontrusted-source rejection was
subsequently verified using a1990's IPv6 link-local connection: a control port
responded while the protected app port timed out. Trusted IPv4 and IPv6 loopback
remained reachable. Those probes were stopped. PostgreSQL remains loopback-only.

Final-cutover tooling added: source JobWatch work-lock drain; root StockWatch
freeze/export and guarded publication; compressed snapshot transfer with full
roundtrip checksums. Eighteen migration regression tests pass. The real StockWatch
rehearsal database compressed from 34,959,163,392 to 4,780,602,548 bytes in 695s;
compression plus decompression verification took 923s. Original files remain.
StockWatch helpers preserve exact enabled timers and persistent timer timestamps;
they have not yet frozen or published production StockWatch data.

Backup/DNS preparation completed at approximately 11:30 ET:

- a1347-d has restricted read-only SSH access to three separate target backup
  directories, limited to source IP 192.168.4.33. Existing SSH keys were preserved;
  no private key left a1347-d. The target host key was obtained over authenticated
  SSH and pinned. Shell commands, write-mode rsync, and directory traversal were
  rejected in live checks. HomeOps's existing absolute backup path is translated
  safely within its restricted export root. Current production pulls still use
  their original hosts; target StockWatch correctly has no finalized backup yet.
- Both PostgreSQL rehearsal dumps were pulled through the new restricted key and
  restored into an isolated, password-protected PostgreSQL 16 cluster on a1347-d
  at loopback port 55439. JobWatch's 15 and Radar's 22 table fingerprints all
  matched. The cluster is now stopped; production PostgreSQL on 5432 stayed up.
  HDD checkpoint flushing took slightly over the initial 60-second shutdown wait;
  clean shutdown was confirmed in its log, and the helper now waits up to 300s.
- `app-postgres-backups.py` and a disabled 08:30 UTC create timer are installed
  on a1347-m. A 09:15 UTC pull cron entry is staged, NOT installed, on a1347-d
  (which has no user linger). Explicit cutover markers gate both commands; the
  create command's refusal was verified. New snapshots publish only after
  source fingerprints, checksums, and archive-listing checks. Pulls reject stale
  snapshots. No backup pruning is enabled; a 50 GiB free-space reserve applies.
  Routine validation passed against both real rehearsal archives and is reported
  distinctly from the isolated full restore test. Scheduling activation and its
  first production run remain cutover tasks.
- `homeops-relocated-configs/` on a1347-m contains a private preview generated
  from all five ACTUAL collector configs and the current server config. All
  credentials and state paths match their sources; relocation is idempotent.
  Preview includes eight sites and 21 backup policies, including local/off-host
  PostgreSQL backup status collection. Source hashes allow drift checks before
  publishing. No live config or collector state was replaced.
- `switch-app-dns-root.py` is staged on a1990. Dry-run diff changes only logs,
  stockwatch, jobwatch, and radar home.arpa records to a1347-m, preserving Sandbox
  records and upstream resolvers. Default execution is review-only; `--apply`
  requires root, an outside-market-hours window, and successful destination app
  and worker readiness. Existing unit is backed up; restart failure rolls back.
- `postgres-final-restore.mjs` is staged on a1347-m. Unlike the rehearsal tool,
  it accepts only the two intended production databases, refuses market hours,
  active destination services, existing activation markers, or nonempty databases,
  and checks app schema, dump checksum, and restored row fingerprints. Operator
  must first verify source writers are stopped and pass `--source-writers-stopped`.
  This script has not restored either production database yet.
- All four original applications passed health/page checks after this work;
  StockWatch's seven source timers remain active, target app units remain inactive,
  and logs.home.arpa still resolves to a1990. Fourteen migration regression tests
  and the HomeOps relocation regression passed. Unrelated HomeOps edits remain
  outside these migration commits.

Prepared locally:

- `stage-app-runtime.mjs`: preserves source env settings and credentials while
  changing only target database/address settings. Protected runtime configs now
  exist under `~/.config/{job-watch,app-demand-radar}/runtime.env` on a1347-m,
  mode 600 inside mode-700 directories. No app starts or database writes.
  Source configs are retained in private staging. Recheck source changes before
  final cutover. Rehearsed code is installed at `~/job-watch` and
  `~/app-demand-radar`; all 29 service/timer definitions are installed but disabled
  (oneshot jobs are static), with no cutover markers. The guarded
  `install-staged-app-units.sh` performed this staging without starting jobs.
- `prepare-app-access-root.sh`: staged for administrator execution on a1347-m;
  preserves a root-only copy of existing firewall configuration, installs ACL
  support, grants directory traversal for finalized StockWatch backup pulls, and
  installs a dedicated nftables table for the four app ports. Loopback and the
  trusted LAN remain allowed; other incoming TCP access to those ports is dropped.
  A separate system service persists these rules; no global ruleset flush, UFW
  activation, or unrelated-port changes. This setup has now completed. The initial command was accidentally
  pasted onto an earlier command and did not run. Inspection showed UFW is
  disabled, so the script was corrected before retry. No apps or DNS changed.
- `verify-artifact-export.py`: checks all file sizes and SHA-256 hashes against
  the export manifest, rejecting missing, extra, nonregular, or changed files.
  Tests include same-size corruption and missing/extra artifacts.
- `render-app-services.py`: renders 29 disabled JobWatch/Radar service/timer files
  without installing them. Staged bundle `service-units-v2` passes systemd unit
  validation. All units require an explicit per-app cutover marker. Radar's
  actual source cron runs in UTC (Debian cron ignores CRON_TZ); explicit UTC
  timers preserve those execution times and do not catch up missed runs.
  Jobs retain their script arguments, log paths, Reddit limit, cleanup dry-run,
  and scheduled report notification behavior. No timer or worker was activated.
  Create protected runtime configs and log directories, verify final restored data,
  restrict LAN access, and drain source writers before creating markers/enabling.
- `export-stockwatch-artifacts-root.py`: read-only rehearsal export of the
  separate artifact directory with per-file SHA-256, source-change detection,
  protected permissions, and refusal to overwrite earlier exports. Nonregular
  files fail closed. Requires root on a1347-j; never stops production services.
- `export-stockwatch-config-root.py`: read-only export on a1347-j of the protected
  environment, configured data-path inventory, and exact installed/enabled/active
  service definitions. No service stops or database changes. Staged under
  `~/app-migration-20260924/`; refuses replacing an earlier export.
- `run-homeops-rehearsal.py`: uses a disposable copy on loopback port 19100,
  without retention, ingestion credentials, monitoring, or notification threads.
- `provision-app-databases-root.py`: create non-admin jobwatch/radar roles,
  empty production and rehearsal databases, and protected generated credentials.
  Refuses existing roles, databases, or credentials rather than replacing them.
- `postgres-migration-snapshot.mjs`: consistent custom-format dump plus
  primary-key-ordered row-content SHA-256 fingerprints from the same exported
  PostgreSQL snapshot, with UTC serialization. Tables without primary keys use
  bytewise row ordering. Current manifest format is 3; earlier rehearsal artifacts
  are retained but must not be used with the current restore verifier.
- `postgres-rehearsal-restore.mjs`: verifies the transferred dump checksum,
  restores only an empty loopback rehearsal database in one transaction, and
  verifies all table fingerprints. Production databases are explicitly refused.
- `prepare-app-host-root.sh`: host-checked a1347-m infrastructure preparation;
  installs pinned Node 24.16.0 and Ubuntu PostgreSQL 16/Python venv packages.
  Refuses an existing PostgreSQL cluster or conflicting runtime links. Does not
  migrate data, open ports, or change application services. Requires root.
- `bootstrap-a1347-j.sh SOURCE stage-only`: install code and disabled units
  on a fresh target, without creating configuration/database or starting services.
  Refuses existing application directories or units. The default `normal` mode
  retains existing bootstrap/update behavior. A partially failed stage must be
  inspected before retry; never delete an existing deployment to bypass the guard.
- `sqlite-migration-snapshot.py`: consistent SQLite backup, integrity check,
  table counts, FK-violation baseline, user version, SHA-256 manifest, and transfer
  verification. Does not prune, stop writers, restore, or activate anything.
- Regression tests for WAL contents, historical notes, source preservation,
  changed snapshot rejection, and recovery-point overwrite protection.

Rehearsal progress: JobWatch's 15 tables restored into `jobwatch_rehearsal` with
all row fingerprints matching the format-3 source snapshot. Linux build, dashboard,
jobs/searches APIs, supervised restart, readiness HTTP 200, and stale-worker
HTTP 503 passed. No source collection or worker was started on the target.
HomeOps snapshot (1,109,602,304 bytes) verified on both source and destination,
SHA-256 `998290b2ba7ee3c86899224b31cb27a5cf965e4d0a002e8decd795689d03c0b9`,
with no FK violations. HomeOps's historical overview, logs, backup runs, network
history, and dashboard passed against a separate working copy. Dashboard latency
was 1.6–1.7 seconds without bulk transfer versus 1.3 seconds on a1990; concurrent
bulk copy caused 18-second responses and an earlier 30-second timeout. Avoid
overlapping large migration copies/restores during latency acceptance checks;
normal workload/backup contention still needs observation before retiring sources.

Radar's 22 tables restored into `radar_rehearsal` with all row fingerprints
matching. Its staged frontend build, 82 backend tests, and all 28 page/API smoke
checks passed on loopback port 15210. No collectors or notification jobs ran.
Existing locked
dependencies report three high frontend advisories and were not upgraded as
part of the move. StockWatch's 34,959,163,392-byte snapshot transfer completed.
Full SQLite integrity/table/FK checks passed on a1347-m (zero FK violations),
and its SHA-256 matches the independent source checksum on a1347-d:
`6203b6192472e699385d84097119905444b7521a18bc8245c37603384da8ebc6`.
An isolated loopback dashboard and six read-only APIs (overview, portfolio,
operations, signals, backtests, research) returned HTTP 200, under one second
each. The rehearsal server was stopped afterward; no worker/broker credentials
or schedules were supplied.
Source backup and live database remain intact. The protected source inventory
also contains 10,381 artifact files totaling 2,655,719,937 bytes; these need their
own final export after writers stop. The separate rehearsal artifact export
completed on a1347-j and transferred successfully to a1347-m. All per-file
destination checksums and the manifest checksum passed. This newer rehearsal contains 10,512 files and
2,665,607,415 bytes; source manifest SHA-256 is
`c44fa8a305f5e30f137d6ee3da7f540918834f89e06ef7f295279db67da455e6`.
Source configuration
and exact deployed system unit definitions have been copied to protected staging.
Destination `/opt/stock-watch` is built, and its web service and timers remain
disabled/inactive. Seven source timers remain active on a1347-j.

JobWatch's explicit stable-host allowlist and HomeOps's independent send-only
watchdog transport are implemented in their own repositories, not yet deployed.
The watchdog supports delivery-disabled rehearsals with separate state and a
configurable observer name; existing notification/deduplication behavior remains.
Independent watchdog code is now staged at `~/home-ops-watchdog` on a1347-j,
with protected send-only credentials and `~/.config/home-ops/watchdog-migration.json`.
Notification-disabled rehearsal detected both reachable and unreachable endpoints.
Production config still has `delivery_enabled=false`; no notification was sent.
The proposed system unit requires a cutover marker AND the transferred historical
state file. It remains staged, not installed or activated. At cutover stop the old
watchdog, carry over its final state, then enable delivery and the new service.
HomeOps now has a pure idempotent relocation helper, generator `--app-host a1347-m`
option, and configurable StockWatch backup source. All 69 Python 3.12 tests pass.
At cutover, apply the helper to actual protected live configs, preserving secrets
and collector state; persist `~/.config/home-ops/app-host.json` on the generator
machine with `{"machine":"a1347-m"}` so future generation retains the new host.
No live config was changed by these tests.

Radar's deploy script now preserves mutable JSON configuration, reports, backups,
and existing credentials; it seeds only missing defaults and does not prune old
releases unless explicitly requested. Its host bind is configurable. A real-rsync
temporary-directory preservation fixture passes. The default deployment target
remains a1347-d until actual cutover; update it and deployment docs at that time.

## Approved destination and boundaries

Move JobWatch (M4), App Demand Radar (a1347-d), HomeOps (a1990), and StockWatch
(a1347-j) to a1347-m in that order during one maintenance window outside market
hours. Stage/rehearse beforehand. Preserve all application history and mutable
files; no reseeding or semantic upgrades during migration.

Keep Data Engine and off-host backups on a1347-d; Sandbox/home controls and DNS
on a1990. Keep existing Autobot, Notes bot, and Ollama on a1347-m. Repurpose
a1347-j for an independent watchdog with a local send-only notification transport,
not dependent on a1347-m. Preserve watchdog incident/delivery state.

Stable names on a1347-m (192.168.4.35): logs.home.arpa:9100,
stockwatch.home.arpa:3001, jobwatch.home.arpa:3020, radar.home.arpa:5210.
Narrowly patch DNS and host/origin allowlists. Restrict app access to loopback
and 192.168.4.0/22; PostgreSQL stays loopback-only. Do not redirect Sandbox or
Data Engine clients. Preserve existing physical-machine IDs/history in HomeOps.

## Required remaining work

1. Inventory live deployed revisions, privileged configuration/data paths,
   schedules, in-flight jobs, backup sizes, and mutable files. Preserve unrelated
   HomeOps work. Verify root access on hosts that need system changes.
2. Prepare target runtimes, separate supervised app services, protected configs,
   LAN access controls, PostgreSQL databases/roles, backup exporters, and the
   independent watchdog. Stage without production writers or notification sends.
3. Rehearse restores and representative workloads: at least 50 GB free after
   staging/backups, at least 1 GB available RAM, no OOM or sustained swapping.
   Measure downtime budget, including the roughly 33 GB StockWatch backup and
   HDD/Wi-Fi transfer. If a gate fails, keep that app on its source.
4. For each cutover, disable source schedules, drain work, stop web writes,
   snapshot, transfer, restore, and verify before enabling any target writer.
   Preserve PostgreSQL schemas, sequences, and full history. Keep Radar's mutable
   watchlists/reports and existing cleanup dry-run behavior. Do not stop shared
   PostgreSQL on a1347-d. Preserve HomeOps collector queues/cursors/tokens and
   merge server state without overwriting a1347-m's existing collector state.
5. StockWatch: capture exactly the enabled timer set; reconcile pending paper
   orders and dispatch state. Copy all configured data artifacts and secrets
   using protected paths. Never run source and destination workers together or
   enable previously disabled strategies/timers.
6. Update HomeOps generator/live monitoring, collector endpoints, affected
   Autobot clients, app deployment scripts, and DNS. Move off-host backup pulls
   to a1347-m and add verified JobWatch/Radar PostgreSQL backups on a1347-d.
   Do not prune earlier recovery points or treat file presence as backup success.
7. Verify LAN and localhost access, supervised restart, worker staleness HTTP
   failure, collector spool draining, single execution of jobs, off-host restore,
   and existing services. Observe the next full trading day before acceptance.
   Commit/push only reviewed migration changes and record deployed revisions.

## SQLite snapshot usage

Run as the database owner, using new protected output paths with sufficient
space. These examples do not stop writers; explicitly drain/stop all writers
first for a final cutover snapshot. Live snapshots are suitable for rehearsals.

```sh
python3 deploy/sqlite-migration-snapshot.py create SOURCE.db SNAPSHOT.db SNAPSHOT.json
python3 deploy/sqlite-migration-snapshot.py verify SNAPSHOT.db SNAPSHOT.json
python3 deploy/sqlite-migration-snapshot.py inspect EXISTING_FINALIZED.db NEW_MANIFEST.json
python3 -m unittest discover -s deploy -p 'test_sqlite_migration_snapshot.py'
```

Verify the transferred snapshot against the source-created manifest before
opening it with application processes. Also inventory/checksum non-database
artifacts. A manifest from a rehearsal is not sufficient for final cutover.
Failures may leave partial output: never activate output lacking a successful
verification. The tool intentionally does not delete failed or existing files.

## Rollback

Keep source data and migration snapshots at least 30 days and until acceptance.
Before target writes, restart only the original authoritative instance if needed.
After target writes, first stop target writers, export the new authoritative data
back to the source, verify it, and reconcile queues/orders/delivery state. Never
restart a stale original database after target writes. Update DNS only alongside
the authoritative-service switch. Never silently discard post-cutover history.
