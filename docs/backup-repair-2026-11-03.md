# Backup producer repair, November 3, 2026

The installed cd89d63 backup completed the primary database, then timed out while
verifying the experiment-evidence database. The offhost primary recovery therefore
can be newer than the last successful complete service execution. Auxiliary
exports are not included in the existing Home Ops primary-database offhost pull.

This candidate increases the SQLite source and destination page caches to 64 MiB
to reduce alternating disk access and identifies each database in progress output.
The backup lock, consistent WAL snapshot, integrity check, deadline and publication
rules remain in force. Six backup tests pass, including concurrent WAL writes and
interruption preserving the previous snapshot. Two installer guard tests pass.
Production throughput improvement is not yet verified.

`deploy/repair-backup-module.py` is a backup-only installer for the exact installed
revision and original module SHA-256. Stage it with the reviewed `backup.py` and
its `backup.sha256`. Run it as root after review. It refuses active backup jobs,
unknown revisions and unknown module hashes, and preserves both installed copies
under `/var/backups/stock-watch-module-repair/`. It does not restart application
services or launch a competing backup.

Deployment is blocked by host administrator access: noninteractive sudo requires
a password. After installation, wait for the current fleet backup to finish,
start `stock-watch-backup.service`, and verify the primary and all auxiliary
exports before claiming complete application recovery. Preserve unresolved
history and do not reduce retention based on the primary-only offhost receipt.
