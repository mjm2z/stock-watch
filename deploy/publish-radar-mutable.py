#!/usr/bin/env python3
"""Publish frozen Radar mutable files; retain archive and previous staging data."""
import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    archive = Path(sys.argv[1]).resolve()
    expected = sys.argv[2]
    home = Path.home()
    if socket.gethostname().split('.')[0] != 'a1347-m':
        raise SystemExit('Destination a1347-m only')
    if (home/'.config/app-migration/app-demand-radar.cutover-ready').exists():
        raise RuntimeError('Destination has already been activated')
    status = subprocess.run(['systemctl','--user','is-active','--quiet','app-demand-radar.service'])
    if status.returncode not in (3,4):
        raise RuntimeError('Destination service must be inactive')
    if sha(archive) != expected:
        raise RuntimeError('Archive checksum mismatch')
    os.umask(0o077)
    root = archive.parent/'radar-final-mutable-expanded'
    root.mkdir(mode=0o700)
    with tarfile.open(archive) as bundle:
        bundle.extractall(root, filter='data')
    previous = archive.parent/'radar-before-final-mutable'
    previous.mkdir(mode=0o700)
    config = Path('app-demand-radar/backend/src/config')
    files = list((root/config).glob('*.json'))
    for directory in ('app-demand-radar/backend/reports',
                      'app-demand-radar/backend/backups', '.local/state/app-demand-radar'):
        files.extend(p for p in (root/directory).rglob('*') if p.is_file())
    for source in files:
        if source.is_symlink():
            raise RuntimeError('Unexpected mutable-file symlink')
        relative = source.relative_to(root)
        target = home/relative
        if target.is_symlink():
            raise RuntimeError('Unexpected destination symlink')
        if target.exists():
            saved = previous/relative
            saved.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        shutil.copy2(source,target)
        os.chmod(target,0o600)
        if sha(source) != sha(target):
            raise RuntimeError('Published file mismatch: '+str(relative))
    print(f'Published and checksum-verified {len(files)} mutable files; previous staging files retained.')


if __name__ == '__main__':
    main()
