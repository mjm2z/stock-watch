#!/usr/bin/env python3
"""Restore migration backups into a NEW isolated PostgreSQL cluster on a1347-d.

Never connects to the host's production PostgreSQL instance. Retains the stopped
verification cluster and original dumps; never prunes any recovery point.
"""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess


def main():
    if socket.gethostname().split('.')[0] != 'a1347-d' or os.geteuid() == 0:
        raise SystemExit('Run unprivileged on a1347-d')
    os.umask(0o077)
    home = Path.home()
    stage = home / 'app-migration-20260924'
    source = stage / 'offhost-postgres-rehearsal'
    for app in ('jobwatch', 'radar'):
        for suffix in ('.dump', '.json'):
            if not (source / (app + '-rehearsal-3' + suffix)).is_file():
                raise RuntimeError('Missing transferred backup; finish transfer first')
    # Refuse an occupied listener before initializing the separate cluster.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 55439))
    root = stage / 'postgres-offhost-restore-check'
    root.mkdir(mode=0o700)
    sock = root / 'socket'
    sock.mkdir(mode=0o700)
    password = secrets.token_hex(32)
    password_file = root / 'password'
    password_file.write_text(password)
    pg = Path('/usr/lib/postgresql/16/bin')
    cluster = root / 'cluster'
    subprocess.run([str(pg/'initdb'), '-D', str(cluster), '--username=restore_check',
                    '--auth=scram-sha-256', '--pwfile='+str(password_file),
                    '--encoding=UTF8', '--no-locale'], check=True)
    started = False
    try:
        subprocess.run([str(pg/'pg_ctl'), '-D', str(cluster), '-l', str(root/'server.log'),
                        '-o', f'-h 127.0.0.1 -p 55439 -k {sock}', '-t', '300', '-w', 'start'], check=True)
        started = True
        env = dict(os.environ, PGHOST='127.0.0.1', PGPORT='55439',
                   PGUSER='restore_check', PGPASSWORD=password,
                   PATH=str(pg)+':'+os.environ['PATH'])
        for app in ('jobwatch', 'radar'):
            db = app + '_rehearsal'
            subprocess.run([str(pg/'createdb'), db], env=env, check=True)
            config = root / (app + '.env')
            config.write_text(f'DATABASE_URL=postgresql://restore_check:{password}@127.0.0.1:55439/{db}\n')
            subprocess.run(['/usr/bin/node', '--env-file='+str(config),
                str(stage/'postgres-rehearsal-restore.mjs'),
                str(home/'app-demand-radar/backend'), str(source/(app+'-rehearsal-3')),
                str(root/(app+'-restored'))], env=env, check=True)
        (root/'verified.json').write_text(json.dumps(dict(
            purpose='rehearsal-only', verified=True,
            verification='isolated_restore_and_all_table_fingerprints',
            apps=['jobwatch', 'radar']), indent=2)+'\n')
        print('Both off-host PostgreSQL backups restored with matching table fingerprints.', flush=True)
    finally:
        if started:
            # A just-restored HDD cluster may need more than pg_ctl's default
            # 60 seconds to flush its shutdown checkpoint. Never force-kill it.
            subprocess.run([str(pg/'pg_ctl'), '-D', str(cluster), '-m', 'fast',
                            '-t', '300', '-w', 'stop'], check=True)


if __name__ == '__main__':
    main()
