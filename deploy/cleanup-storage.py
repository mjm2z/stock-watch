#!/usr/bin/env python3
"""Conservative StockWatch artifact cleanup. Default is a read-only plan.

Never deletes scheduled completed backups, entire recovery directories, live
state, configuration, or unrelated applications. Explicit --recovery-backups keeps
two newest verified recovery DB copies and removes only older main DB files.
Run on a1347-m as root.
"""
import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import time

RUNTIME = Path('/opt/stock-watch')
STAGING = Path('/home/mjm2z/stock-watch-releases')
BACKUPS = Path('/var/backups/stock-watch')
OLD = re.compile(r'stock-watch\.before-\d{8}T\d{6}Z')
RELEASE = re.compile(r'[0-9a-f]{7,40}')
TEMP = re.compile(r'\.stock-watch-\d{8}T\d{12}Z\.db\.tmp(?:-shm|-wal)?')


def plain(path, directory=False):
    info = path.lstat()
    return stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)


def read_receipt(root):
    path = root / 'installed-release.json'
    if not plain(path):
        raise RuntimeError('Receipt must be a regular file: ' + str(path))
    data = json.loads(path.read_text())
    if not re.fullmatch(r'[0-9a-f]{40}', data['revision']):
        raise RuntimeError('Invalid receipt revision')
    return data


def candidates(runtime=RUNTIME, staging=STAGING, backups=BACKUPS, now=None):
    now = time.time() if now is None else now
    receipt = read_receipt(runtime)
    old = sorted((p for p in runtime.parent.iterdir() if OLD.fullmatch(p.name) and plain(p, True)), reverse=True)
    keep = set(old[:2])
    previous = Path(receipt['previous_runtime'])
    if previous.parent != runtime.parent or not OLD.fullmatch(previous.name):
        raise RuntimeError('Invalid prior-runtime path in receipt')
    keep.add(previous)
    revisions = {receipt['revision']}
    for path in keep:
        if path.exists():
            revisions.add(read_receipt(path)['revision'])
    stages = [p for p in staging.iterdir() if RELEASE.fullmatch(p.name) and plain(p, True)]
    # Also preserve the two most recently prepared releases (possibly not installed).
    recent = sorted(stages, key=lambda p: (p / 'reviewed-release.json').stat().st_mtime if (p / 'reviewed-release.json').is_file() else p.stat().st_mtime, reverse=True)[:2]
    protected_stages = set(recent) | {p for p in stages if any(r.startswith(p.name) for r in revisions)}
    result = [{'path': str(p), 'kind': 'old-runtime'} for p in old if p not in keep]
    result += [{'path': str(p), 'kind': 'old-staging'} for p in stages if p not in protected_stages and now - p.stat().st_mtime > 6*3600]
    # A completed backup must exist, and is always retained. No recovery backups are candidates.
    completed = [p for p in backups.glob('stock-watch-*.db') if plain(p) and p.stat().st_size > 0]
    if completed:
        result += [{'path': str(p), 'kind': 'abandoned-backup', 'bytes': p.stat().st_size}
                   for p in backups.iterdir() if TEMP.fullmatch(p.name) and plain(p) and now - p.stat().st_mtime > 6*3600]
    for entry in result:
        info = Path(entry['path']).lstat()
        entry['identity'] = [info.st_dev, info.st_ino, info.st_mtime_ns]
    return {'revision': receipt['revision'], 'preserved_runtimes': sorted(map(str, keep)),
            'preserved_staging': sorted(map(str, protected_stages)), 'candidates': result}


def recovery_candidates(root=Path('/var/backups/stock-watch-releases')):
    verified = []
    for directory in root.iterdir():
        if not re.fullmatch(r'\d{8}T\d{6}Z', directory.name) or not plain(directory, True):
            continue
        marker, database = directory/'backup-verified.json', directory/'stock-watch.db'
        if not marker.exists() or not database.exists() or not plain(marker) or not plain(database):
            continue
        if json.loads(marker.read_text()).get('verified') is True:
            verified.append(directory)
    verified.sort(reverse=True)
    if len(verified) < 2:
        raise RuntimeError('At least two verified recovery databases must be retained')
    rows=[]
    for directory in verified[2:]:
        path=directory/'stock-watch.db'
        info=path.lstat()
        rows.append({'path':str(path),'kind':'old-recovery-database','bytes':info.st_size,
                     'identity':[info.st_dev,info.st_ino,info.st_mtime_ns]})
    return rows, list(map(str, verified[:2]))


def under(path, root):
    return path == root or path.startswith(root + '/')


def in_use(paths):
    """Inspect open descriptors, cwd, executables and mappings; do not print their contents."""
    busy = set()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            links = [proc / 'cwd', proc / 'exe'] + list((proc / 'fd').iterdir())
            targets = []
            for link in links:
                try:
                    targets.append(os.readlink(link).removesuffix(' (deleted)'))
                except FileNotFoundError:
                    pass
            for line in (proc / 'maps').read_text().splitlines():
                fields = line.split(None, 5)
                if len(fields) == 6:
                    targets.append(fields[5].removesuffix(' (deleted)'))
            busy.update(p for p in paths if any(under(t, p) for t in targets))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise RuntimeError('Cannot verify all process handles; no cleanup performed') from exc
    return busy


def remove_plan(plan):
    paths = [entry['path'] for entry in plan['candidates']]
    busy = in_use(paths)
    if busy:
        raise RuntimeError('Candidates still in use; no cleanup performed: ' + ', '.join(sorted(busy)))
    for entry in plan['candidates']:
        p = Path(entry['path'])
        info = p.lstat()
        if [info.st_dev, info.st_ino, info.st_mtime_ns] != entry['identity'] or p.is_symlink():
            raise RuntimeError('Candidate changed; aborting: ' + str(p))
    for entry in plan['candidates']:
        p = Path(entry['path'])
        print('Removing ' + str(p), flush=True)
        if entry['kind'] in ('abandoned-backup', 'old-recovery-database'):
            p.unlink()
        else:
            # Python's fd-based rmtree refuses symlink substitution on this platform.
            if not shutil.rmtree.avoids_symlink_attacks:
                raise RuntimeError('Safe directory removal is unavailable')
            shutil.rmtree(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--recovery-backups', action='store_true', help='Also remove older main recovery DB copies, retaining two newest verified copies; keeps config and evidence files')
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--expected-revision')
    identity.add_argument('--automatic', action='store_true', help='Scheduled maintenance: use the installed receipt under the release lock')
    args = parser.parse_args()
    if socket.gethostname().split('.')[0] != 'a1347-m' or os.geteuid() != 0:
        raise SystemExit('Run on a1347-m with sudo; default is a plan only.')
    with ExitStack() as stack:
        for path in (Path('/run/stock-watch-reviewed-release.lock'), BACKUPS / '.backup.lock'):
            if path.is_symlink():
                raise RuntimeError('Unexpected lock symlink')
            lock = stack.enter_context(path.open('a'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        units = subprocess.check_output(['systemctl', 'list-units', '--state=running,activating', '--no-legend', '--plain', 'stock-watch-release-*', 'stock-watch-backup.service'], text=True)
        if units.strip():
            raise RuntimeError('Installer or backup is active; retry after it finishes')
        plan = candidates()
        if args.recovery_backups:
            extra, retained = recovery_candidates()
            plan['candidates'].extend(extra)
            plan['preserved_recovery_databases'] = retained
        if not args.automatic and plan['revision'] != args.expected_revision:
            raise RuntimeError('Installed revision changed; review cleanup again')
        print(json.dumps(plan, indent=2), flush=True)
        before = shutil.disk_usage('/').free
        if args.apply:
            remove_plan(plan)
        print(json.dumps({'applied': args.apply, 'free_bytes_before': before,
                          'free_bytes_after': shutil.disk_usage('/').free}), flush=True)


if __name__ == '__main__':
    main()
