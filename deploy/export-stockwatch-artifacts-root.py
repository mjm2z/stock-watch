#!/usr/bin/env python3
"""Read-only rehearsal export of StockWatch artifacts on a1347-j.

Does not stop jobs, change source permissions, or export a final cutover snapshot.
A final export must be made separately after all source writers have drained.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import stat
import time


def export(source, destination, uid, gid):
    destination.mkdir(mode=0o700)  # Never overwrite a previous recovery point.
    os.chown(destination, uid, gid)
    data = destination / 'data'
    data.mkdir(mode=0o700)
    os.chown(data, uid, gid)
    records = []
    last_report = time.monotonic()
    for path in sorted(source.rglob('*')):
        before = path.lstat()
        relative = path.relative_to(source)
        target = data / relative
        if stat.S_ISDIR(before.st_mode):
            target.mkdir(mode=0o700)
            os.chown(target, uid, gid)
            continue
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f'Unexpected nonregular artifact: {relative}; inspect before migration')
        digest = hashlib.sha256()
        with path.open('rb') as incoming, target.open('xb') as outgoing:
            os.chmod(target, 0o600)
            for chunk in iter(lambda: incoming.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        after = path.lstat()
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise RuntimeError(f'Artifact changed during export: {relative}; export is incomplete')
        shutil.copystat(path, target, follow_symlinks=False)
        os.chmod(target, 0o600)
        os.chown(target, uid, gid)
        records.append(dict(path=str(relative), bytes=before.st_size,
                            mtime_ns=before.st_mtime_ns, sha256=digest.hexdigest()))
        if time.monotonic() - last_report > 20:
            print(f'Copied and fingerprinted {len(records)} artifacts...', flush=True)
            last_report = time.monotonic()
    manifest = destination / 'manifest.json'
    with manifest.open('x') as output:
        os.chmod(manifest, 0o600)
        json.dump(dict(purpose='rehearsal-only', source=str(source), files=records), output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.chown(manifest, uid, gid)
    print(f'Export complete: {len(records)} files, {sum(r["bytes"] for r in records)} bytes')
    print(destination)


def main():
    if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'a1347-j':
        raise SystemExit('Run as root on a1347-j only')
    owner = pwd.getpwnam('mjm2z')
    source = Path('/var/lib/stock-watch/data')
    for line in Path('/etc/stock-watch/stock-watch.env').read_text().splitlines():
        if line.startswith('STOCK_WATCH_DATA_PATH='):
            source = Path(line.split('=', 1)[1].strip().strip('\"\''))
    if not source.is_absolute() or not source.is_dir() or source.is_symlink():
        raise SystemExit('Configured artifact path requires inspection')
    export(source, Path(owner.pw_dir) / 'app-migration-20260924/stockwatch-artifacts-rehearsal',
           owner.pw_uid, owner.pw_gid)


if __name__ == '__main__':
    main()
