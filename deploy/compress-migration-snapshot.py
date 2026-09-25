#!/usr/bin/env python3
"""Losslessly package a verified snapshot and verify the decompressed checksum."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import time


def compress(source, manifest, destination):
    expected = json.loads(manifest.read_text())
    if destination.exists() or source.resolve() == destination.resolve():
        raise ValueError('Refusing to replace an existing file')
    partial = destination.with_suffix(destination.suffix+'.partial')
    digest = hashlib.sha256()
    started = last_report = time.monotonic()
    total = 0
    fd = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as output, source.open('rb') as incoming:
        with gzip.GzipFile(filename='', fileobj=output, mode='wb', compresslevel=1, mtime=0) as archive:
            for chunk in iter(lambda: incoming.read(8*1024*1024), b''):
                archive.write(chunk)
                digest.update(chunk)
                total += len(chunk)
                if time.monotonic()-last_report >= 30:
                    print(f'Compressed {total}/{expected["bytes"]} source bytes...', flush=True)
                    last_report = time.monotonic()
        output.flush()
        os.fsync(output.fileno())
    if total != expected['bytes'] or digest.hexdigest() != expected['sha256']:
        raise ValueError('Source differs from verified snapshot; partial output not published')
    compression_seconds = time.monotonic()-started
    print('Compression complete; verifying decompressed contents...', flush=True)
    roundtrip = hashlib.sha256()
    with gzip.open(partial, 'rb') as incoming:
        for chunk in iter(lambda: incoming.read(8*1024*1024), b''):
            roundtrip.update(chunk)
    if roundtrip.hexdigest() != expected['sha256']:
        raise ValueError('Compressed snapshot failed round-trip verification')
    compressed_hash = hashlib.sha256()
    with partial.open('rb') as incoming:
        for chunk in iter(lambda: incoming.read(8*1024*1024), b''):
            compressed_hash.update(chunk)
    result = dict(source_bytes=total, source_sha256=expected['sha256'],
                  compressed_bytes=partial.stat().st_size, compressed_sha256=compressed_hash.hexdigest(),
                  compression_seconds=round(compression_seconds,2),
                  total_seconds=round(time.monotonic()-started,2), roundtrip_verified=True)
    # Hard-link publication is exclusive and cannot replace a concurrently created file.
    os.link(partial, destination)
    partial.unlink()
    with Path(str(destination)+'.json').open('x') as output:
        os.chmod(output.name,0o600)
        json.dump(result,output,indent=2)
        output.write('\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('destination',type=Path)
    args = parser.parse_args()
    print(json.dumps(compress(args.source,args.manifest,args.destination)))
