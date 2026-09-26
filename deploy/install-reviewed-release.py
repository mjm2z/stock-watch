#!/usr/bin/env python3
"""Install a prebuilt release on the authoritative host with retained recovery data."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo


def run(*args):
    return subprocess.run(args, check=True, text=True)


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def counts(db):
    names = ('paper_orders', 'paper_exit_orders', 'paper_lots', 'signals',
             'strategy_versions', 'scan_runs')
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {n: db.execute('SELECT COUNT(*) FROM "' + n + '"').fetchone()[0]
            for n in names if n in existing}


def verify_files(source, manifest):
    for name, expected in manifest['files'].items():
        path = source / name
        if not path.resolve().is_relative_to(source):
            raise RuntimeError('Unsafe release manifest path')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise RuntimeError('Staged release changed: ' + name)


def main():
    if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'a1347-m':
        raise SystemExit('Run as root on a1347-m only')
    now = datetime.now(ZoneInfo('America/New_York'))
    if now.weekday() < 5 and 570 <= now.hour * 60 + now.minute < 960:
        raise SystemExit('Run outside US market hours')
    source = Path(sys.argv[1]).resolve()
    if source.parent != Path('/home/mjm2z/stock-watch-releases'):
        raise SystemExit('Unexpected release staging directory')
    manifest = json.loads((source / 'reviewed-release.json').read_text())
    verify_files(source, manifest)
    for required in ('.next/BUILD_ID', 'package-lock.json', 'worker/migrations/016_systems.sql'):
        if required not in manifest['files']:
            raise RuntimeError('Incomplete reviewed release: ' + required)
    if any(source.glob('.env*')):
        raise RuntimeError('Release staging must not contain environment files')
    wheels = list((source / 'release-wheels').glob('stock_watch_worker-*.whl'))
    if len(wheels) != 1:
        raise RuntimeError('Expected one prebuilt worker wheel')
    runtime = Path('/opt/stock-watch')
    database = Path('/var/lib/stock-watch/stock-watch.db')
    stamp = datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
    recovery = Path('/var/backups/stock-watch-releases') / stamp
    if shutil.disk_usage('/').free < database.stat().st_size + 20 * 1024**3:
        raise RuntimeError('Insufficient room for fresh backup and reserve')
    os.umask(0o077)
    recovery.mkdir(parents=True)
    shutil.copytree('/etc/stock-watch', recovery / 'config')
    units = output('systemctl', 'list-unit-files', 'stock-watch-*', '--no-legend').splitlines()
    timers = [line.split()[0] for line in units if line.split()[0].endswith('.timer')]
    enabled = {unit: output('systemctl', 'is-enabled', unit) for unit in timers
               if subprocess.run(['systemctl', 'is-enabled', '--quiet', unit]).returncode == 0}
    (recovery / 'enabled-timers.json').write_text(json.dumps(enabled, indent=2))
    if timers:
        run('systemctl', 'stop', *timers)
    services = [line.split()[0] for line in units if line.split()[0].endswith('.service')
                and line.split()[0] != 'stock-watch-web.service']
    deadline = time.monotonic() + 600
    while any(output('systemctl', 'show', '-p', 'ActiveState', '--value', s)
              in ('active', 'activating', 'deactivating') for s in services):
        if time.monotonic() > deadline:
            raise RuntimeError('Jobs still active; timers remain stopped. Review before retrying.')
        time.sleep(5)
    run('systemctl', 'stop', 'stock-watch-web.service')
    print('Writers stopped. Creating a fresh recovery database; originals are retained.', flush=True)
    last = [0.0]
    def progress(status, remaining, total):
        if time.monotonic() - last[0] > 10:
            print(f'Backup copied {total-remaining}/{total} pages...', flush=True)
            last[0] = time.monotonic()
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as old:
        before = counts(old)
        with sqlite3.connect(recovery / 'stock-watch.db') as backup:
            old.backup(backup, pages=4096, progress=progress)
            print('Verifying fresh recovery database...', flush=True)
            if backup.execute('PRAGMA quick_check').fetchall() != [('ok',)] or counts(backup) != before:
                raise RuntimeError('Backup verification failed; release not installed')
    (recovery / 'backup-verified.json').write_text(json.dumps({'counts': before, 'verified': True}))
    previous = runtime.with_name('stock-watch.before-' + stamp)
    runtime.rename(previous)
    os.umask(0o022)
    runtime.mkdir(mode=0o755)
    # Leave the full previous runtime available; no production artifacts are removed.
    run('rsync', '-a', '--exclude=reviewed-release.json', str(source) + '/', str(runtime) + '/')
    run('chown', '-R', 'root:root', str(runtime))
    run('chmod', '755', str(runtime))
    run('python3.12', '-m', 'venv', str(runtime / '.venv'))
    run(str(runtime / '.venv/bin/pip'), 'install', '--no-index', str(runtime / 'release-wheels' / wheels[0].name))
    run('chown', '-R', 'stock-watch:stock-watch', str(runtime / '.next/cache'))
    env = Path('/etc/stock-watch/systems.env')
    if not env.exists():
        shutil.copyfile(runtime / 'deploy/systems.env.example', env)
        env.chmod(0o600)
    text = env.read_text()
    if 'SYSTEMS_OPERATOR_TOKEN=\n' in text:
        text = text.replace('SYSTEMS_OPERATOR_TOKEN=\n', 'SYSTEMS_OPERATOR_TOKEN=' + secrets.token_urlsafe(48) + '\n')
        env.write_text(text)
    # Only additive systems migration/seeding; legacy strategy authority is unchanged.
    run('runuser', '-u', 'stock-watch', '--', str(runtime / '.venv/bin/stock-watch-systems'),
        '--database', str(database), 'init')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as current:
        if counts(current) != before:
            raise RuntimeError('Legacy ledger counts changed during migration; services remain stopped')
        if current.execute('SELECT COUNT(*) FROM system_deployments').fetchone()[0]:
            raise RuntimeError('Unexpected systems deployments require review before activation')
    run('bash', str(runtime / 'deploy/install-systems-root.sh'))
    for mode in ('enabled', 'enabled-runtime'):
        selected = [unit for unit, state in enabled.items() if state == mode]
        if selected:
            run('systemctl', 'enable', *(['--runtime'] if mode == 'enabled-runtime' else []), '--now', *selected)
    for route in ('/api/health', '/api/systems?asset=stocks', '/api/systems?asset=bitcoin', '/api/bitcoin'):
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:3001' + route, timeout=10) as response:
                    if response.status == 200:
                        break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Release readiness failed: ' + route)
    receipt = {'revision': manifest['revision'], 'recovery': str(recovery),
               'previous_runtime': str(previous), 'legacy_counts': before,
               'installed_at': datetime.now(ZoneInfo('UTC')).isoformat()}
    (runtime / 'installed-release.json').write_text(json.dumps(receipt, indent=2))
    (runtime / 'installed-release.json').chmod(0o644)
    print('Release verified. Existing timers restored; research/watch-only timers enabled. No strategy activated.')
    print('Recovery directory:', recovery)
    print('Operator token is retained privately in /etc/stock-watch/systems.env')


if __name__ == '__main__':
    main()
