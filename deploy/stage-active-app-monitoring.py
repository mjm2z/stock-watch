#!/usr/bin/env python3
"""Stage monitoring for completed app moves while HomeOps remains on a1990."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket


def main():
    if socket.gethostname().split('.')[0] != 'a1347-m':
        raise SystemExit('Run on a1347-m')
    os.umask(0o077)
    root = Path.home()/'app-migration-20260924'
    preview = root/'homeops-relocated-configs'
    output = root/'homeops-active-app-configs'
    output.mkdir(mode=0o700)
    apps = {'JobWatch','App Demand Radar'}
    patches = {}
    for machine in ('a1347-m','a1347-d','m4-mac-mini'):
        source = root/f'homeops-{machine}-before.json'
        original = json.loads(source.read_text())
        proposed = json.loads((preview/(machine+'.json')).read_text())
        updated = copy.deepcopy(original)
        for key in ('files','journals','services'):
            updated[key] = [x for x in original.get(key,[]) if x.get('app') not in apps] + [
                x for x in proposed.get(key,[]) if x.get('app') in apps]
        assert updated['token'] == original['token']
        assert updated['state_dir'] == original['state_dir']
        (output/(machine+'.json')).write_text(json.dumps(updated,indent=2)+'\n')
        patches[machine+'.json'] = hashlib.sha256(source.read_bytes()).hexdigest()
    source = root/'homeops-server-before.json'
    original = json.loads(source.read_text())
    proposed = json.loads((preview/'server.json').read_text())
    selected = {x['id']:x for x in proposed['sites'] if x['id'] in ('job-watch','job-watch-worker','app-radar')}
    for site in selected.values():
        site['open_url'] = 'http://192.168.4.35:' + ('5210' if site['id']=='app-radar' else '3020')
    original['sites'] = [selected.get(x['id'],x) for x in original['sites']]
    (output/'server.json').write_text(json.dumps(original,indent=2)+'\n')
    patches['server.json'] = hashlib.sha256(source.read_bytes()).hexdigest()
    (output/'expected-before.json').write_text(json.dumps(patches,indent=2)+'\n')
    print('Staged only JobWatch/Radar monitoring; HomeOps hosting, endpoints, credentials and backups unchanged.')


if __name__ == '__main__':
    main()
