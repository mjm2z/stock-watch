#!/usr/bin/env python3
"""Offline compaction after migration 023, called by the reviewed installer.

The installer must first verify a fresh full recovery copy and stop/drain writers.
VACUUM preserves the original database transactionally if interrupted; no file swap.
"""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time


def compact(database):
    database = Path(database)
    with sqlite3.connect(database, timeout=3) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version='023_company_fact_storage'").fetchone():
            raise RuntimeError('Required storage migration is not installed')
        before = connection.execute('PRAGMA page_count').fetchone()[0] * connection.execute('PRAGMA page_size').fetchone()[0]
        # Conservative headroom for the rebuilt DB, SQLite temporary space and WAL.
        required = before * 2 + 5*1024**3
        if shutil.disk_usage(database.parent).free < required:
            raise RuntimeError(f'Compaction requires {required} free bytes; migrated data remains intact, compaction pending')
        counts = tuple(connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                       for table in ('company_fact_observations','company_fact_contents'))
        checkpoint = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
        if checkpoint[0]:
            raise RuntimeError('Database readers/writers remain active; compaction aborted')
        start = last = time.monotonic()
        def progress():
            nonlocal last
            now = time.monotonic()
            if now-last >= 30:
                print(json.dumps({'phase':'compacting/verifying','elapsed_seconds':round(now-start)}),flush=True)
                last=now
            return 0
        connection.set_progress_handler(progress,10000)
        print(json.dumps({'phase':'compacting','database_bytes_before':before}),flush=True)
        connection.execute('VACUUM')
        if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise RuntimeError('Compacted database failed integrity check; services must remain stopped')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise RuntimeError('Compacted database failed foreign-key check')
        after_counts = tuple(connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                             for table in ('company_fact_observations','company_fact_contents'))
        if counts != after_counts:
            raise RuntimeError('Document counts changed during compaction')
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        after=connection.execute('PRAGMA page_count').fetchone()[0]*connection.execute('PRAGMA page_size').fetchone()[0]
        result={'database_bytes_before':before,'database_bytes_after':after,'reclaimed_bytes':before-after,
                'observations':counts[0],'unique_contents':counts[1]}
        print(json.dumps(result),flush=True)
        return result


if __name__ == '__main__':
    database=Path(sys.argv[1]).resolve()
    if database != Path('/var/lib/stock-watch/stock-watch.db'):
        raise SystemExit('Only the production StockWatch database is supported by this entry point')
    units=subprocess.check_output(['systemctl','list-units','--type=service','--state=running,activating','--no-legend','--plain','stock-watch-*'],text=True)
    active=[line.split()[0] for line in units.splitlines() if line.split() and not line.split()[0].startswith('stock-watch-release-')]
    if active:
        raise SystemExit('Stop/drain StockWatch services before compaction: '+', '.join(active))
    compact(database)
