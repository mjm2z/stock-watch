#!/usr/bin/python3
"""Preserve recovery history, then start the existing backup only when idle."""
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

BASELINE = '1fcba6f0a78305acbd468e713cbff2ed70b619f7740f263464cf52d192a5381f'
REVISION = 'cd89d63efaa65ed4359f89ff7dd1b81d6e96930f'
ROOT = Path('/opt/stock-watch')
DROPIN = Path('/etc/systemd/system/stock-watch-backup.service.d/90-preserve-recovery.conf')


class NotReady(RuntimeError):
    pass


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=20).stdout.strip()


def ready():
    for unit in ('stock-watch-backup.service', 'stock-watch-maintenance.service',
                 'apt-daily.service', 'apt-daily-upgrade.service', 'home-ops-restart-assessment.service'):
        if run('systemctl', 'show', unit, '-p', 'ActiveState', '--value') not in ('inactive', 'failed'):
            raise NotReady('Still busy: ' + unit)
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    pressure = next(line for line in Path('/proc/pressure/io').read_text().splitlines() if line.startswith('full '))
    pressure = dict(field.split('=') for field in pressure.split()[1:])
    if int(memory['MemAvailable'].split()[0]) < 2 * 1024 * 1024 or float(pressure['avg60']) >= 10:
        raise NotReady('Memory/I/O pressure still high')


def install_and_start():
    ready()
    lock = open('/home/mjm2z/.local/state/home-ops/backup-io.lock', 'r+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (ROOT / 'source-revision.txt').read_text().strip() != REVISION:
        raise SystemExit('Installed release changed; review required')
    staged = Path(__file__).resolve().with_name('backup.py')
    expected = staged.with_name('backup.sha256').read_text().strip()
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    source = ROOT / 'worker/src/stock_watch_worker/backup.py'
    package = ROOT / '.venv/lib/python3.12/site-packages/stock_watch_worker/backup.py'
    if digest(staged) != expected or any(digest(p) != BASELINE for p in (source, package)) or DROPIN.exists():
        raise SystemExit('Unknown/already changed module or drop-in; refusing overwrite')
    compile(staged.read_text(), str(staged), 'exec')
    archive = Path('/var/backups/stock-watch-module-repair') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive.mkdir(parents=True, mode=0o700)
    for name, path in (('source.py', source), ('installed.py', package)):
        shutil.copy2(path, archive / name)
    try:
        for path in (source, package):
            temporary = path.with_suffix('.validation-tmp')
            shutil.copy2(staged, temporary)
            st = path.stat()
            temporary.chmod(st.st_mode & 0o777)
            os.chown(temporary, st.st_uid, st.st_gid)
            temporary.replace(path)
        DROPIN.parent.mkdir(parents=True, exist_ok=True)
        DROPIN.write_text('[Service]\nEnvironment=STOCK_WATCH_BACKUP_PRESERVE_HISTORY=1\nIOSchedulingClass=idle\n')
        DROPIN.chmod(0o644)
        run('systemctl', 'daemon-reload')
    except Exception:
        for name, path in (('source.py', source), ('installed.py', package)):
            st = path.stat()
            shutil.copy2(archive / name, path)
            os.chown(path, st.st_uid, st.st_gid)
        DROPIN.unlink(missing_ok=True)
        run('systemctl', 'daemon-reload')
        raise
    (archive / 'receipt.txt').write_text('previous=' + BASELINE + '\ninstalled=' + expected +
        '\nRecovery history preservation remains enabled until dual-destination acceptance.\n')
    print('Recovery exports preserved; module rollback:', archive, flush=True)
    # Shared lock prevents a fleet/self snapshot racing this start. Once the
    # unit is activating, existing guards on those jobs defer to StockWatch.
    run('systemctl', 'start', '--no-block', 'stock-watch-backup.service')
    print('Backup validation requested; verification is pending.', flush=True)


def main():
    if os.geteuid() != 0 or socket.gethostname().split('.')[0] != 'a1347-m':
        raise SystemExit('Run as root on a1347-m')
    if '--queue' in sys.argv:
        unit = 'stock-watch-recovery-validation.service'
        state = subprocess.run(['systemctl', 'show', unit, '-p', 'ActiveState', '--value'],
                               text=True, capture_output=True, timeout=10).stdout.strip()
        if state in ('active', 'activating', 'deactivating'):
            raise SystemExit('Recovery validation is already queued/running')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        directory = Path('/var/backups/stock-watch-validation-queue') / stamp
        directory.mkdir(parents=True, mode=0o700)
        for name in ('start-backup-validation.py', 'backup.py', 'backup.sha256'):
            target = directory / name
            shutil.copyfile(Path(__file__).resolve().with_name(name), target)
            target.chmod(0o600)
        run('systemd-run', '--unit=stock-watch-recovery-validation', '--collect', '--no-block',
            '--property=Type=oneshot', '--property=TimeoutStartSec=3h',
            '/usr/bin/python3', str(directory / 'start-backup-validation.py'), '--wait')
        print('Queued; waits for idle conditions for at most three hours. No backup success claimed.')
        print('Progress: journalctl -u stock-watch-recovery-validation.service -u stock-watch-backup.service -n 20 --no-pager')
        return
    if '--wait' in sys.argv:
        # Serialize recovery launchers. The actual backup service still uses its
        # existing dataset lock; no second maintenance or backup process is killed.
        queue_lock = open('/run/stock-watch-validation-queue.lock', 'a')
        fcntl.flock(queue_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deadline = time.monotonic() + 170 * 60
        while time.monotonic() < deadline:
            try:
                install_and_start()
                return
            except (NotReady, BlockingIOError) as exc:
                print('Waiting; no backup started: ' + str(exc), flush=True)
                time.sleep(30)
        raise SystemExit('Idle wait expired; backup was not started')
    install_and_start()


if __name__ == '__main__':
    main()
