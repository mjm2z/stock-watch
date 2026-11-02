#!/usr/bin/env python3
"""Verified PostgreSQL bundles with restore-gated daily/weekly retention."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time

NAME = re.compile(r'\d{8}T\d{12}Z')


def retention(root, policy, apply=False):
    """Only owned complete bundles; restore proof gates pruning, never copy success."""
    folders = sorted(p for p in root.iterdir() if NAME.fullmatch(p.name) and p.is_dir() and not p.is_symlink())
    items, dates = [], []
    for folder in folders:
        try:
            metadata = json.loads((folder/'bundle.json').read_text())
            captured = datetime.fromisoformat(metadata['recovery_point_at'])
            if captured.tzinfo is None: raise ValueError('Missing recovery timezone')
            captured = captured.astimezone(timezone.utc)
            expected = {'jobwatch.dump','jobwatch.json','radar.dump','radar.json'}
            if metadata.get('format') != 1 or set(metadata['files']) != expected:
                raise ValueError('Incomplete bundle')
            if any(p.is_symlink() or not p.is_file() or p.name not in expected|{'bundle.json','verified.json'} for p in folder.iterdir()):
                raise ValueError('Unrecognized bundle contents')
            dates.append((folder.name,captured))
            reason = None
        except (OSError, ValueError, KeyError, TypeError):
            reason = 'unrecognized bundle; review required'
        files = {p.name: {'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns,'inode':p.stat().st_ino}
                 for p in folder.iterdir() if p.is_file() and not p.is_symlink()}
        items.append(dict(name=folder.name, files=files, reason=reason,
                          allocated_bytes=sum(p.stat().st_blocks*512 for p in folder.iterdir() if p.is_file() and not p.is_symlink())))
    days, weeks, keep = set(), set(), set(policy.get('pins', []))
    for name, captured in sorted(dates,key=lambda x:x[1],reverse=True):
        day, week = captured.date(), captured.isocalendar()[:2]
        if day not in days and len(days)<7:
            days.add(day); keep.add(name)
        if week not in weeks and len(weeks)<4:
            weeks.add(week); keep.add(name)
    for item in items:
        item['action'] = 'keep' if item['reason'] or item['name'] in keep else 'delete'
        item['reason'] = item['reason'] or ('retained daily/weekly or pinned bundle' if item['action']=='keep' else 'outside seven daily/four weekly periods')
    result = dict(policy='7 daily + 4 weekly UTC periods; pins preserved',items=items,
        reclaimable_bytes=sum(i['allocated_bytes'] for i in items if i['action']=='delete'),
        retained_count=sum(i['action']=='keep' for i in items),
        retained_allocated_bytes=sum(i['allocated_bytes'] for i in items if i['action']=='keep'))
    if apply:
        proof = policy.get('restore_proof', {})
        if (not policy.get('enabled') or not proof.get('verified')
                or proof.get('verification') != 'isolated_restore_and_all_table_fingerprints'
                or set(proof.get('apps', [])) != {'jobwatch','radar'}):
            raise RuntimeError('Retention requires an approved isolated restore receipt')
        if not dates or not 0 <= (datetime.now(timezone.utc)-max(t for _,t in dates)).total_seconds() <= 30*3600:
            raise RuntimeError('Retention requires a fresh recovery bundle')
        # One budget for the entire validation pass, not one hour per bundle.
        deadline = time.monotonic()+3600
        # Validate both retained coverage and deletion candidates before deleting anything.
        for item in items:
            if not item['reason'].startswith('unrecognized'):
                verify_bundle(root/item['name'], deadline)
        if retention(root,policy)['items'] != items:
            raise RuntimeError('Bundle inventory changed after dry run')
        for item in items:
            if item['action']=='delete':
                folder=root/item['name']
                for name in item['files']:
                    (folder/name).unlink()
                folder.rmdir()
        result['reclaimed_bytes']=result['reclaimable_bytes']
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(path, deadline=None):
    deadline = time.monotonic()+3600 if deadline is None else deadline
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            if time.monotonic() >= deadline:
                raise TimeoutError('Backup checksum verification exceeded its deadline')
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(directory, deadline=None):
    deadline = time.monotonic()+3600 if deadline is None else deadline
    metadata = json.loads((directory/'bundle.json').read_text())
    if metadata.get('format') != 1 or set(metadata['files']) != {
            'jobwatch.dump', 'jobwatch.json', 'radar.dump', 'radar.json'}:
        raise ValueError('Incomplete backup bundle')
    for name, digest in metadata['files'].items():
        path = directory/name
        if path.is_symlink() or checksum(path, deadline) != digest:
            raise ValueError('Backup checksum mismatch: '+name)
    for app, required in [('jobwatch', 'jobs'), ('radar', 'raw_posts')]:
        manifest = json.loads((directory/(app+'.json')).read_text())
        if manifest.get('format') != 3 or f'"public"."{required}"' not in manifest.get('tables', {}):
            raise ValueError('Missing application tables')
        if manifest['dump_sha256'] != metadata['files'][app+'.dump']:
            raise ValueError('Dump does not match snapshot manifest')
        subprocess.run(['/usr/lib/postgresql/16/bin/pg_restore', '--list',
                        str(directory/(app+'.dump'))], check=True, stdout=subprocess.DEVNULL, timeout=max(.01,min(60,deadline-time.monotonic())))
    return metadata


def run(command, heartbeat):
    with subprocess.Popen(command) as child:
        deadline = time.monotonic()+3600
        while True:
            try:
                code = child.wait(timeout=30)
                if code:
                    raise subprocess.CalledProcessError(code, command)
                return
            except subprocess.TimeoutExpired:
                heartbeat()
                if time.monotonic()>=deadline:
                    child.terminate()
                    try: child.wait(timeout=10)
                    except subprocess.TimeoutExpired: child.kill(); child.wait()
                    raise TimeoutError('Backup subprocess exceeded one hour')


def create(home, state, heartbeat):
    for app in ('job-watch', 'app-demand-radar'):
        if not (home/'.config/app-migration'/f'{app}.cutover-ready').is_file():
            raise RuntimeError('Both applications must finish cutover before production backups')
    recovery_point = now()  # Conservative earliest time, not end-of-backup time.
    ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    work = state/'work'/ident
    work.mkdir(parents=True, mode=0o700)
    script = home/'.local/lib/app-migration/postgres-migration-snapshot.mjs'
    for app, code in [('jobwatch', 'job-watch'), ('radar', 'app-demand-radar')]:
        root = home/code/('backend' if app == 'radar' else '')
        run(['/usr/local/bin/node', '--env-file='+str(home/'.config'/code/'runtime.env'),
             str(script), str(root), str(work/app)], heartbeat)
    files = {name: checksum(work/name) for name in
             ('jobwatch.dump', 'jobwatch.json', 'radar.dump', 'radar.json')}
    (work/'bundle.json').write_text(json.dumps(dict(format=1, recovery_point_at=recovery_point, files=files), indent=2)+'\n')
    metadata = verify_bundle(work)
    for path in work.iterdir():
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
    destination = home/'.local/state/app-backups'/ident
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    work.rename(destination)
    return metadata, destination


def pull(home, state, heartbeat):
    incoming = state/'incoming'
    incoming.mkdir(parents=True, exist_ok=True, mode=0o700)
    ssh = f'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 -i {home}/.ssh/app_postgres_backup_pull'
    source='mjm2z@192.168.4.35:/home/mjm2z/.local/state/app-backups/'
    inventory=subprocess.run(['rsync','--list-only','-e',ssh,source],capture_output=True,text=True,timeout=60,check=True)
    names=[line.split()[-1].rstrip('/') for line in inventory.stdout.splitlines() if line.startswith('d') and line.split()]
    names=[name for name in names if NAME.fullmatch(name)]
    if not names:
        raise RuntimeError('No finalized production PostgreSQL backup exists')
    ident=max(names); latest=incoming/ident
    if latest.is_symlink(): raise RuntimeError('Unsafe backup destination')
    if not latest.exists():
        pending=state/'work'/('pull-'+ident)
        if pending.is_symlink(): raise RuntimeError('Unsafe staging directory')
        pending.mkdir(parents=True,exist_ok=True,mode=0o700)
        run(['rsync','-ac','--partial','--timeout=120','--include=*.dump','--include=*.json',
             '--exclude=*','-e',ssh,source+ident+'/',str(pending)+'/'],heartbeat)
        metadata = verify_bundle(pending)
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(metadata['recovery_point_at'])).total_seconds()
        if not 0 <= age <= 30*3600: raise RuntimeError('Staged backup is stale or future-dated')
        pending.rename(latest)
    metadata = verify_bundle(latest)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(metadata['recovery_point_at'])).total_seconds()
    if not 0 <= age <= 30*3600:
        raise RuntimeError('Newest backup is stale or has a future recovery timestamp')
    # Keep the verified bundle in place; a receipt is published only after checks.
    (latest/'verified.json').write_text(json.dumps(dict(verified_at=now(),
        verification='sha256_and_pg_restore_archive_listing'), indent=2)+'\n')
    return metadata, latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['create','pull'])
    parser.add_argument('--retention-only',action='store_true')
    parser.add_argument('--apply-retention',action='store_true')
    args = parser.parse_args()
    expected = 'a1347-m' if args.mode == 'create' else 'a1347-d'
    if socket.gethostname().split('.')[0] != expected or os.geteuid() == 0:
        raise SystemExit('Run unprivileged on '+expected)
    os.umask(0o077)
    home = Path.home()
    if not (home/'.config/app-migration/postgres-backups.cutover-ready').is_file():
        raise SystemExit('Production backup activation marker is absent')
    state = home/'.local/state/app-postgres-backups'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state/'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        root=home/'.local/state/app-backups' if args.mode=='create' else state/'incoming'
        policy_path=home/'.config/app-migration/backup-retention.json'
        policy=json.loads(policy_path.read_text()) if policy_path.is_file() else {}
        if args.retention_only:
            manifest=retention(root,policy)
            (state/'retention-plan.json').write_text(json.dumps(manifest,indent=2)+'\n')
            if args.apply_retention:
                manifest=retention(root,policy,True)
                (state/'retention-result.json').write_text(json.dumps(manifest,indent=2)+'\n')
            print(json.dumps(manifest,indent=2))
            return
        status = home/'.local/state/home-ops'/('app-postgres-'+args.mode+'-status.json')
        status.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = dict(job='app-postgres-'+args.mode, run_id='postgres:'+now(),
                      started_at=now(), status='running', verification='unverified')
        def save():
            record['observed_at'] = now()
            temporary = status.with_suffix('.next')
            temporary.write_text(json.dumps(record, indent=2)+'\n')
            temporary.replace(status)
        save()
        try:
            if shutil.disk_usage(state).free < 50*1024**3:
                raise RuntimeError('Less than 50 GiB free; preserve earlier backups and review storage')
            metadata, destination = (create if args.mode == 'create' else pull)(home, state, save)
            record.update(status='ok', recovery_point_at=metadata['recovery_point_at'],
                          destination=str(destination), verification='sha256_and_pg_restore_archive_listing',
                          summary='Both application backups passed checksums and archive listing')
            manifest=retention(root,policy)
            (state/'retention-plan.json').write_text(json.dumps(manifest,indent=2)+'\n')
            if policy.get('enabled'): manifest=retention(root,policy,True)
            record['retention']={k:v for k,v in manifest.items() if k!='items'}
        except Exception as error:
            record.update(status='failed', diagnostic=str(error), summary='Application PostgreSQL backup failed')
            raise
        finally:
            record['finished_at'] = now()
            save()


if __name__ == '__main__':
    main()
