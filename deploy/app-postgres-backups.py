#!/usr/bin/env python3
"""Additive PostgreSQL backup creation/pull. Cutover markers gate scheduled use.

No retention pruning is performed during migration. Stops below a 50 GiB disk
reserve. Restoreability is separately exercised by verify-offhost-postgres.py;
routine pull verification reports checksums/archive readability, not a restore.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(directory):
    metadata = json.loads((directory/'bundle.json').read_text())
    if metadata.get('format') != 1 or set(metadata['files']) != {
            'jobwatch.dump', 'jobwatch.json', 'radar.dump', 'radar.json'}:
        raise ValueError('Incomplete backup bundle')
    for name, digest in metadata['files'].items():
        path = directory/name
        if path.is_symlink() or checksum(path) != digest:
            raise ValueError('Backup checksum mismatch: '+name)
    for app, required in [('jobwatch', 'jobs'), ('radar', 'raw_posts')]:
        manifest = json.loads((directory/(app+'.json')).read_text())
        if manifest.get('format') != 3 or f'"public"."{required}"' not in manifest.get('tables', {}):
            raise ValueError('Missing application tables')
        if manifest['dump_sha256'] != metadata['files'][app+'.dump']:
            raise ValueError('Dump does not match snapshot manifest')
        subprocess.run(['/usr/lib/postgresql/16/bin/pg_restore', '--list',
                        str(directory/(app+'.dump'))], check=True, stdout=subprocess.DEVNULL)
    return metadata


def run(command, heartbeat):
    with subprocess.Popen(command) as child:
        while True:
            try:
                code = child.wait(timeout=30)
                if code:
                    raise subprocess.CalledProcessError(code, command)
                return
            except subprocess.TimeoutExpired:
                heartbeat()


def create(home, state, heartbeat):
    for app in ('job-watch', 'app-demand-radar'):
        if not (home/'.config/app-migration'/f'{app}.cutover-ready').is_file():
            raise RuntimeError('Both applications must finish cutover before production backups')
    recovery_point = now()  # Conservative earliest time, not end-of-backup time.
    ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    work = state/'work'/ident
    work.mkdir(parents=True, mode=0o700)
    script = home/'.local/lib/app-migration/postgres-migration-snapshot.mjs'
    for app, code in [('jobwatch', 'job-watch'), ('radar', 'app-demand-radar')]:
        root = home/code/('backend' if app == 'radar' else '')
        run(['/usr/local/bin/node', '--env-file='+str(home/'.config'/code/'runtime.env'),
             str(script), str(root), str(work/app)], heartbeat)
    files = {name: checksum(work/name) for name in
             ('jobwatch.dump', 'jobwatch.json', 'radar.dump', 'radar.json')}
    (work/'bundle.json').write_text(json.dumps(dict(format=1, recovery_point_at=recovery_point, files=files), indent=2)+'\n')
    metadata = verify_bundle(work)
    for path in work.iterdir():
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
    destination = home/'.local/state/app-backups'/ident
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    work.rename(destination)
    return metadata, destination


def pull(home, state, heartbeat):
    incoming = state/'incoming'
    incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
    ssh = f'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 -i {home}/.ssh/app_postgres_backup_pull'
    run(['rsync', '-a', '--timeout=120', '--include=/20*/',
        '--include=*.dump', '--include=*.json', '--exclude=*', '-e', ssh,
        'mjm2z@192.168.4.35:/home/mjm2z/.local/state/app-backups/', str(incoming)+'/'], heartbeat)
    bundles = sorted(p for p in incoming.iterdir() if p.is_dir() and
                     re.fullmatch(r'\d{8}T\d{12}Z', p.name))
    if not bundles:
        raise RuntimeError('No finalized production PostgreSQL backup exists')
    latest = bundles[-1]
    metadata = verify_bundle(latest)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(metadata['recovery_point_at'])).total_seconds()
    if not 0 <= age <= 30*3600:
        raise RuntimeError('Newest backup is stale or has a future recovery timestamp')
    # Keep the verified bundle in place; a receipt is published only after checks.
    (latest/'verified.json').write_text(json.dumps(dict(verified_at=now(),
        verification='sha256_and_pg_restore_archive_listing'), indent=2)+'\n')
    return metadata, latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['create','pull'])
    args = parser.parse_args()
    expected = 'a1347-m' if args.mode == 'create' else 'a1347-d'
    if socket.gethostname().split('.')[0] != expected or os.geteuid() == 0:
        raise SystemExit('Run unprivileged on '+expected)
    os.umask(0o077)
    home = Path.home()
    if not (home/'.config/app-migration/postgres-backups.cutover-ready').is_file():
        raise SystemExit('Production backup activation marker is absent')
    state = home/'.local/state/app-postgres-backups'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state/'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = home/'.local/state/home-ops'/('app-postgres-'+args.mode+'-status.json')
        status.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = dict(job='app-postgres-'+args.mode, run_id='postgres:'+now(),
                      started_at=now(), status='running', verification='unverified')
        def save():
            record['observed_at'] = now()
            temporary = status.with_suffix('.next')
            temporary.write_text(json.dumps(record, indent=2)+'\n')
            temporary.replace(status)
        save()
        try:
            if shutil.disk_usage(state).free < 50*1024**3:
                raise RuntimeError('Less than 50 GiB free; preserve earlier backups and review storage')
            metadata, destination = (create if args.mode == 'create' else pull)(home, state, save)
            record.update(status='ok', recovery_point_at=metadata['recovery_point_at'],
                          destination=str(destination), verification='sha256_and_pg_restore_archive_listing',
                          summary='Both application backups passed checksums and archive listing')
        except Exception as error:
            record.update(status='failed', diagnostic=str(error), summary='Application PostgreSQL backup failed')
            raise
        finally:
            record['finished_at'] = now()
            save()


if __name__ == '__main__':
    main()
