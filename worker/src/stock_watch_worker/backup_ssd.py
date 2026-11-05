"""Checksum-bound verification of closed exports on a restricted SSD receiver.

Standalone receiver deployment needs only this file and Python's standard library.
Never point this interface at a live SQLite database.
"""
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

RESERVE = 20 * 1024**3
TRANSFER_SECONDS = 2700
CHECK_SECONDS = 600
HASH_SECONDS = 600


def checksum(path, deadline, report):
    h = hashlib.sha256()
    count = 0
    last = time.monotonic()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024**2):
            if time.monotonic() >= deadline:
                raise TimeoutError('hashing stage deadline exceeded')
            h.update(block)
            count += len(block)
            if time.monotonic() - last >= 30:
                report('hashing', bytes_processed=count)
                last = time.monotonic()
    return h.hexdigest()


def validate_receipt(receipt, run_id, size, digest):
    expected = dict(version=1, run_id=run_id, bytes=size, sha256=digest,
                    status='ok', verification='sqlite_integrity_check_and_reopen')
    if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in expected.items()):
        raise RuntimeError('SSD verification receipt does not match this export')


def stop(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def remote_verify(path, config_path, deadline, report):
    config = json.loads(Path(config_path).read_text())
    for field in ('host', 'key', 'known_hosts'):
        if not isinstance(config.get(field), str) or not config[field] or config[field].startswith('-'):
            raise ValueError('Invalid SSD verifier ' + field)
    for field in ('key', 'known_hosts'):
        if not Path(config[field]).is_absolute():
            raise ValueError('SSD verifier credential paths must be absolute')
    report('hashing')
    digest = checksum(path, min(deadline, time.monotonic()+HASH_SECONDS), report)
    size = path.stat().st_size
    run_id = uuid.uuid4().hex
    command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
               '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
               '-o', 'Compression=no', '-o', 'UserKnownHostsFile='+config['known_hosts'],
               '-i', config['key'], config['host'], 'verify-stockwatch-v1', run_id,
               str(size), digest]
    phase = 'receiving'
    phase_deadline = min(deadline, time.monotonic()+TRANSFER_SECONDS+30)
    receipt = None
    report('ssd_transfer', bytes_total=size)
    with path.open('rb') as source, tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE, stderr=errors)
        try:
            buffer = b''
            last = time.monotonic()
            with selectors.DefaultSelector() as poller:
                poller.register(child.stdout, selectors.EVENT_READ)
                while True:
                    if time.monotonic() >= phase_deadline:
                        raise TimeoutError('SSD '+phase+' stage deadline exceeded')
                    if time.monotonic()-last >= 30:
                        report('ssd_'+phase)
                        last = time.monotonic()
                    if not poller.select(timeout=1):
                        continue
                    block = os.read(child.stdout.fileno(), 4096)
                    if not block:
                        break
                    buffer += block
                    if len(buffer) > 16384:
                        raise RuntimeError('Oversized SSD verifier output')
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        item = json.loads(line)
                        if item.get('event') == 'progress':
                            if item.get('run_id') != run_id or item.get('bytes_total') != size:
                                raise RuntimeError('Invalid SSD progress identity')
                            stage = item.get('phase')
                            if stage not in ('receiving', 'verifying') or (phase == 'verifying' and stage != phase):
                                raise RuntimeError('Invalid SSD stage transition')
                            if stage == 'verifying' and phase != stage:
                                if item.get('bytes_received') != size:
                                    raise RuntimeError('Incomplete SSD transfer')
                                phase = stage
                                phase_deadline = min(deadline, time.monotonic()+CHECK_SECONDS+30)
                            report('ssd_'+stage, bytes_processed=item.get('bytes_received'), bytes_total=size)
                        else:
                            if receipt is not None:
                                raise RuntimeError('Duplicate SSD receipt')
                            validate_receipt(item, run_id, size, digest)
                            receipt = item
            code = child.wait(timeout=max(.1, min(10, phase_deadline-time.monotonic())))
            if code or buffer or receipt is None:
                errors.seek(0)
                raise RuntimeError('SSD verifier failed: '+errors.read(2000).decode(errors='replace'))
        finally:
            stop(child)
            child.stdout.close()
    report('confirming_export')
    if checksum(path, min(deadline, time.monotonic()+HASH_SECONDS), report) != digest:
        raise RuntimeError('Export changed after SSD verification')
    return receipt


def receive(stream, path, size, digest, progress):
    h = hashlib.sha256()
    received = 0
    with path.open('xb') as target:
        while received < size:
            block = stream.read(min(8*1024**2, size-received))
            if not block:
                raise RuntimeError('Interrupted SSD transfer')
            target.write(block)
            h.update(block)
            received += len(block)
            progress(received)
        target.flush()
        os.fsync(target.fileno())
    if h.hexdigest() != digest:
        raise RuntimeError('SSD transfer checksum mismatch')


def check_database(path):
    uri = path.resolve().as_uri()+'?mode=ro&immutable=1'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute('PRAGMA cache_size=-65536')
        db.execute('PRAGMA mmap_size=536870912')
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('SQLite integrity check failed')
    # Generic reopen also supports StockWatch's auxiliary SQLite datasets.
    with closing(sqlite3.connect(uri, uri=True)) as db:
        tables = db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        if not tables:
            raise RuntimeError('Export has no application tables')
        table = tables[0][0].replace('"', '""')
        db.execute(f'SELECT * FROM "{table}" LIMIT 1').fetchall()


def receiver():
    args = shlex.split(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    if (len(args) != 4 or args[0] != 'verify-stockwatch-v1'
            or not re.fullmatch('[a-f0-9]{32}', args[1])
            or not re.fullmatch('[0-9]{1,12}', args[2])
            or not 512 <= int(args[2]) <= 64*1024**3
            or not re.fullmatch('[a-f0-9]{64}', args[3])):
        raise ValueError('Invalid StockWatch verifier request')
    _, run_id, raw_size, digest = args
    size = int(raw_size)
    os.umask(0o077)
    root = Path.home()/'.local/state/stock-watch-ssd-verifier'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = Path.home()/'.local/state/home-ops/ssd-verifier/worker.lock'
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.disk_usage(root).free < size+RESERVE:
            raise RuntimeError('SSD capacity would breach 20 GiB reserve')
        phase = 'receiving'
        last = 0
        def progress(count, force=False):
            nonlocal last
            if force or time.monotonic()-last >= 30:
                event = dict(event='progress',run_id=run_id,phase=phase,
                             bytes_received=count,bytes_total=size)
                (root/'progress.json').write_text(json.dumps(dict(event, observed_at=time.time()))+'\n')
                print(json.dumps(event), flush=True)
                last = time.monotonic()
        def expired(*_):
            raise TimeoutError('SSD '+phase+' stage interrupted')
        for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, expired)
        signal.alarm(TRANSFER_SECONDS)
        try:
            with tempfile.TemporaryDirectory(prefix='stage-',dir=root) as stage:
                path = Path(stage)/'export.db'
                receive(sys.stdin.buffer,path,size,digest,progress)
                phase = 'verifying'
                signal.alarm(CHECK_SECONDS+10)
                progress(size, True)
                with tempfile.TemporaryFile() as errors:
                    child = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--check',str(path)],
                                             stdout=errors,stderr=errors)
                    try:
                        deadline = time.monotonic()+CHECK_SECONDS
                        while child.poll() is None:
                            remaining = deadline-time.monotonic()
                            if remaining <= 0:raise TimeoutError('SQLite integrity stage timeout')
                            try:child.wait(timeout=min(30,remaining))
                            except subprocess.TimeoutExpired:progress(size,True)
                        if child.returncode:
                            errors.seek(0)
                            raise RuntimeError(errors.read(2000).decode(errors='replace'))
                    finally:stop(child)
                receipt = dict(version=1,run_id=run_id,bytes=size,sha256=digest,status='ok',
                               verification='sqlite_integrity_check_and_reopen',verified_at=time.time())
                receipts = root/'receipts';receipts.mkdir(exist_ok=True)
                (receipts/(run_id+'.json')).write_text(json.dumps(receipt)+'\n')
                print(json.dumps(receipt),flush=True)
        finally:signal.alarm(0)


if __name__ == '__main__':
    try:
        if len(sys.argv)==3 and sys.argv[1]=='--check':check_database(Path(sys.argv[2]))
        elif sys.argv[1:]==['--receive']:receiver()
        else:raise ValueError('Invalid invocation')
    except Exception as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
