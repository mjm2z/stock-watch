#!/usr/bin/env python3
"""Read-only metadata inventory; never dumps configuration or database contents."""
import json
from pathlib import Path
import sqlite3

root = Path('/var/backups/stock-watch-releases')
for directory in sorted(root.iterdir()):
    if not directory.is_dir() or directory.is_symlink():
        continue
    marker = directory / 'backup-verified.json'
    try:
        verified = json.loads(marker.read_text()).get('verified') is True if marker.is_file() else False
    except (ValueError, OSError):
        verified = False
    print(json.dumps({'recovery': str(directory), 'verified': verified and (directory/'stock-watch.db').is_file(),
                      'files': {p.name: {'bytes':p.stat().st_size, 'allocated_bytes':p.stat().st_blocks*512}
                                for p in directory.iterdir() if p.is_file() and not p.is_symlink() and
                                (p.name.endswith(('.db', '.tmp', '-wal', '-shm')) or p.name=='backup-verified.json')}}), flush=True)
p = Path('/var/lib/stock-watch/stock-watch.db')
with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True, timeout=3) as connection:
    print(json.dumps({'live_database': str(p), **{name: connection.execute('PRAGMA '+name).fetchone()[0]
                                               for name in ('page_size','page_count','freelist_count')}}), flush=True)
