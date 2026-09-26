#!/usr/bin/env python3
"""Install the reviewed independent watchdog after its final state handoff."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess


def main():
    if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'a1347-j':
        raise SystemExit('Run as root on a1347-j only')
    home = Path('/home/mjm2z')
    staging = home / 'app-migration-20260924'
    receipt = json.loads((staging / 'watchdog-handoff.json').read_text())
    if receipt.get('source_stopped') is not True:
        raise RuntimeError('Missing stopped-source handoff receipt')
    state = home / '.local/state/home-ops/watchdog.json'
    source = staging / 'home-ops-watchdog-migration.service'
    for path, key in ((state, 'state_sha256'), (source, 'unit_sha256')):
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt[key]:
            raise RuntimeError('Reviewed handoff changed: ' + str(path))
    config = json.loads((home / '.config/home-ops/watchdog-migration.json').read_text())
    if (config.get('endpoint') != 'http://192.168.4.35:9100'
            or config.get('observer') != 'a1347-j'
            or config.get('delivery_enabled') is not True
            or config.get('delivery_transport') != 'telegram'
            or config.get('state_path') != str(state)):
        raise RuntimeError('Unexpected production watchdog configuration')
    credentials = Path(config['telegram_credentials'])
    if credentials.stat().st_mode & 0o077:
        raise RuntimeError('Watchdog credentials must be private')
    marker = home / '.config/app-migration/watchdog.cutover-ready'
    if not marker.is_file():
        raise RuntimeError('Missing final cutover marker')
    target = Path('/etc/systemd/system/home-ops-watchdog-migration.service')
    if target.exists():
        raise RuntimeError('Existing watchdog unit needs review; refusing replacement')
    subprocess.run(['systemd-analyze', 'verify', str(source)], check=True)
    with target.open('xb') as stream:
        stream.write(source.read_bytes())
    target.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', target.name], check=True)
    subprocess.run(['systemctl', 'is-active', '--quiet', target.name], check=True)
    print('Independent watchdog enabled on a1347-j with transferred incident history.')


if __name__ == '__main__':
    main()
