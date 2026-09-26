#!/usr/bin/env python3
"""Narrow StockWatch display-label update; credentials and historical rows are untouched."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile


def rebrand(value):
    changed=0
    if isinstance(value,dict):
        for key,item in value.items():
            if key in ('name','app','label','description') and isinstance(item,str):
                replacement=item.replace('Stock'+' Watch','StockWatch')
                changed+=int(replacement!=item);value[key]=replacement
            elif isinstance(item,(dict,list)):changed+=rebrand(item)
    elif isinstance(value,list):
        for item in value:changed+=rebrand(item)
    return changed


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if socket.gethostname().split('.')[0]!='a1347-m':raise SystemExit('Run as the HomeOps user on a1347-m')
    root=Path.home()/'.config/home-ops';changes=[]
    for name in ('server.json','collector.json'):
        path=root/name;data=json.loads(path.read_text());count=rebrand(data)
        print(name+': '+str(count)+' display labels')
        if count:changes.append((path,data))
    if not args.apply:return
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for path,data in changes:
        backup=path.with_name(path.name+'.before-stockwatch-brand-'+stamp)
        if backup.exists():raise RuntimeError('Backup already exists')
        shutil.copy2(path,backup);backup.chmod(0o600)
        with tempfile.NamedTemporaryFile(mode='w',dir=root,delete=False) as stream:
            json.dump(data,stream,indent=2);stream.write('\n');temporary=Path(stream.name)
        temporary.chmod(path.stat().st_mode&0o777);temporary.replace(path)
    if changes:subprocess.run(['systemctl','--user','restart','home-ops.service','home-ops-collector.service'],check=True)
    print('Display labels applied; protected backups retained. Historical data unchanged.')

if __name__=='__main__':main()
