#!/usr/bin/env python3
"""Verify and unpack a transferred snapshot without deleting its archive."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path


def decompress(archive, manifest, destination):
    expected=json.loads(manifest.read_text())
    transfer=json.loads(Path(str(archive)+'.json').read_text())
    if destination.exists() or destination.is_symlink():
        raise ValueError('Refusing to replace an existing destination')
    if (transfer.get('roundtrip_verified') is not True or
        transfer.get('source_sha256')!=expected['sha256'] or transfer.get('source_bytes')!=expected['bytes']):
        raise ValueError('Transfer metadata does not match the snapshot manifest')
    compressed_hash=hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''): compressed_hash.update(chunk)
    if archive.stat().st_size!=transfer['compressed_bytes'] or compressed_hash.hexdigest()!=transfer['compressed_sha256']:
        raise ValueError('Transferred archive checksum mismatch')
    partial=Path(str(destination)+'.partial')
    fd=os.open(partial,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    digest=hashlib.sha256();total=0
    with os.fdopen(fd,'wb') as output,gzip.open(archive,'rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            total+=len(chunk)
            if total>expected['bytes']: raise ValueError('Archive expands beyond the expected snapshot size')
            digest.update(chunk);output.write(chunk)
        output.flush();os.fsync(output.fileno())
    if total!=expected['bytes'] or digest.hexdigest()!=expected['sha256']:
        raise ValueError('Decompressed snapshot differs from the verified source')
    os.link(partial,destination)
    partial.unlink()
    return dict(verified=True,bytes=total,sha256=digest.hexdigest(),archive_retained=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    print(json.dumps(decompress(args.archive,args.manifest,args.destination)))
