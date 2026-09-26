#!/usr/bin/env python3
"""Publish a reviewed config only if its live predecessor still matches."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

source, destination, expected = Path(sys.argv[1]), Path(sys.argv[2]).expanduser(), sys.argv[3]
if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
    raise SystemExit('Live config drifted; regenerate from current configuration')
json.loads(source.read_text())
os.umask(0o077)
tag = sys.argv[4] if len(sys.argv)>4 else 'before-app-cutover-20260925'
if not re.fullmatch(r'before-[a-z0-9-]+',tag):
    raise SystemExit('Invalid recovery-copy tag')
backup = destination.with_name(destination.name+'.'+tag)
with backup.open('xb') as stream:
    stream.write(destination.read_bytes())
staged = destination.with_name(destination.name+'.app-cutover-new')
with staged.open('xb') as stream:
    stream.write(source.read_bytes())
    stream.flush()
    os.fsync(stream.fileno())
os.replace(staged,destination)
print('Published reviewed configuration; predecessor retained:',backup)
