#!/usr/bin/env python3
"""Verify every exported artifact and reject missing, changed, or extra files."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import time


def verify(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    expected = {}
    for record in manifest['files']:
        name = record['path']
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or str(path) != name or name in expected:
            raise ValueError('Unsafe or duplicate artifact path in manifest')
        expected[name] = record
    actual = set()
    total = 0
    last_report = time.monotonic()
    for path in sorted((root / 'data').rglob('*')):
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        name = path.relative_to(root / 'data').as_posix()
        if not stat.S_ISREG(metadata.st_mode) or name not in expected:
            raise ValueError(f'Unexpected artifact: {name}')
        record = expected[name]
        if metadata.st_size != record['bytes']:
            raise ValueError(f'Artifact size mismatch: {name}')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != record['sha256']:
            raise ValueError(f'Artifact checksum mismatch: {name}')
        actual.add(name)
        total += metadata.st_size
        if time.monotonic() - last_report > 20:
            print(f'Verified {len(actual)}/{len(expected)} artifacts...', flush=True)
            last_report = time.monotonic()
    if actual != set(expected):
        raise ValueError(f'Missing {len(set(expected) - actual)} artifacts')
    return dict(verified=True, files=len(actual), bytes=total, purpose=manifest['purpose'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.export)))
