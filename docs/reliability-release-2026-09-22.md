# News revisions and paper exit timing — September 22, 2026

Installed on a1347-j September 22, 2026, at 10:58:32 AM Eastern.
The next scheduled scan and first actual exit still require forward verification.

Mike explicitly selected five minutes before close, including early closes.

## Behavior

Updated Alpaca articles no longer abort a scan. Migration 014 retains original
article rows and links and adds immutable content revisions, revision-specific
symbol/sentiment links, ingestion membership, and scan snapshots. The collector
freezes one eligible revision per article, including an explicit empty snapshot.
Replay reads the pinned revisions. Provider publication and update timestamps
must be at or before the signal cutoff. Changed content without a newer provider
timestamp becomes available only from local observation time. Capture time is
retained separately; provider-time selection does not claim independent proof
that a provider revision existed before collection.

New historical-news runs use a new version and pinned ingestion membership.
Historical signals exclude edits after the exchange close and do not blend in
unrelated later ingestions. Original completed feature/outcome/backtest records
are not rewritten. A replay of a legacy scan without a news snapshot uses its
original article table, with the update-time check.

Migration 015 introduces a separately versioned exit execution policy. The
installer explicitly activates `near-close-v1` for `sp500-long-paper-v2`, covering
its existing unclosed and future lots. Ranking configuration and allocation limits
stay unchanged. The horizon session is retained; intended submission becomes
five minutes before that session's exchange close. `target_session_close_at`
retains the reference close separately, and schedule changes are audited.

`stock-watch-exits.timer` runs `exit-once` each minute independently of scanning
and forward evaluation. It uses the cached exchange calendar, skips nontrading
hours, and reports missing calendar coverage as an error. A fresh broker clock
must confirm the regular session before a new managed sell is submitted.
Broker-ID lookup happens first, so an already accepted order is reconciled even
outside the submission window. A missed close waits for a subsequent regular
session and produces a late-submission audit event.

Paper fills determine actual returns. Standard research labels still use the
horizon closing price; they are not a simulation of the 3:55 PM fill. This release
removes routine after-close submission but does not claim exact closing fills,
financial outperformance, or complete execution-matched backtesting. Those remain
part of the baseline research work described in the effectiveness review.

Canceled/rejected exits remain exposed in the ledger and cause the exit job to
report that reconciliation is needed. Partial fills preceding cancellation are
preserved. The release does not blindly resubmit terminal orders or pretend the
remaining position is closed. A future recovery workflow can create audited
replacement orders after resolving broker state.

The dashboard includes the exit timer in execution health and shows full target
timestamps. Existing application changes from the September 17 releases are
included in the staged source/build, as they were already present in this workspace.

## Installation and verification

Staged path: `/home/mjm2z/stock-watch-reliability-20260922`.

```bash
sudo bash ~/stock-watch-reliability-20260922/deploy/install-reliability-root.sh
journalctl -u stock-watch-reliability-install --no-pager -n 40
```

The installer verifies the tested SHA-256 manifest and package lock, preserves
source/installed-worker/web-build rollback copies, stops timers, and waits for
active jobs and backups to finish. Migration DDL and version stamps commit atomically. It applies additive migrations, switches the
build, verifies HTTP routes, activates the exit policy, and enables the exit timer.
It restores the previously active timers. It neither replays old failed scans nor
submits an order directly. Existing automation resumes after installation.

Failure restores prior code/build and removes a policy newly activated by that
attempt. Additive tables/columns and captured audit evidence remain. If an exit
service cannot finish, rollback stops rather than switching code underneath a
broker request. The wrapper is for first installation; it leaves an already
activated policy untouched. No full copy of the large production database is made; the
existing verified database backup flow remains in place.

After installation, verify:

- `stock-watch-exits.timer` is active and its minute ticks succeed.
- The MRK five-session lot has a September 24, 3:55 PM Eastern submission target
  and a separate 4 PM reference close, once schedules have been refreshed.
- The next normal scan succeeds and records revisions/snapshots; old failed
  scans remain historical evidence.
- Paper positions reconcile, and no fill or closed trade is inferred from an
  intent or a scheduled time.

Host `sudo` requires Mike's password. The release is not live until installation
and these production checks succeed.

## Verification completed

- 258 Python worker tests passed locally and on a1347-j, including news revision
  replay, future edits, removed ticker associations, ingestion-pinned historical
  selection, populated-schema upgrade, failed-migration rollback, early closes,
  off-hours deferral, stale clocks, zero-fill acceptance, partial cancellation,
  and reconciliation after a lost submission response.
- 43 dashboard tests passed locally and on Linux; TypeScript checks and the
  final Linux production build passed. Existing console warnings in the legacy
  AI integration remain unrelated to this release.
- An isolated smoke check confirmed idempotent policy activation and exercised
  the read-only release verifier against a SQLite fixture.
- Shell syntax and whitespace checks passed. The staged SHA-256 manifest covers
  437 source, test, deployment, and build files and verified successfully.
- Production installation and the next scheduled scan/actual exit remain to be
  verified after administrator installation. No claim of improved returns is made.

## First installation attempt and correction

The September 22 10:56 AM Eastern attempt applied migrations 014/015 and preserved
all 2,290 original articles, but the web service could not start: its systemd
namespace requires `/opt/stock-watch/.next/cache`, which the installer had
excluded without recreating. The installer restored the previous source/build
and timers. The dashboard recovered; exit policy activation was not reached.

The corrected installer creates that cache directory with `stock-watch` ownership
before starting the web service and allows 30 startup retries. Ten deployment
contract tests pass locally, including a regression check of this ordering and
the web unit's required path. Existing additive migrations can be reused on retry.
The corrected script is staged; installation must be retried and verified.

## Successful installation and live checks

The corrected installation completed at 10:58:32 AM Eastern. The read-only
verifier confirmed original article preservation and active `near-close-v1`.
The exit timer is enabled, and live checks through 1:41 PM Eastern show successful
minute ticks. The portfolio API now records MRK's five-session submission target
as September 24 at 3:55 PM Eastern and MSFT's as September 28 at 3:55 PM Eastern.
All eight MRK/MSFT lots are open with filled entry orders.

Worker, dispatcher, maintenance, and exit timers report active with successful
latest completions. The latest recorded broker reconciliation is matched.
The dashboard still reports this morning's pre-release scan failure; no new scan
has run since installation. The next scheduled scan is September 22 at 4:15 PM
Eastern. Neither the news fix's next live collection nor an actual managed exit
has yet been observed, so those remain explicit follow-up checks.

Rollback source/build: `/var/backups/home-ops-code/stock-watch-reliability-20260922T145829Z`.
