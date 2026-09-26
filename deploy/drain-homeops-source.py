#!/usr/bin/env python3
"""Stop HomeOps server writers and create a final verified snapshot on a1990.

Collectors, Sandbox, DNS and unrelated backup jobs remain configured. Stop the
remote notifier before invoking this helper. Original data is never removed.
"""
from datetime import datetime
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from zoneinfo import ZoneInfo


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-export',action='store_true')
    parser.add_argument('--notifier-stopped',action='store_true')
    args=parser.parse_args()
    if socket.gethostname().split('.')[0]!='a1990' or os.geteuid()==0:
        raise SystemExit('Run as the ordinary HomeOps user on a1990')
    now=datetime.now(ZoneInfo('America/New_York'))
    if now.weekday()<5 and 570<=now.hour*60+now.minute<960:
        raise SystemExit('Outside market hours only')
    os.umask(0o077)
    home=Path.home()
    config_path=home/'.config/home-ops/server.json'
    config=json.loads(config_path.read_text())
    database=Path(config['database']).expanduser()
    if database!=home/'.local/state/home-ops/events.sqlite' or database.is_symlink():
        raise RuntimeError('Unexpected source database')
    if shutil.disk_usage(database).free<database.stat().st_size*2+10*1024**3:
        raise RuntimeError('Insufficient recovery snapshot space')
    if not args.freeze_export:
        print('Review only: server/network/backup timer will stop; original database and collectors remain.')
        return
    if not args.notifier_stopped:
        raise RuntimeError('First stop the remote notifier, then pass --notifier-stopped')
    names=('home-ops.service','home-ops-network.service','home-ops-backup.timer','home-ops-backup.service')
    output=home/'app-migration-20260924'/('homeops-final-'+datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir(mode=0o700)
    states={}
    for name in names:
        states[name]=subprocess.check_output(['systemctl','--user','show',name,'-p','ActiveState','-p','UnitFileState'],text=True)
        (output/name).write_text(subprocess.check_output(['systemctl','--user','cat',name],text=True))
    (output/'source-units.json').write_text(json.dumps(states,indent=2)+'\n')
    shutil.copy2(config_path,output/'server.json')
    subprocess.run(['systemctl','--user','disable','--now','home-ops-backup.timer'],check=True)
    deadline=time.monotonic()+7200
    while True:
        state=subprocess.check_output(['systemctl','--user','show','home-ops-backup.service','-p','MainPID','-p','ControlPID'],text=True)
        if all(line.endswith('=0') for line in state.splitlines()):
            break
        if time.monotonic()>deadline:
            raise RuntimeError('Backup did not finish; no process force-killed')
        print('Waiting for existing HomeOps snapshot to finish...',flush=True)
        time.sleep(15)
    subprocess.run(['systemctl','--user','disable','--now','home-ops-network.service','home-ops.service'],check=True)
    stamp=home/'.local/share/systemd/timers/stamp-home-ops-backup.timer'
    if stamp.exists():
        shutil.copy2(stamp,output/stamp.name)
        (output/'timer-stamp.json').write_text(json.dumps({'mtime_ns':stamp.stat().st_mtime_ns})+'\n')
    paths=[p for p in (database,Path(str(database)+'-wal'),Path(str(database)+'-shm')) if p.exists()]
    opened=subprocess.run(['lsof','-t',*map(str,paths)],capture_output=True,text=True)
    if opened.returncode not in (0,1) or opened.stdout.strip():
        raise RuntimeError('Database has open handles; inspect before snapshot')
    def signature():
        return {str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in
                (database,Path(str(database)+'-wal')) if p.exists()}
    before=signature()
    spec=importlib.util.spec_from_file_location('snapshot',Path(__file__).with_name('sqlite-migration-snapshot.py'))
    snapshot=importlib.util.module_from_spec(spec);spec.loader.exec_module(snapshot)
    record=snapshot.snapshot(database,output/'events.sqlite',output/'events.json')
    if before!=signature():
        raise RuntimeError('Source changed after drain')
    (output/'final-export.json').write_text(json.dumps(dict(purpose='final-cutover',verified=True,
        writers_stopped=True,database_sha256=record['sha256'],source_database=str(database),
        completed_at=datetime.now(ZoneInfo('UTC')).isoformat()),indent=2)+'\n')
    print('Final HomeOps snapshot verified; original database retained and server writers stopped.',flush=True)
    print(output,flush=True)


if __name__=='__main__':
    main()
