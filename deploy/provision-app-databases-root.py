#!/usr/bin/env python3
"""Create isolated app/rehearsal DBs; never grant server administration rights.

Run once as root on a1347-m. Credentials are written only to the owner's
protected migration directory. No app starts, restores, or migrations occur.
"""
import json
import os
from pathlib import Path
import pwd
import secrets
import socket
import subprocess

if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'a1347-m':
    raise SystemExit('Run as root on a1347-m')
owner = pwd.getpwnam('mjm2z')
directory = Path(owner.pw_dir) / '.config/app-migration'
if directory.exists():
    raise SystemExit('Existing migration credentials: inspect before retry; nothing changed')


def sql(statement):
    result = subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-XAt',
                             '-v', 'ON_ERROR_STOP=1', '-d', 'postgres'],
                            input=statement, text=True, capture_output=True)
    if result.returncode:
        # SQL could contain credentials; do not print PostgreSQL error detail.
        raise RuntimeError('Database provisioning failed; inspect protected server state')
    return result.stdout.strip()


for role in ('jobwatch', 'radar'):
    if sql(f"SELECT 1 FROM pg_roles WHERE rolname='{role}'"):
        raise SystemExit('An app role exists; inspect before retry; nothing changed')
for database in ('jobwatch', 'jobwatch_rehearsal', 'app_demand_radar', 'radar_rehearsal'):
    if sql(f"SELECT 1 FROM pg_database WHERE datname='{database}'"):
        raise SystemExit('An app database exists; inspect before retry; nothing changed')

directory.mkdir(mode=0o700)
os.chown(directory, owner.pw_uid, owner.pw_gid)
for role, databases in [('jobwatch', ['jobwatch', 'jobwatch_rehearsal']),
                        ('radar', ['app_demand_radar', 'radar_rehearsal'])]:
    password = secrets.token_hex(32)
    # Write credentials first so a partial failure never loses a generated secret.
    for database in databases:
        config = directory / (database + '.env')
        fd = os.open(config, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(f'DATABASE_URL=postgresql://{role}:{password}@127.0.0.1:5432/{database}\n')
        os.chown(config, owner.pw_uid, owner.pw_gid)
    sql(f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{password}'")
    for database in databases:
        sql(f'CREATE DATABASE {database} OWNER {role}')
        sql(f'REVOKE CONNECT ON DATABASE {database} FROM PUBLIC')
print('Created separate app roles, production DBs, and rehearsal DBs; no app started.')
