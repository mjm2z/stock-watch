#!/usr/bin/env python3
"""Plan by default. --freeze-export drains StockWatch and exports final history.

Run only during the approved maintenance window on a1347-j. The original data
is never removed. On failure services remain stopped for inspection; do not
restart them after destination writes without transferring authoritative data back.
"""
import argparse
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import sqlite3
import subprocess
import time
from zoneinfo import ZoneInfo


def outside_market(at):
    local = at.astimezone(ZoneInfo('America/New_York'))
    return local.weekday() >= 5 or not 570 <= local.hour*60+local.minute < 960


def busy(state):
    return (state.get('ActiveState') in ('activating','deactivating','reloading') or
            int(state.get('MainPID','0')) != 0 or int(state.get('ControlPID','0')) != 0)


def unit_state(unit):
    text = subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','SubState',
                                   '-p','MainPID','-p','ControlPID'],text=True)
    return dict(line.split('=',1) for line in text.splitlines())


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-export',action='store_true')
    args=parser.parse_args()
    if socket.gethostname().split('.')[0]!='a1347-j':
        raise SystemExit('Run on a1347-j only')
    if args.freeze_export and os.geteuid()!=0:
        raise SystemExit('Freezing/exporting requires root; review mode does not')
    os.umask(0o077)
    listing=subprocess.check_output(['systemctl','list-unit-files','stock-watch-*',
                                    '--no-legend','--no-pager'],text=True)
    units={line.split()[0]:line.split()[1] for line in listing.splitlines() if line.strip()}
    if not units or any(not re.fullmatch(r'stock-watch-[a-z0-9-]+\.(service|timer)',name) for name in units):
        raise RuntimeError('Unexpected service inventory')
    if units.get('stock-watch-web.service')!='enabled':
        raise RuntimeError('Source web service no longer matches the expected live deployment')
    print(json.dumps({'mode':'freeze-export' if args.freeze_export else 'review-only',
                      'unit_states':units}),flush=True)
    if not args.freeze_export:
        return
    if not outside_market(datetime.now(ZoneInfo('UTC'))):
        raise SystemExit('Refusing to stop StockWatch during US market hours')
    owner=pwd.getpwnam('mjm2z')
    base=Path(owner.pw_dir)/'app-migration-20260924'
    env=Path('/etc/stock-watch/stock-watch.env')
    paths={}
    for line in env.read_text().splitlines():
        if line.startswith(('STOCK_WATCH_DATABASE_PATH=','STOCK_WATCH_DATA_PATH=')):
            key,value=line.split('=',1);paths[key]=Path(value.strip().strip('\"\''))
    database=paths.get('STOCK_WATCH_DATABASE_PATH',Path('/var/lib/stock-watch/stock-watch.db'))
    data=paths.get('STOCK_WATCH_DATA_PATH',Path('/var/lib/stock-watch/data'))
    if (not database.is_file() or database.is_symlink() or not database.is_absolute() or
            not data.is_dir() or data.is_symlink() or not data.is_absolute()):
        raise RuntimeError('Unexpected source paths')
    if shutil.disk_usage(base).free < database.stat().st_size*3+20*1024**3:
        raise RuntimeError('Insufficient disk reserve for full uncompressed/compressed exports')
    # Reject unaccounted-for cron writers instead of assuming systemd owns all work.
    for user in ('root','mjm2z','stock-watch'):
        cron=subprocess.run(['crontab','-u',user,'-l'],capture_output=True,text=True)
        if any('stock-watch' in line or 'stock_watch' in line for line in cron.stdout.splitlines()
               if line.strip() and not line.lstrip().startswith('#')):
            raise RuntimeError('StockWatch cron entry requires review before drain: '+user)
    snapshotter=module('snapshot','sqlite-migration-snapshot.py')
    artifacts=module('artifacts','export-stockwatch-artifacts-root.py')
    output=base/('stockwatch-final-'+datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir(mode=0o700);os.chown(output,owner.pw_uid,owner.pw_gid)
    def write(name, value):
        path=output/name
        with path.open('x') as stream:
            stream.write(value if isinstance(value,str) else json.dumps(value,indent=2)+'\n')
            stream.flush();os.fsync(stream.fileno())
        os.chown(path,owner.pw_uid,owner.pw_gid)
    before={name:dict(enabled=enabled,**unit_state(name)) for name,enabled in units.items()}
    write('source-units.json',before)
    write('stock-watch.env',env.read_text())
    for name in units:
        write(name,subprocess.check_output(['systemctl','cat',name],text=True))
    timers=[name for name in units if name.endswith('.timer')]
    enabled=[name for name in timers if units[name] in ('enabled','enabled-runtime')]
    if enabled: subprocess.run(['systemctl','disable',*enabled],check=True)
    if timers: subprocess.run(['systemctl','stop',*timers],check=True)
    jobs=[name for name in units if name.endswith('.service') and name!='stock-watch-web.service']
    deadline=time.monotonic()+2*3600
    while True:
        running=[name for name in jobs if busy(unit_state(name))]
        if not running: break
        if time.monotonic()>deadline:
            raise RuntimeError('Timed out waiting for jobs; no jobs were force-killed')
        print('Waiting for jobs to finish: '+', '.join(running),flush=True)
        time.sleep(20)
    subprocess.run(['systemctl','disable','--now','stock-watch-web.service'],check=True)
    stamps=output/'timer-stamps'
    stamps.mkdir(mode=0o700);os.chown(stamps,owner.pw_uid,owner.pw_gid)
    stamp_metadata={}
    for name in timers:
        source_stamp=Path('/var/lib/systemd/timers')/('stamp-'+name)
        if source_stamp.is_symlink(): raise RuntimeError('Unexpected timer timestamp symlink')
        if source_stamp.exists():
            target_stamp=stamps/source_stamp.name
            shutil.copy2(source_stamp,target_stamp)
            os.chmod(target_stamp,0o600);os.chown(target_stamp,owner.pw_uid,owner.pw_gid)
            stamp_metadata[source_stamp.name]=source_stamp.stat().st_mtime_ns
    write('timer-stamps.json',stamp_metadata)
    open_paths=[p for p in [database,Path(str(database)+'-wal'),Path(str(database)+'-shm')] if p.exists()]
    opened=subprocess.run(['lsof','-t',*map(str,open_paths)],capture_output=True,text=True)
    if opened.returncode not in (0,1) or opened.stdout.strip():
        raise RuntimeError('Database still has open handles; inspect before exporting')
    def signature():
        return {str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in
                [database,Path(str(database)+'-wal')] if p.exists()}
    frozen=signature()
    print('Source writers stopped. Copying and verifying final database...',flush=True)
    record=snapshotter.snapshot(database,output/'stock-watch.db',output/'stock-watch.json')
    for name in ('stock-watch.db','stock-watch.json'): os.chown(output/name,owner.pw_uid,owner.pw_gid)
    artifacts.export(data,output/'artifacts',owner.pw_uid,owner.pw_gid,purpose='final-cutover')
    with sqlite3.connect((output/'stock-watch.db').as_uri()+'?mode=ro',uri=True) as db:
        order_state={table:dict(db.execute(f'SELECT status,count(*) FROM {table} GROUP BY status'))
                     for table in ('paper_orders','paper_exit_orders','paper_trade_lots')}
        order_state['latest_reconciliation']=db.execute(
            'SELECT captured_at,status FROM broker_reconciliations ORDER BY captured_at DESC LIMIT 1').fetchone()
    write('paper-state-at-freeze.json',order_state)
    if signature()!=frozen or any(busy(unit_state(name)) for name in units if name.endswith('.service')):
        raise RuntimeError('Source changed after drain; do not use this export for cutover')
    write('final-export.json',dict(verified=True,purpose='final-cutover',
        completed_at=datetime.now(ZoneInfo('UTC')).isoformat(),database_sha256=record['sha256'],
        source_database=str(database),source_data=str(data),writers_stopped=True))
    print('Final export verified. Original data remains intact; source services remain stopped.',flush=True)
    print(output,flush=True)


if __name__=='__main__': main()
