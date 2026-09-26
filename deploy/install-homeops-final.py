#!/usr/bin/env python3
"""Restore verified frozen HomeOps history into its empty destination and start it."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys


def main():
    if socket.gethostname().split('.')[0]!='a1347-m' or os.geteuid()==0:
        raise SystemExit('Run as the ordinary HomeOps user on a1347-m')
    os.umask(0o077)
    home=Path.home()
    source=Path(sys.argv[1]).resolve()
    if source.parent!=home/'app-migration-20260924' or not source.name.startswith('homeops-final-'):
        raise RuntimeError('Unexpected final snapshot directory')
    preview=home/'app-migration-20260924/homeops-relocated-configs'
    receipt=json.loads((source/'final-export.json').read_text())
    manifest=json.loads((source/'events.json').read_text())
    if (receipt.get('verified') is not True or receipt.get('writers_stopped') is not True or
        receipt.get('purpose')!='final-cutover' or receipt['database_sha256']!=manifest['sha256']):
        raise RuntimeError('Missing final source verification')
    hashes=json.loads((preview/'source-hashes.json').read_text())
    if hashlib.sha256((source/'server.json').read_bytes()).hexdigest()!=hashes['homeops-server-before.json']:
        raise RuntimeError('Source config changed after relocation preview')
    original=json.loads((source/'server.json').read_text())
    config=json.loads((preview/'server.json').read_text())
    if any(config[key]!=original[key] for key in ('collector_tokens','notification_token','database')):
        raise RuntimeError('Credentials/database path changed unexpectedly')
    if config['server_machine']!='a1347-m':
        raise RuntimeError('Unexpected server identity')
    # Keep app links usable before the separate privileged DNS handoff.
    ports={'home-ops':9100,'job-watch':3020,'job-watch-worker':3020,'app-radar':5210,'stock-watch':3001}
    for site in config['sites']:
        if site['id'] in ports: site['open_url']='http://192.168.4.35:'+str(ports[site['id']])
    destination=home/'.local/state/home-ops/events.sqlite'
    live=home/'.config/home-ops/server.json'
    marker=home/'.config/app-migration/home-ops.cutover-ready'
    if destination.exists() or live.exists() or marker.exists():
        raise RuntimeError('Destination is not empty; refusing replacement')
    units=json.loads((source/'source-units.json').read_text())
    allowed={'home-ops.service','home-ops-network.service','home-ops-backup.service','home-ops-backup.timer'}
    if set(units)!=allowed: raise RuntimeError('Unexpected source unit set')
    enabled=[name for name,state in units.items() if 'UnitFileState=enabled\n' in state]
    if 'home-ops.service' not in enabled: raise RuntimeError('Source server was not enabled')
    for name in allowed:
        status=subprocess.run(['systemctl','--user','is-active','--quiet',name])
        if status.returncode not in (3,4): raise RuntimeError('Destination unit is not inactive: '+name)
    stamp=home/'.local/share/systemd/timers/stamp-home-ops-backup.timer'
    if stamp.exists(): raise RuntimeError('Destination timer history already exists')
    spec=importlib.util.spec_from_file_location('decompress',Path(__file__).with_name('decompress-migration-snapshot.py'))
    decompressor=importlib.util.module_from_spec(spec);spec.loader.exec_module(decompressor)
    result=decompressor.decompress(source/'events.sqlite.gz',source/'events.json',destination)
    print(json.dumps(result),flush=True)
    with live.open('x') as stream: json.dump(config,stream,indent=2)
    if (source/stamp.name).exists():
        stamp.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/stamp.name,stamp)
        mtime=json.loads((source/'timer-stamp.json').read_text())['mtime_ns']
        os.utime(stamp,ns=(mtime,mtime))
    with marker.open('x') as stream: stream.write('Verified final HomeOps snapshot '+manifest['sha256']+'\n')
    with (home/'.config/home-ops/app-host.json').open('x') as stream:
        json.dump({'machine':'a1347-m'},stream)
    subprocess.run(['systemctl','--user','enable','--now',*enabled],check=True)
    print('HomeOps restored and original enabled service/timer set activated; collector databases were not replaced.',flush=True)


if __name__=='__main__': main()
