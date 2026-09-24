# Application consolidation: a1347-m

## Execution status — 2026-09-24

Migration is **not deployed**. No source services, databases, schedules, DNS,
or backup policies have been changed. Connectivity was restored after switching
Wi-Fi; SSH now succeeds to all four servers. All four reject noninteractive sudo
with "a password is required". The user ran runtime preparation successfully:
Node 24.16.0 and PostgreSQL 16.15 are installed on a1347-m; PostgreSQL listens
on localhost. The user also completed separate app/rehearsal database provisioning.
Production cutover has not started. StockWatch's disabled destination installation
and protected source configuration export are the current administrative gates.
StockWatch's seven production timers are active; do not interrupt market hours.

Prepared locally:

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
part of the move. StockWatch's 34,959,163,392-byte snapshot transfer is still in
progress (16 GiB at 13:07 ET); it is not yet a verified destination recovery point.
The transfer was temporarily paused for isolated performance measurements and
Radar restoration, then resumed. Source backup and live database remain intact.

JobWatch's explicit stable-host allowlist and HomeOps's independent send-only
watchdog transport are implemented in their own repositories, not yet deployed.
The watchdog supports delivery-disabled rehearsals with separate state and a
configurable observer name; existing notification/deduplication behavior remains.
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
