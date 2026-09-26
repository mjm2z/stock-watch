#!/usr/bin/env python3
"""Publish a verified final StockWatch export on a1347-m; NEVER start services.

The destination must still be the empty staging installation. By default the
source export stays intact. --use-verified-transfer-copy publishes the already
decompressed file directly, retaining its verified compressed recovery archive
and the original source-host data. No existing database/configuration is replaced.
"""
import argparse
import hashlib
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
from zoneinfo import ZoneInfo


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def checksum(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_transfer(source,manifest):
    """Prove byte identity with the source's integrity-checked SQLite snapshot."""
    archive=source/'stock-watch.db.gz'
    metadata=source/'stock-watch.db.gz.json'
    database=source/'stock-watch.db'
    if any(p.is_symlink() or not p.is_file() for p in (archive,metadata,database)):
        raise RuntimeError('Verified archive, metadata and decompressed file are required')
    transfer=json.loads(metadata.read_text())
    if (transfer.get('roundtrip_verified') is not True or
        transfer.get('source_bytes')!=manifest['bytes'] or
        transfer.get('source_sha256')!=manifest['sha256']):
        raise RuntimeError('Transfer metadata does not match the verified source snapshot')
    if (archive.stat().st_size!=transfer['compressed_bytes'] or
        checksum(archive)!=transfer['compressed_sha256']):
        raise RuntimeError('Compressed recovery archive failed verification')
    if database.stat().st_size!=manifest['bytes'] or checksum(database)!=manifest['sha256']:
        raise RuntimeError('Decompressed database differs from verified source snapshot')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export',type=Path)
    parser.add_argument('--use-verified-transfer-copy',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='a1347-m':
        raise SystemExit('Run as root on a1347-m only')
    freeze=load('freeze','final-stockwatch-export-root.py')
    if not freeze.outside_market(datetime.now(ZoneInfo('UTC'))):
        raise SystemExit('Refusing production publication during market hours')
    os.umask(0o077)
    source=args.export.resolve()
    if source.parent!=Path('/home/mjm2z/app-migration-20260924') or not re.fullmatch(r'stockwatch-final-\d{8}T\d{6}Z',source.name):
        raise RuntimeError('Expected a final export in protected migration staging')
    receipt=json.loads((source/'final-export.json').read_text())
    manifest=json.loads((source/'stock-watch.json').read_text())
    if (receipt.get('purpose')!='final-cutover' or receipt.get('writers_stopped') is not True or
        receipt.get('verified') is not True or receipt.get('database_sha256')!=manifest.get('sha256')):
        raise RuntimeError('Missing successful final source-export evidence')
    root=Path('/var/lib/stock-watch'); database=root/'stock-watch.db'; data=root/'data'
    environment=Path('/etc/stock-watch/stock-watch.env')
    if database.exists() or database.is_symlink() or environment.exists() or environment.is_symlink():
        raise RuntimeError('Existing destination database/configuration; refusing replacement')
    if root.is_symlink() or data.is_symlink() or not data.is_dir() or any(data.iterdir()):
        raise RuntimeError('Destination artifact directory is not empty staging')
    text=(source/'stock-watch.env').read_text()
    for line in text.splitlines():
        if line.startswith(('STOCK_WATCH_DATABASE_PATH=','STOCK_WATCH_DATA_PATH=')):
            key,value=line.split('=',1)
            expected=database if key=='STOCK_WATCH_DATABASE_PATH' else data
            if Path(value.strip().strip('\"\''))!=expected:
                raise RuntimeError('Custom source paths require explicit review')
    units=json.loads((source/'source-units.json').read_text())
    if not units or any(not re.fullmatch(r'stock-watch-[a-z0-9-]+\.(service|timer)',name) for name in units):
        raise RuntimeError('Unexpected source unit inventory')
    for name in units:
        state=freeze.unit_state(name)
        if state.get('ActiveState') not in ('inactive','failed') or freeze.busy(state):
            raise RuntimeError('Destination unit is not inactive: '+name)
    stamp_metadata=json.loads((source/'timer-stamps.json').read_text())
    for name in stamp_metadata:
        if not name.startswith('stamp-') or name[6:] not in units or not name.endswith('.timer'):
            raise RuntimeError('Unexpected timer timestamp name')
        if (Path('/var/lib/systemd/timers')/name).exists():
            raise RuntimeError('Existing destination timer history requires review: '+name)
    needed=(0 if args.use_verified_transfer_copy else manifest['bytes'])+20*1024**3
    if shutil.disk_usage(root).free < needed:
        raise RuntimeError('Insufficient disk reserve')
    artifacts=load('artifacts','verify-artifact-export.py')
    artifact_manifest=json.loads((source/'artifacts/manifest.json').read_text())
    if artifact_manifest.get('purpose')!='final-cutover':
        raise RuntimeError('Rehearsal artifacts cannot be published as final')
    artifacts.verify(source/'artifacts')
    if (source/'stock-watch.db').is_symlink(): raise RuntimeError('Unexpected database symlink')
    staged=root/('.'+source.name)
    staged.mkdir(mode=0o700)
    if args.use_verified_transfer_copy:
        if (source/'stock-watch.db').stat().st_dev!=root.stat().st_dev:
            raise RuntimeError('Direct publication requires the same filesystem')
        print('Verifying compressed recovery archive and decompressed database SHA-256...',flush=True)
        verify_transfer(source,manifest)
        published_database=source/'stock-watch.db'
        actual=manifest
    else:
        print('Copying final database; source export remains intact...',flush=True)
        shutil.copyfile(source/'stock-watch.db',staged/'stock-watch.db')
        with (staged/'stock-watch.db').open('rb') as stream: os.fsync(stream.fileno())
        snapshot=load('snapshot','sqlite-migration-snapshot.py')
        actual=snapshot.fingerprint(staged/'stock-watch.db',progress=True)
        if actual!=manifest: raise RuntimeError('Destination database failed final snapshot verification')
        published_database=staged/'stock-watch.db'
    verified_signature=published_database.stat()
    shutil.copytree(source/'artifacts/data',staged/'artifacts/data')
    shutil.copyfile(source/'artifacts/manifest.json',staged/'artifacts/manifest.json')
    artifacts.verify(staged/'artifacts')
    owner=pwd.getpwnam('stock-watch')
    current=published_database.stat()
    if (current.st_ino,current.st_size,current.st_mtime_ns)!=(verified_signature.st_ino,verified_signature.st_size,verified_signature.st_mtime_ns):
        raise RuntimeError('Database changed after verification')
    for path in [published_database,staged/'artifacts/data',*(staged/'artifacts/data').rglob('*')]:
        os.chown(path,owner.pw_uid,owner.pw_gid)
        os.chmod(path,0o700 if path.is_dir() else 0o600)
    # Preserve the staging unit definitions before replacing them with the exact
    # installed source definitions (including its backup-reader environment).
    previous=Path('/etc/stock-watch')/(source.name+'-previous-units')
    previous.mkdir(mode=0o700)
    for name in units:
        target=Path('/etc/systemd/system')/name
        if target.is_file(): shutil.copy2(target,previous/name)
        content=(source/name).read_text()
        target.write_text(content);os.chmod(target,0o644)
    with environment.open('x') as stream: stream.write(text)
    os.chmod(environment,0o600)
    os.link(published_database,database)  # Exclusive: never replace an existing database.
    published_database.unlink()
    (staged/'artifacts/data').rename(data)  # Replaces only the confirmed empty directory.
    for name,mtime_ns in stamp_metadata.items():
        target_stamp=Path('/var/lib/systemd/timers')/name
        with target_stamp.open('xb') as stream:
            stream.write((source/'timer-stamps'/name).read_bytes())
        os.chmod(target_stamp,0o644)
        os.utime(target_stamp,ns=(mtime_ns,mtime_ns))
    subprocess.run(['systemctl','daemon-reload'],check=True)
    (staged/'published.json').write_text(json.dumps(dict(
        source=str(source),database_sha256=actual['sha256'],services_started=False,
        compressed_recovery_retained=args.use_verified_transfer_copy,
        published_at=datetime.now(ZoneInfo('UTC')).isoformat()),indent=2)+'\n')
    print('Final database, artifacts, config and source units installed. No services started.',flush=True)
    print('Before activation, confirm source is still stopped and reconcile pending paper-order state.')


if __name__=='__main__': main()
