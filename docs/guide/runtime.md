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

Rollback retains databases, research artifacts, reservations and uncertain
orders. Reconcile before resuming ownership. Do not roll back to a binary that
cannot understand pending notional instructions, strip new request fields, or
start both a timer and daemon owner. Never reset a broker account to make a
rollback easier. A current operator pause remains a pause, and existing position
exit management must continue through policy/data outages.

Protected setup still requires the manual paper key/secret, separate browser and
Autobot service tokens, and allowed Telegram user/chat IDs. Do not paste secrets
into chat. Confirm account setup and any test trade through their own exact drafts.
