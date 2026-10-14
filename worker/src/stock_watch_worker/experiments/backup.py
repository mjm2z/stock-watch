"""Verified auxiliary backups and content-preserving research artifact copies."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from ..backup import create_sqlite_backup

def auxiliary_backups(database,destination,keep):
    database=Path(database).resolve(); destination=Path(destination).resolve()
    names=(database.name+'.experiment-evidence.db',database.name+'.bitcoin-history.db','manual-paper.db','market-data.db')
    results=[]
    def readable(path,directory=False):
        reader=os.environ.get('STOCK_WATCH_BACKUP_READER')
        if reader: subprocess.run(['setfacl','-m',f'u:{reader}:'+('r-x' if directory else 'r--'),str(path)],check=True)
    for name in names:
        source=database.with_name(name)
        if source.exists():
            target=destination/'auxiliary'/name; target.mkdir(parents=True,exist_ok=True)
            readable(target.parent,True); readable(target,True)
            results.append(create_sqlite_backup(source,target,keep=keep))
    source=Path(str(database)+'.systems-data')
    if source.exists():
        for file in source.rglob('*'):
            if any(p.startswith('.experiment-staging-') for p in file.relative_to(source).parts): continue
            if file.is_symlink(): raise ValueError('Research artifact symlink is not supported')
            if not file.is_file() or file.name.endswith(('-wal','-shm')): continue
            target=destination/'research-artifacts'/file.relative_to(source)
            target.parent.mkdir(parents=True,exist_ok=True)
            for directory in (target.parent,*target.parent.parents):
                if directory==destination: break
                readable(directory,True)
            with file.open('rb') as stream: checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            if target.exists():
                with target.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=checksum: raise ValueError('Existing archived artifact changed')
            else:
                temporary=target.with_name('.'+target.name+'.copying')
                shutil.copyfile(file,temporary)
                with temporary.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=checksum: raise ValueError('Artifact verification failed')
                temporary.replace(target)
            readable(target)
    return results
