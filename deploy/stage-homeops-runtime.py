#!/usr/bin/env python3
"""Install disabled HomeOps destination units and the deployed source dashboard."""
from pathlib import Path
import shutil
import socket
import subprocess


def main():
    if socket.gethostname().split('.')[0] != 'a1347-m':
        raise SystemExit('Destination a1347-m only')
    home=Path.home()
    marker=home/'.config/app-migration/home-ops.cutover-ready'
    if marker.exists() or (home/'.config/home-ops/server.json').exists():
        raise SystemExit('HomeOps destination is already configured; inspect before changing')
    units=home/'.config/systemd/user'
    specifications={}
    for name,module,oneshot in (
        ('home-ops','server',False),('home-ops-network','network_observer',False),
        ('home-ops-backup','self_backup',True)):
        specifications[name+'.service']=f'''[Unit]
Description={name}
After=network-online.target
ConditionPathExists=%h/.config/app-migration/home-ops.cutover-ready
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type={'oneshot' if oneshot else 'simple'}
WorkingDirectory=%h/home-ops
ExecStart=/usr/bin/python3 -m home_ops.{module}
Environment=PYTHONUNBUFFERED=1
UMask=0077
NoNewPrivileges={'false' if module=='network_observer' else 'true'}
TimeoutStopSec=infinity
''' + ('' if oneshot else 'Restart=on-failure\nRestartSec=15\n') + '''
[Install]
WantedBy=default.target
'''
    specifications['home-ops-backup.timer']='''[Unit]
Description=Daily verified Home Ops database snapshot
ConditionPathExists=%h/.config/app-migration/home-ops.cutover-ready

[Timer]
OnCalendar=*-*-* 12:30:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
'''
    for name in specifications:
        if (units/name).exists():
            raise RuntimeError('Existing unit requires review: '+name)
    destination=home/'home-ops/web/dist'
    source=home/'app-migration-20260924/homeops-web-final'
    if destination.exists() or not (source/'index.html').is_file():
        raise RuntimeError('Unexpected dashboard staging state')
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,destination)
    for name,text in specifications.items():
        (units/name).write_text(text)
    subprocess.run(['systemd-analyze','--user','verify',*[str(units/name) for name in specifications]],check=True)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    print('Dashboard and four disabled units installed. No database/config published; no services started.')


if __name__=='__main__':
    main()
