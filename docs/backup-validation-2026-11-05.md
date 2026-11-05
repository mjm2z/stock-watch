# Recovery validation after the November 4 overload

The repaired primary copy timed out during severe memory/disk pressure; the
backup did not reach verification. Maintenance later completed successfully.

The existing backup service uses `--keep 1`. Recovery validation now supports
`STOCK_WATCH_BACKUP_PRESERVE_HISTORY=1`, covering the primary and auxiliary
SQLite exports. It keeps all prior managed exports and logs zero removals until
an independent dual-destination recovery review permits retention again.

`deploy/start-backup-validation.py --queue` is staged with the candidate backup
module and its SHA-256. Run as root on a1347-m. It makes a root-owned copy of the
queue inputs and starts a transient systemd unit, returning immediately. The
queue waits up to 170 minutes for inactive maintenance/APT/checker/backup units,
at least 2 GiB available memory and I/O full-stall avg60 below 10%. A three-hour
systemd bound limits the waiter. It never stops competing jobs.

When ready, it acquires the shared backup I/O lock, checks the exact installed
release/module hashes, preserves rollback copies, installs only backup.py and a
history-preservation/idle-I/O service drop-in, then starts the existing backup
service. Its normal 130-minute service limit remains unchanged. The queue's
success only means launch was requested, not verified recovery.

Progress: `journalctl -u stock-watch-recovery-validation.service -u stock-watch-backup.service -n 20 --no-pager`.
The preservation drop-in remains until coverage and retention are explicitly
reviewed. Rollback modules are under `/var/backups/stock-watch-module-repair/`;
restore only while backup is inactive and reconcile subsequent edits first.

Validation: seven backup tests, including retained unverified history for primary
and auxiliary destinations; six deployment tests, including unknown/active unit
states and pressure gating. Remote staged hash and Python syntax checks passed.
Live candidate installation, backup completion and dual-destination restoration
remain pending administrator launch. Unrelated development changes are preserved
in the separate original checkout.
