#!/usr/bin/env python3
"""Render relocation from actual protected configs; never publish live config."""
import hashlib
import json
import os
from pathlib import Path
import socket
import sys


def main():
    if socket.gethostname().split('.')[0] != 'a1347-m':
        raise SystemExit('Run on a1347-m only')
    os.umask(0o077)
    root = Path.home()/'app-migration-20260924'
    sys.path.insert(0, str(root/'home-ops'))
    from home_ops.app_relocation import relocate
    machines = ['a1990','a1347-d','a1347-j','a1347-m','m4-mac-mini']
    server_file = root/'homeops-server-before.json'
    server = json.loads(server_file.read_text())
    sources = {machine: root/f'homeops-{machine}-before.json' for machine in machines}
    collectors = {machine: json.loads(path.read_text()) for machine,path in sources.items()}
    updated, moved = relocate(server, collectors)
    assert updated['collector_tokens'] == server['collector_tokens']
    assert updated['notification_token'] == server['notification_token']
    for machine in machines:
        assert moved[machine]['token'] == collectors[machine]['token']
        assert moved[machine]['state_dir'] == collectors[machine]['state_dir']
        assert server['collector_tokens'][machine] == collectors[machine]['token']
    assert relocate(updated, moved) == (updated, moved)
    output = root/'homeops-relocated-configs'
    output.mkdir(mode=0o700)
    (output/'server.json').write_text(json.dumps(updated,indent=2)+'\n')
    for machine, config in moved.items():
        (output/(machine+'.json')).write_text(json.dumps(config,indent=2)+'\n')
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in [server_file,*sources.values()]}
    (output/'source-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
    print('Relocation preview passed: all credentials and collector state paths preserved.')
    print(json.dumps({'collectors':len(moved),'sites':len(updated.get('sites',[])),
                      'backup_policies':len(updated.get('backups',[])), 'live_configs_changed':False}))


if __name__ == '__main__':
    main()
