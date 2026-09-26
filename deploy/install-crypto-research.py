#!/usr/bin/env python3
"""Reviewed code-only update: chart collector and Bitcoin research UI. No migration."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.request
from zipfile import ZipFile


ROOT = Path('/opt/stock-watch')
CHANGED_MODULES = {'stock_watch_worker/systems/cli.py', 'stock_watch_worker/systems/workspace.py'}


def run(*args):
    subprocess.run(args, check=True)


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(source, manifest):
    if source.parent != Path('/home/mjm2z/stock-watch-releases'):
        raise ValueError('Unexpected staging location')
    if (source / '.env').exists() or any(source.glob('.env.*')):
        raise ValueError('Staging must not contain environment files')
    for name, digest in manifest['files'].items():
        path = source / name
        if not path.resolve().is_relative_to(source) or sha(path) != digest:
            raise ValueError('Staged checksum mismatch: ' + name)
    for name, digest in manifest['previous'].items():
        path = ROOT / name
        if digest is None:
            if path.exists():
                raise ValueError('Unexpected existing file: ' + name)
        elif sha(path) != digest:
            raise ValueError('Installed source differs from reviewed baseline: ' + name)
    if (source / 'package-lock.json').read_bytes() != (ROOT / 'package-lock.json').read_bytes():
        raise ValueError('Dependency change requires a full release')
    package = Path(output(str(ROOT / '.venv/bin/python'), '-c',
                          'import stock_watch_worker;print(next(iter(stock_watch_worker.__path__)))'))
    if not package.resolve().is_relative_to(ROOT / '.venv'):
        raise ValueError('Unexpected installed package')
    wheel = source / manifest['wheel']
    with ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith('stock_watch_worker/') and name.endswith('.py'):
                module = package / Path(name).relative_to('stock_watch_worker')
                expected = source / 'worker/src' / name if name in CHANGED_MODULES else module
                if archive.read(name) != expected.read_bytes():
                    raise ValueError('Unexpected worker change: ' + name)
                if name in CHANGED_MODULES and sha(module) != manifest['previous']['worker/src/' + name]:
                    raise ValueError('Installed module differs from source baseline')
    for suffix in ('service', 'timer'):
        if Path('/etc/systemd/system/stock-watch-chart.' + suffix).exists():
            raise ValueError('Chart collector is already installed; review before updating')
    return wheel


def ready():
    for endpoint in ('crypto', 'api/systems/research/bitcoin', 'api/health'):
        failure = None
        for _ in range(3):
            try:
                with urllib.request.urlopen('http://127.0.0.1:3001/' + endpoint, timeout=45) as response:
                    if response.status != 200:
                        raise ValueError('Unhealthy endpoint: ' + endpoint)
                    if endpoint == 'api/health' and json.load(response).get('status') == 'unavailable':
                        raise ValueError('Database unavailable')
                failure = None
                break
            except Exception as error:
                failure = error
                print('Waiting for', endpoint, str(error), flush=True)
                time.sleep(2)
        if failure:
            raise failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if socket.gethostname().split('.')[0] != 'a1347-m':
        raise ValueError('Run on a1347-m')
    source = args.source.resolve()
    manifest = json.loads((source / 'crypto-research-release.json').read_text())
    wheel = verify(source, manifest)
    if args.check:
        print('Code, dependencies, wheel and installed baseline verified. No changes made.')
        return
    if os.geteuid() != 0:
        raise ValueError('Run with sudo')
    if not args.run:
        run('systemd-run', '--no-block', '--collect', '--unit=stock-watch-crypto-research-install',
            '--property=Type=oneshot', '--property=TimeoutStartSec=20min',
            '/usr/bin/python3', str(source / 'deploy/install-crypto-research.py'), str(source), '--run')
        print('Installation continues independently of SSH. Progress:')
        print('journalctl -u stock-watch-crypto-research-install --no-pager -n 30')
        return
    os.umask(0o022)
    backup = Path('/var/backups/stock-watch-code-fixes') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True, mode=0o700)
    old_wheel = ROOT / manifest['wheel']
    shutil.copy2(old_wheel, backup / 'previous.whl')
    receipt_path = ROOT / 'installed-release.json'
    shutil.copy2(receipt_path, backup / 'installed-release.json')
    for name, digest in manifest['previous'].items():
        if digest is not None:
            saved = backup / 'source' / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, saved)
    run('rsync', '-a', '--exclude=cache/', str(source / '.next') + '/', str(backup / 'new-next') + '/')
    run('chown', '-R', 'root:root', str(backup / 'new-next'))
    timers = [line.split()[0] for line in output('systemctl', 'list-units', '--type=timer', '--state=active', '--no-legend', '--plain', 'stock-watch-*').splitlines()]
    services = [line.split()[0] for line in output('systemctl', 'list-units', '--all', '--type=service', '--no-legend', '--plain', 'stock-watch-*').splitlines()
                if line.split()[0] not in ('stock-watch-web.service', 'stock-watch-crypto-research-install.service')]
    (backup / 'active-timers.json').write_text(json.dumps(timers))
    if timers:
        run('systemctl', 'stop', *timers)
    modified = published = False
    safe_to_resume = True
    try:
        deadline = time.monotonic() + 300
        while any(output('systemctl', 'show', unit, '-p', 'ActiveState', '--value') in ('active', 'activating', 'deactivating') for unit in services):
            if time.monotonic() > deadline:
                raise ValueError('Existing workers did not drain; no code changed')
            time.sleep(2)
        modified = True
        safe_to_resume = False
        run(str(ROOT / '.venv/bin/pip'), 'install', '--no-index', '--no-deps', '--force-reinstall', str(wheel))
        run('systemctl', 'stop', 'stock-watch-web.service')
        for name in manifest['previous']:
            destination = ROOT / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, destination)
        shutil.copy2(wheel, old_wheel)
        (ROOT / '.next').rename(backup / 'previous-next')
        published = True
        (backup / 'new-next').rename(ROOT / '.next')
        run('install', '-d', '-o', 'stock-watch', '-g', 'stock-watch', '-m', '0755', str(ROOT / '.next/cache'))
        for suffix in ('service', 'timer'):
            shutil.copy2(source / ('deploy/systemd/stock-watch-chart.' + suffix), Path('/etc/systemd/system/stock-watch-chart.' + suffix))
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'stock-watch-web.service')
        ready()
        receipt = json.loads(receipt_path.read_text())
        receipt['crypto_research_patch'] = {'revision': manifest['revision'], 'recovery': str(backup), 'installed_at': datetime.now(timezone.utc).isoformat()}
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        run('systemctl', 'enable', '--now', 'stock-watch-chart.timer')
        safe_to_resume = True
    except Exception:
        if modified:
            run('systemctl', 'stop', 'stock-watch-web.service')
            subprocess.run(['systemctl', 'disable', '--now', 'stock-watch-chart.timer'], check=False)
            subprocess.run(['systemctl', 'stop', 'stock-watch-chart.service'], check=False)
            for suffix in ('service', 'timer'):
                Path('/etc/systemd/system/stock-watch-chart.' + suffix).unlink(missing_ok=True)
            run('systemctl', 'daemon-reload')
            # pip requires the original valid wheel filename.
            restore = backup / 'wheel' / old_wheel.name
            restore.parent.mkdir(exist_ok=True)
            shutil.copy2(backup / 'previous.whl', restore)
            run(str(ROOT / '.venv/bin/pip'), 'install', '--no-index', '--no-deps', '--force-reinstall', str(restore))
            shutil.copy2(restore, old_wheel)
            for name, digest in manifest['previous'].items():
                if digest is None:
                    (ROOT / name).unlink(missing_ok=True)
                else:
                    shutil.copy2(backup / 'source' / name, ROOT / name)
            if published:
                if (ROOT / '.next').exists():
                    (ROOT / '.next').rename(backup / 'failed-next')
                (backup / 'previous-next').rename(ROOT / '.next')
            shutil.copy2(backup / 'installed-release.json', receipt_path)
            run('systemctl', 'start', 'stock-watch-web.service')
            safe_to_resume = True
        raise
    finally:
        if timers and safe_to_resume:
            run('systemctl', 'start', *timers)
    print('Crypto research and independent chart collection installed. No migration or trading activation.')
    print('Code recovery:', backup)


if __name__ == '__main__':
    main()
