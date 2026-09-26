#!/usr/bin/env python3
"""Activate only the recorded source web/timer set after verified publication."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.request
from zoneinfo import ZoneInfo


def enabled_sets(units):
    enabled={name:state['enabled'] for name,state in units.items()
             if state['enabled'] in ('enabled','enabled-runtime')}
    if enabled.get('stock-watch-web.service')!='enabled':
        raise RuntimeError('Expected the original enabled web service')
    if any(name!='stock-watch-web.service' and not re.fullmatch(r'stock-watch-[a-z0-9-]+\.timer',name)
           for name in enabled):
        raise RuntimeError('Unexpected enabled source service; review before activation')
    return enabled


def activate(source):
    if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='a1347-m':
        raise SystemExit('Run as root on a1347-m')
    now=datetime.now(ZoneInfo('America/New_York'))
    if now.weekday()<5 and 570<=now.hour*60+now.minute<960:
        raise SystemExit('Outside market hours only')
    source=source.resolve()
    if source.parent!=Path('/home/mjm2z/app-migration-20260924') or not re.fullmatch(r'stockwatch-final-\d{8}T\d{6}Z',source.name):
        raise RuntimeError('Unexpected final export')
    published=Path('/var/lib/stock-watch')/('.'+source.name)
    receipt=json.loads((published/'published.json').read_text())
    manifest=json.loads((source/'stock-watch.json').read_text())
    if receipt['source']!=str(source) or receipt['database_sha256']!=manifest['sha256']:
        raise RuntimeError('Successful publication receipt does not match this export')
    paper=json.loads((source/'paper-state-at-freeze.json').read_text())
    terminal={'filled','canceled','cancelled','rejected','expired'}
    if any(status not in terminal and count for table in ('paper_orders','paper_exit_orders')
           for status,count in paper[table].items()):
        raise RuntimeError('Pending source paper orders need reconciliation before activation')
    if not paper.get('latest_reconciliation') or paper['latest_reconciliation'][1]!='matched':
        raise RuntimeError('Source reconciliation needs review')
    enabled=enabled_sets(json.loads((source/'source-units.json').read_text()))
    # Enforce the approved app activation order.
    with urllib.request.urlopen('http://127.0.0.1:9100/api/health',timeout=15) as response:
        if response.status!=200: raise RuntimeError('HomeOps destination is not ready')
    subprocess.run(['systemctl','enable','--now','stock-watch-web.service'],check=True)
    deadline=time.monotonic()+120
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:3001/api/dashboard/overview',timeout=15) as response:
                if response.status==200: break
        except Exception:
            pass
        if time.monotonic()>deadline:
            raise RuntimeError('Web readiness failed; no timers enabled')
        time.sleep(2)
    for mode in ('enabled','enabled-runtime'):
        timers=[name for name,state in enabled.items() if name.endswith('.timer') and state==mode]
        if timers:
            subprocess.run(['systemctl','enable',*(['--runtime'] if mode=='enabled-runtime' else []),'--now',*timers],check=True)
    subprocess.run(['systemctl','is-active','--quiet',*enabled],check=True)
    final=published/'activated.json'
    if not final.exists():
        with final.open('x') as stream:
            json.dump(dict(activated_at=datetime.now(ZoneInfo('UTC')).isoformat(),
                source_writers_confirmed_stopped=True,enabled_units=enabled),stream,indent=2)
    print('StockWatch web is ready; only the recorded source timer set was enabled.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export',type=Path)
    parser.add_argument('--source-writers-stopped',action='store_true',required=True)
    args=parser.parse_args()
    activate(args.export)
