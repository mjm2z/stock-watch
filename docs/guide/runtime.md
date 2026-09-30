# Runtime, deployment and recovery

[Application guide](../../README.md) · [Current release report](../next-phase-release.md)

The web process serves port 3001 on a1347-m. Separate supervised services own
Coinbase market data, Bitcoin execution and manual paper instructions. The
existing research worker handles serialized expensive jobs; chart collection has
its own bounded queue. Existing stock timers remain a documented boundary rather
than being silently replaced by a UI release. a1347-j remains the independent
watchdog and must not restart its retired StockWatch application.

Component checks are `/api/health/market-feed`, `/api/health/execution` and
`/api/health/notifications`. They distinguish observation freshness, execution
owner heartbeat and notification activity. Installation does not prove manual
credentials, Telegram authorization or notification delivery. HomeOps registration
must follow healthy endpoint verification and independent a1347-j checks.

The reviewed release process is:

1. Review only task-owned diffs. Run worker/web/feed suites, type checking, lint,
   production build and isolated browser checks. No live test order is implied.
2. Commit and push the reviewed revision. `deploy/stage-reviewed-release.sh`
   builds/tests on Linux, produces the worker wheel and verifies the manifest.
3. Run the installer's read-only check against the exact stage. An already-running
   healthy installer retains ownership; do not launch another or move its files.
4. With operator root access, install outside the guarded regular market window.
   Back up before additive migration 022, including auxiliary manual/feed/history
   stores and retained research artifacts. Preserve credentials and identities.
5. Drain the previous execution owner, reconcile outstanding orders, then start
   exactly one replacement. Verify receipt revision, LAN views/SSE, owner health,
   restart behavior, existing automation and independent monitoring.

The installer writes a receipt only after verification. A staged artifact, active
installer unit or successful command exit is not alone proof of operational
manual trading. Report installed revision separately from source/documentation
commits. Credentials and setup confirmations may remain operator-only steps.

The new installer holds a process lock and also checks active supervised release
units, including older installers that predate that lock. It refuses a competing
installation before changing runtime files or stopping services.

Use `journalctl -fu <release-unit>.service` to observe an authorized installer
without continuous agent polling. Database backup and verification can be long;
visible progress is not a reason to interrupt them. Check resource use and
journal phase before diagnosing a stall. Do not treat a pre-existing database
lock as proof that the new release caused a failure.

### Monitoring a quiet installer

From the local repository, run:

```bash
python3 deploy/monitor-release.py --watch
```

The default unit is the ongoing `6e7120fe1e9d` installation. For a future release,
pass `--unit stock-watch-release-5c374e316dd9.service`. This read-only monitor uses
one SSH connection, samples every 30 seconds, and needs no Codex session. Ctrl-C
stops only the monitor. Omit `--watch` for one snapshot. It shows unit state, the
actual installer process tree, host disk rates, I/O pressure and the last log.
Disk rates appear after the second sample and are explicitly host-wide: they
cannot establish an installer completion percentage or ETA. A `D` process state
means a kernel I/O wait, not proof of failure. A stopped unit still requires
receipt and service verification.

At September 29 12:42 ET, the earlier installer had reached `rsync` into
`/opt/stock-watch`, despite its last journal line still describing auxiliary
backup. The host's APPLE HDD HTS541 is rotational storage; short measurements
showed approximately 90–98% disk utilization and substantial I/O pressure.
Unprivileged per-installer byte counters were unavailable. Avoid extra builds,
large directory scans or backup jobs on this disk while installation finishes.

Future optimization work, **not applied to the active installer**: add timed
phase boundaries, auxiliary-backup callbacks and rsync progress; package a
minimal runtime instead of copying development dependencies and build caches;
prepare consistent verified recovery data before the short final writer drain;
and evaluate moving application data and releases to SSD storage. Preserve
database consistency, recovery verification and single execution ownership.
Do not skip a migration backup to obtain a faster deployment. A backup on the
same physical disk adds read/write contention; moving it requires an explicit
recovery design rather than changing the destination mid-installation.

### Capturing database contention

`deploy/record-database-locks.py` samples the main database and its WAL/shared-memory
file locks once per second for five minutes (maximum one hour with `--seconds`).
It reports changed locks and a 30-second heartbeat as JSON lines, including PIDs,
program names, byte ranges and host I/O pressure. It reads filesystem metadata
and `/proc`; it never opens a database connection. Sampling can miss short locks,
and a write lock alone does not establish that a job was blocked for its timeout.
Normal execution ownership lock files must not be deleted.

An identical helper was copied to `/home/mjm2z/stockwatch-record-locks.py` and
validated against an isolated Linux fixture. To capture a recurring failure:

```bash
ssh -t a1347-m 'sudo python3 /home/mjm2z/stockwatch-record-locks.py --seconds 300 | tee /home/mjm2z/stockwatch-locks.jsonl'
```

Root is needed to stat protected database paths, not to modify them. Run during
the affected workload; an idle-period capture cannot exclude contention during
a scan. Ctrl-C stops only the recorder. The saved file contains diagnostic
metadata, not SQL rows or credentials.

The source now retains `sqlite_errorcode` and `sqlite_errorname` in exception-chain
diagnostics. Tests reproduce both `SQLITE_BUSY` and `SQLITE_BUSY_SNAPSHOT`, which
otherwise share the same error text. This diagnostic change is not present in
installed `6e7120f` or previously staged `5c374e3`; it requires a future reviewed
artifact. It changes no timeout, order handling, qualification or retry behavior.

Rollback retains databases, research artifacts, reservations and uncertain
orders. Reconcile before resuming ownership. Do not roll back to a binary that
cannot understand pending notional instructions, strip new request fields, or
start both a timer and daemon owner. Never reset a broker account to make a
rollback easier. A current operator pause remains a pause, and existing position
exit management must continue through policy/data outages.

Protected setup still requires the manual paper key/secret, separate browser and
Autobot service tokens, and allowed Telegram user/chat IDs. Do not paste secrets
into chat. Confirm account setup and any test trade through their own exact drafts.
