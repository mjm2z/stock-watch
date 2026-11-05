#!/usr/bin/python3
"""Guarded backup-only SSD verifier installation, idle queue, and rollback."""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import time

BASELINE = 'da17c17599305ceb017dbb5e5ad28428027df621e665ea486a03b10cbcf1dec9'
REVISION = 'cd89d63efaa65ed4359f89ff7dd1b81d6e96930f'
ROOT = Path('/opt/stock-watch')
CONFIG = Path('/etc/stock-watch/backup-ssd')
DROPIN = Path('/etc/systemd/system/stock-watch-backup.service.d/91-ssd-verification.conf')
PRESERVE = DROPIN.with_name('90-preserve-recovery.conf')
PRESERVE_TEXT = '[Service]\nEnvironment=STOCK_WATCH_BACKUP_PRESERVE_HISTORY=1\nIOSchedulingClass=idle\n'
PAYLOAD = ('backup.py','backup_ssd.py','id_ed25519','known_hosts','config.json')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args):
    return subprocess.run(args,check=True,text=True,capture_output=True,timeout=30).stdout.strip()


def preflight(stage):
    if socket.gethostname().split('.')[0]!='a1347-m':raise RuntimeError('Wrong host')
    if (ROOT/'source-revision.txt').read_text().strip()!=REVISION:raise RuntimeError('Installed release changed')
    manifest=json.loads((stage/'manifest.json').read_text())
    if set(manifest)!=set(PAYLOAD):raise RuntimeError('Unexpected payload manifest')
    for name in PAYLOAD:
        if (stage/name).is_symlink() or digest(stage/name)!=manifest[name]:raise RuntimeError('Payload changed: '+name)
    for name in ('backup.py','backup_ssd.py'):compile((stage/name).read_text(),name,'exec')
    for base in ('worker/src/stock_watch_worker','.venv/lib/python3.12/site-packages/stock_watch_worker'):
        if digest(ROOT/base/'backup.py')!=BASELINE or (ROOT/base/'backup_ssd.py').exists():raise RuntimeError('Unknown installed module')
    if PRESERVE.read_text()!=PRESERVE_TEXT or DROPIN.exists() or CONFIG.exists():raise RuntimeError('Unknown configuration')
    config=json.loads((stage/'config.json').read_text())
    if config!=dict(host='mjm2z@192.168.4.36',key=str(CONFIG/'id_ed25519'),known_hosts=str(CONFIG/'known_hosts')):
        raise RuntimeError('Unexpected verifier configuration')
    return manifest


def ready():
    units=('stock-watch-backup.service','stock-watch-maintenance.service','apt-daily.service',
           'apt-daily-upgrade.service','home-ops-restart-assessment.service')
    for unit in units:
        if run('systemctl','show',unit,'-p','ActiveState','--value') not in ('inactive','failed'):
            return False,unit+' busy'
    mem=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    line=next(x for x in Path('/proc/pressure/io').read_text().splitlines() if x.startswith('full '))
    pressure=dict(x.split('=') for x in line.split()[1:])
    if int(mem['MemAvailable'].split()[0])<2*1024**2 or float(pressure['avg60'])>=10:
        return False,'memory/I/O pressure'
    return True,'ready'


def rollback(archive):
    if run('systemctl','show','stock-watch-backup.service','-p','ActiveState','--value') not in ('inactive','failed'):
        raise RuntimeError('Backup active; cannot roll back')
    entries=json.loads((archive/'rollback.json').read_text())
    for entry in entries:
        p=Path(entry['path'])
        if p.exists() and digest(p) not in (entry['installed'],entry.get('previous_sha256')):
            raise RuntimeError('Subsequent edit: '+str(p))
        if entry['previous'] is not None and digest(archive/entry['previous'])!=entry['previous_sha256']:
            raise RuntimeError('Rollback file changed')
    for entry in reversed(entries):
        p=Path(entry['path'])
        if entry['previous'] is None:p.unlink(missing_ok=True)
        else:
            backup=archive/entry['previous']
            if digest(backup)!=entry['previous_sha256']:raise RuntimeError('Rollback file changed')
            shutil.copy2(backup,p);os.chown(p,entry['uid'],entry['gid'])
    if CONFIG.exists():CONFIG.rmdir()
    run('systemctl','daemon-reload')


def install(stage):
    good,why=ready()
    if not good:raise BlockingIOError(why)
    with open('/home/mjm2z/.local/state/home-ops/backup-io.lock','r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        preflight(stage)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        archive=Path('/var/backups/stock-watch-ssd-repair')/stamp
        archive.mkdir(parents=True,mode=0o700)
        account=pwd.getpwnam('stock-watch')
        entries=[]
        def write(path,data,mode,uid=0,gid=0):
            entry=dict(path=str(path),installed=hashlib.sha256(data).hexdigest(),previous=None)
            if path.exists():
                st=path.stat();name=str(len(entries))+'.previous';shutil.copy2(path,archive/name)
                entry.update(previous=name,previous_sha256=digest(path),uid=st.st_uid,gid=st.st_gid)
            entries.append(entry)
            (archive/'rollback.json').write_text(json.dumps(entries,indent=2)+'\n')
            temp=path.with_name(path.name+'.ssd-install-tmp');temp.write_bytes(data)
            temp.chmod(mode);os.chown(temp,uid,gid);temp.replace(path)
        try:
            for base in ('worker/src/stock_watch_worker','.venv/lib/python3.12/site-packages/stock_watch_worker'):
                for name in ('backup.py','backup_ssd.py'):write(ROOT/base/name,(stage/name).read_bytes(),0o644)
            CONFIG.mkdir(mode=0o750);os.chown(CONFIG,0,account.pw_gid)
            for name in ('id_ed25519','known_hosts','config.json'):
                write(CONFIG/name,(stage/name).read_bytes(),0o640,0,account.pw_gid)
            write(DROPIN,b'[Service]\nEnvironment=STOCK_WATCH_BACKUP_SSD_CONFIG=/etc/stock-watch/backup-ssd/config.json\n',0o644)
            run('systemctl','daemon-reload')
        except Exception:
            rollback(archive)
            raise
        print('Installed SSD verification; rollback: '+str(archive),flush=True)
        run('systemctl','start','--no-block','stock-watch-backup.service')
        print('Backup requested. Success still requires fresh export and both replica checks.',flush=True)


def main():
    stage=Path(__file__).resolve().parent
    if sys.argv[1:]==['--check']:
        preflight(stage);print('Read-only payload and installed baseline checks passed.');return
    if os.geteuid()!=0:raise SystemExit('Run with sudo on a1347-m')
    if len(sys.argv)==3 and sys.argv[1]=='--rollback':
        rollback(Path(sys.argv[2]));print('Backup code/configuration rolled back; history unchanged.');return
    if sys.argv[1:]==['--queue']:
        preflight(stage)
        unit='stock-watch-ssd-validation.service'
        state=subprocess.run(['systemctl','show',unit,'-p','ActiveState','--value'],capture_output=True,text=True,timeout=15).stdout.strip()
        if state in ('active','activating','deactivating'):raise RuntimeError('SSD validation already queued')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        private=Path('/var/backups/stock-watch-ssd-queue')/stamp;private.mkdir(parents=True,mode=0o700)
        for name in (*PAYLOAD,'manifest.json','install-ssd-backup.py'):
            shutil.copyfile(stage/name,private/name);(private/name).chmod(0o600)
        run('systemd-run','--unit=stock-watch-ssd-validation','--collect','--no-block',
            '--property=Type=oneshot','--property=TimeoutStartSec=3h',
            '/usr/bin/python3',str(private/'install-ssd-backup.py'),'--wait')
        print('Queued for idle conditions, up to 170 minutes. No backup success claimed.');return
    if sys.argv[1:]==['--wait']:
        with open('/run/stock-watch-validation-queue.lock','a') as queue_lock:
            fcntl.flock(queue_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            deadline=time.monotonic()+170*60
            while time.monotonic()<deadline:
                try:install(stage);return
                except BlockingIOError as exc:print('Waiting: '+str(exc),flush=True);time.sleep(30)
            raise RuntimeError('Idle wait expired; backup not started')
    raise SystemExit('Use --check, --queue, or --rollback ARCHIVE')


if __name__=='__main__':main()
