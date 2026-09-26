#!/usr/bin/env python3
"""Publish a reviewed config only if its live predecessor still matches."""
import hashlib
import json
import os
from pathlib import Path
import sys

source, destination, expected = Path(sys.argv[1]), Path(sys.argv[2]).expanduser(), sys.argv[3]
if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
    raise SystemExit('Live config drifted; regenerate from current configuration')
json.loads(source.read_text())
os.umask(0o077)
backup = destination.with_name(destination.name+'.before-app-cutover-20260925')
with backup.open('xb') as stream:
    stream.write(destination.read_bytes())
staged = destination.with_name(destination.name+'.app-cutover-new')
with staged.open('xb') as stream:
    stream.write(source.read_bytes())
    stream.flush()
    os.fsync(stream.fileno())
os.replace(staged,destination)
print('Published reviewed configuration; predecessor retained:',backup)
