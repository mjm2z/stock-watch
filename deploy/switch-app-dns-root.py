#!/usr/bin/env python3
"""Review the narrow DNS patch by default; --apply is only for final cutover."""
import argparse
from datetime import datetime
import difflib
import os
from pathlib import Path
import re
import shlex
import socket
import stat
import subprocess
import urllib.request
from zoneinfo import ZoneInfo

NAMES = ('logs', 'stockwatch', 'jobwatch', 'radar')


def patch(text):
    lines = [line for line in text.splitlines() if line.startswith('ExecStart=')]
    if len(lines) != 1 or not lines[0].startswith('ExecStart=/usr/sbin/dnsmasq '):
        raise ValueError('Unexpected DNS service; review required')
    before = after = lines[0]
    for name in NAMES:
        expression = rf'(?<!\S)--address=/{name}\.home\.arpa/(\S+)'
        found = re.findall(expression, after)
        if len(found) > 1 or (found and found[0] not in (
                ('192.168.4.35', '192.168.4.36') if name == 'logs' else ('192.168.4.35',))):
            raise ValueError(f'Unexpected existing DNS mapping: {name}')
        argument = f'--address=/{name}.home.arpa/192.168.4.35'
        after = re.sub(expression, argument, after) if found else after + ' ' + argument
    return text.replace(before, after, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if socket.gethostname().split('.')[0] != 'a1990':
        raise SystemExit('Run on a1990 only')
    unit = Path('/etc/systemd/system/sandbox-dns.service')
    original = unit.read_text()
    updated = patch(original)
    print(''.join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
        fromfile='current DNS service', tofile='proposed app DNS service')))
    if not args.apply:
        print('Review only: DNS has not changed.')
        return
    if os.geteuid() != 0:
        raise SystemExit('Applying requires root')
    now = datetime.now(ZoneInfo('America/New_York'))
    if now.weekday() < 5 and 9*60+30 <= now.hour*60+now.minute < 16*60:
        raise SystemExit('Refusing cutover during US market hours')
    for port, path in [(9100,'/api/health'), (3001,'/api/dashboard/overview'),
                       (3020,'/api/health'), (3020,'/api/worker-health'), (5210,'/api/health')]:
        with urllib.request.urlopen(f'http://192.168.4.35:{port}{path}', timeout=15) as response:
            if response.status != 200:
                raise RuntimeError('Destination readiness check failed; DNS unchanged')
    if updated == original:
        print('DNS already matches the target; no changes.')
        return
    command = next(line.removeprefix('ExecStart=') for line in updated.splitlines() if line.startswith('ExecStart='))
    subprocess.run(['/usr/sbin/dnsmasq', '--test', *shlex.split(command)[1:]], check=True)
    backup = unit.with_suffix('.service.before-app-consolidation')
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    metadata = unit.stat()
    temporary = unit.with_suffix('.service.app-migration-next')
    with temporary.open('x') as stream:
        stream.write(updated)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, stat.S_IMODE(metadata.st_mode))
    os.chown(temporary, metadata.st_uid, metadata.st_gid)
    os.replace(temporary, unit)
    try:
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'restart', 'sandbox-dns.service'], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'sandbox-dns.service'], check=True)
    except Exception:
        unit.write_text(original)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'restart', 'sandbox-dns.service'], check=True)
        raise
    print('App DNS switched; Sandbox records preserved.')


if __name__ == '__main__':
    main()
