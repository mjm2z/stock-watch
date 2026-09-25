#!/usr/bin/env python3
"""Add read-only, source-restricted public backup keys without replacing others."""
import os,re,socket
from pathlib import Path
if socket.gethostname().split('.')[0] != 'a1347-m' or os.geteuid() == 0:
    raise SystemExit('Run unprivileged on a1347-m')
home=Path.home(); staging=home/'app-migration-20260924'; auth=home/'.ssh/authorized_keys'
original=auth.read_bytes()
lines=[]
for kind,file in [('homeops','homeops-pull.pub'),('stockwatch','stock-watch-pull.pub'),('postgres','postgres-pull.pub')]:
    parts=(staging/file).read_text().strip().split()
    if len(parts)<2 or parts[0]!='ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]+',parts[1]): raise RuntimeError('Invalid public key')
    if parts[1].encode() in original: raise RuntimeError('Existing key requires review')
    command=f'/usr/bin/python3 {home}/.local/lib/app-migration/restricted-app-backup-export.py {kind}'
    lines.append(f'from="192.168.4.33",restrict,command="{command}" ssh-ed25519 {parts[1]} app-migration-{kind}\n')
with (staging/'authorized_keys.before-backup-pulls').open('xb') as f:
    os.chmod(f.name,0o600); f.write(original)
code=home/'.local/lib/app-migration'; code.mkdir(parents=True,mode=0o700,exist_ok=True)
target=code/'restricted-app-backup-export.py'
with target.open('xb') as f:
    os.chmod(target,0o700); f.write((staging/'restricted-app-backup-export.py').read_bytes())
for directory in [home/'.local/state/home-ops/backups',home/'.local/state/app-backups']:
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
with auth.open('ab') as f:
    if original and not original.endswith(b'\n'): f.write(b'\n')
    f.write(''.join(lines).encode())
print('Three source-restricted, read-only backup keys installed; existing keys preserved.')
