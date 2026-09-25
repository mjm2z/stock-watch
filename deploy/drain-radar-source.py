#!/usr/bin/env python3
"""Disable only Radar's managed cron block, drain jobs, stop its source server.

Preserves original crontab and data. Shared PostgreSQL and Data Engine stay up.
Run only on a1347-d during the approved maintenance window.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
from urllib.request import urlopen
from zoneinfo import ZoneInfo


def main():
    if socket.gethostname().split('.')[0] != 'a1347-d':
        raise SystemExit('Source a1347-d only')
    now = datetime.now(ZoneInfo('America/New_York'))
    if now.weekday() < 5 and 570 <= now.hour*60+now.minute < 960:
        raise SystemExit('Outside market hours only')
    os.umask(0o077)
    home = Path.home()
    app = home/'app-demand-radar'
    output = home/'app-migration-20260924'/('radar-final-'+now.strftime('%Y%m%dT%H%M%S'))
    original = subprocess.check_output(['crontab','-l'], text=True)
    begin, end = '# BEGIN APP_DEMAND_RADAR', '# END APP_DEMAND_RADAR'
    if original.count(begin) != 1 or original.count(end) != 1:
        raise RuntimeError('Unexpected managed cron markers')
    before, rest = original.split(begin)
    block, after = rest.split(end)
    remaining = before + after.lstrip('\n')
    if any('app-demand-radar' in line for line in remaining.splitlines()
           if line.strip() and not line.lstrip().startswith('#')):
        raise RuntimeError('Unmanaged Radar schedule requires review')
    output.mkdir(mode=0o700)
    (output/'crontab-before.txt').write_text(original)
    (output/'crontab-after.txt').write_text(remaining)
    subprocess.run(['crontab','-'], input=remaining, text=True, check=True)

    def processes():
        result = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                cwd = (entry/'cwd').resolve(strict=True)
                args = (entry/'cmdline').read_bytes().replace(b'\0', b' ').decode()
                if cwd == app or app in cwd.parents:
                    result.append((int(entry.name), args))
            except (OSError, UnicodeError):
                continue
        return result

    deadline = time.monotonic()+7200
    while True:
        current = processes()
        # The known npm -> sh -> node web wrapper is idle infrastructure.
        jobs = [(pid,args) for pid,args in current if args.strip() not in
                ('npm run start','sh -c node src/server.js','node src/server.js')]
        with urlopen('http://127.0.0.1:5210/api/run-controls', timeout=15) as response:
            controls = json.load(response)['controls']
        active = [x['script'] for x in controls if x.get('active_pid')]
        if not jobs and not active:
            break
        if time.monotonic() > deadline:
            raise RuntimeError('Jobs did not drain; no process force-killed')
        print(json.dumps({'waiting_pids':[pid for pid,_ in jobs], 'manual_jobs':active}), flush=True)
        time.sleep(15)
    servers = [pid for pid,args in processes() if args.strip() == 'node src/server.js']
    if len(servers) != 1:
        raise RuntimeError('Expected one source web process')
    os.kill(servers[0], signal.SIGTERM)
    deadline = time.monotonic()+60
    while processes():
        if time.monotonic() > deadline:
            raise RuntimeError('Source processes remain; inspect before snapshot')
        time.sleep(1)
    if subprocess.check_output(['crontab','-l'],text=True) != remaining:
        raise RuntimeError('Cron changed during drain; inspect before snapshot')
    (output/'stopped.json').write_text(json.dumps({'source_writers_stopped':True,
        'at':datetime.now(ZoneInfo('UTC')).isoformat(), 'shared_postgres_retained':True},indent=2)+'\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
