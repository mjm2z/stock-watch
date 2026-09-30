#!/usr/bin/env python3
"""Bounded read-only Linux lock sampling; never opens a SQLite connection."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default='/var/lib/stock-watch/stock-watch.db')
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('Use a duration between 1 and 3600 seconds')
    if not Path('/proc/locks').exists():
        parser.error('Run on the Linux application host')
    paths = [Path(args.database + suffix) for suffix in ('', '-wal', '-shm')]
    deadline = time.monotonic() + args.seconds
    previous, heartbeat = None, 0.0
    while time.monotonic() < deadline:
        identities = {}
        for path in paths:
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            except PermissionError:
                parser.exit(1, 'Database metadata is protected; run with sudo on the host.\n')
            identities[(os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)] = str(path)
        if not identities:
            parser.exit(1, 'No database files found; check the path.\n')
        locks = []
        for line in Path('/proc/locks').read_text().splitlines():
            fields = line.replace('-> ', '').split()
            if len(fields) < 8:
                continue
            device = fields[5].split(':')
            if len(device) != 3:
                continue
            identity = (int(device[0], 16), int(device[1], 16), int(device[2]))
            if identity not in identities:
                continue
            pid = fields[4]
            try:
                program = Path('/proc', pid, 'comm').read_text().strip()
            except OSError:
                program = 'unavailable'
            locks.append(dict(pid=pid, program=program, kind=fields[1], mode=fields[3],
                              path=identities[identity], start=fields[6], end=fields[7],
                              waiting='->' in line))
        locks.sort(key=lambda r: (r['path'], r['pid'], r['start'], r['mode']))
        now = time.monotonic()
        if locks != previous or now >= heartbeat:
            pressure = Path('/proc/pressure/io')
            print(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), locks=locks,
                                  host_io_pressure=pressure.read_text().strip() if pressure.exists() else None)), flush=True)
            previous, heartbeat = locks, now + 30
        time.sleep(min(1, max(0, deadline-time.monotonic())))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
