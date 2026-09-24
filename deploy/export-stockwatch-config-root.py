#!/usr/bin/env python3
"""Export protected StockWatch config and inventory; never stop or change services."""
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess

if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'a1347-j':
    raise SystemExit('Run as root on a1347-j only')
owner = pwd.getpwnam('mjm2z')
destination = Path(owner.pw_dir)/'app-migration-20260924/stockwatch-source-export'
destination.mkdir(mode=0o700)  # Refuse replacement of any earlier export.
os.chown(destination, owner.pw_uid, owner.pw_gid)
source = Path('/etc/stock-watch/stock-watch.env')
config = {}
for line in source.read_text().splitlines():
    if line.startswith(('STOCK_WATCH_DATABASE_PATH=', 'STOCK_WATCH_DATA_PATH=')):
        key, value = line.split('=', 1)
        config[key] = value.strip().strip('\"\'')
database = Path(config.get('STOCK_WATCH_DATABASE_PATH', '/var/lib/stock-watch/stock-watch.db'))
data = Path(config.get('STOCK_WATCH_DATA_PATH', '/var/lib/stock-watch/data'))
if not database.is_file() or not data.is_dir():
    raise SystemExit('Configured data paths need inspection; no services changed')


def write(name, content):
    target = destination/name
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
    os.chown(target, owner.pw_uid, owner.pw_gid)


write('stock-watch.env', source.read_text())
units = subprocess.check_output(['systemctl', 'list-unit-files', 'stock-watch-*',
                                  '--no-legend', '--no-pager'], text=True)
write('unit-files.txt', units)
names = [line.split()[0] for line in units.splitlines() if line.strip()]
inventory = {'database': str(database), 'database_bytes': database.stat().st_size,
             'data_directory': str(data), 'files': [], 'units': {}}
for path in sorted(data.rglob('*')):
    if path.is_symlink():
        inventory['files'].append({'path': str(path.relative_to(data)), 'symlink': os.readlink(path)})
    elif path.is_file():
        metadata = path.stat()
        inventory['files'].append({'path': str(path.relative_to(data)), 'bytes': metadata.st_size,
                                   'mtime_ns': metadata.st_mtime_ns})
for name in names:
    state = {}
    for verb in ('is-enabled', 'is-active'):
        result = subprocess.run(['systemctl', verb, name], capture_output=True, text=True)
        state[verb] = result.stdout.strip()
    inventory['units'][name] = state
    result = subprocess.run(['systemctl', 'cat', name], capture_output=True, text=True, check=True)
    write(name + '.txt', result.stdout)
write('inventory.json', json.dumps(inventory, indent=2)+'\n')
print('Protected configuration and inventory exported; no services or source data changed.')
print(destination)
