#!/usr/bin/env python3
"""Verify and unpack a final StockWatch file archive into new private staging."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import sys
import tarfile


def main():
    if socket.gethostname().split('.')[0]!='a1347-m':
        raise SystemExit('Destination a1347-m only')
    archive=Path(sys.argv[1]).resolve()
    expected=sys.argv[2]
    base=Path.home()/'app-migration-20260924'
    if archive.parent!=base or not re.fullmatch(r'stockwatch-final-\d{8}T\d{6}Z-files\.tar\.gz',archive.name):
        raise RuntimeError('Unexpected archive location')
    metadata=json.loads(Path(str(archive)+'.json').read_text())
    if metadata['sha256']!=expected or archive.stat().st_size!=metadata['bytes']:
        raise RuntimeError('Archive metadata mismatch')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:
            raise RuntimeError('Transferred archive checksum mismatch')
    name=archive.name.removesuffix('-files.tar.gz')
    if metadata['source_export']!=name:
        raise RuntimeError('Source export identity mismatch')
    os.umask(0o077)
    output=base/name
    output.mkdir(mode=0o700)
    allowed={'artifacts','timer-stamps','stock-watch.json','stock-watch.env',
             'source-units.json','timer-stamps.json','paper-state-at-freeze.json','final-export.json'}
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            path=PurePosixPath(member.name)
            if path==PurePosixPath('.'):
                continue
            if (path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()) or
                (path.parts[0] not in allowed and not re.fullmatch(r'stock-watch-[a-z0-9-]+\.(service|timer)',str(path)))):
                raise RuntimeError('Unexpected archive entry')
        bundle.extractall(output,filter='data')
    for path in output.rglob('*'):
        os.chmod(path,0o700 if path.is_dir() else 0o600)
    receipt=json.loads((output/'final-export.json').read_text())
    manifest=json.loads((output/'stock-watch.json').read_text())
    if (receipt.get('purpose')!='final-cutover' or receipt.get('verified') is not True or
        receipt.get('writers_stopped') is not True or receipt['database_sha256']!=manifest['sha256']):
        raise RuntimeError('Missing final source verification')
    spec=importlib.util.spec_from_file_location('artifacts',Path(__file__).with_name('verify-artifact-export.py'))
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    result=verifier.verify(output/'artifacts')
    if result['purpose']!='final-cutover':
        raise RuntimeError('Rehearsal artifacts are not final data')
    print(json.dumps(dict(output=str(output),archive_verified=True,**result)),flush=True)


if __name__=='__main__':
    main()
