# Application consolidation: a1347-m

## Execution status — 2026-09-24

Migration is **not deployed**. No source services, databases, schedules, DNS,
or backup policies have been changed. Connectivity was restored after switching
Wi-Fi; SSH now succeeds to all four servers. All four reject noninteractive sudo
with "a password is required". The user ran runtime preparation successfully:
Node 24.16.0 and PostgreSQL 16.15 are installed on a1347-m; PostgreSQL listens
on localhost. Separate app/rehearsal database provisioning is staged but pending
administrative execution. Production cutover has not started.
StockWatch's seven production timers are active; do not interrupt market hours.

Prepared locally:

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

Rehearsal progress: JobWatch backup contains 15 tables and its Linux build passed.
HomeOps snapshot (1,109,602,304 bytes) verified on both source and destination,
SHA-256 `998290b2ba7ee3c86899224b31cb27a5cf965e4d0a002e8decd795689d03c0b9`,
with no FK violations. Radar's staged frontend build and 82 backend tests passed; existing locked
dependencies report three high frontend advisories and were not upgraded as
part of the move. Radar fingerprinting and StockWatch backup transfer are in
progress; check completion and verify before using either artifact.

JobWatch's explicit stable-host allowlist and HomeOps's independent send-only
watchdog transport are implemented in their own repositories, not yet deployed.
The watchdog supports delivery-disabled rehearsals with separate state and a
configurable observer name; existing notification/deduplication behavior remains.

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
