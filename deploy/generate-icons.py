#!/usr/bin/env python3
"""Regenerate all brand variants from app/icon.svg (requires librsvg)."""
from pathlib import Path
import struct
import subprocess

root = Path(__file__).resolve().parents[1]
source = root/'app/icon.svg'
def png(size):
    return subprocess.check_output(['rsvg-convert', '--width', str(size), '--height', str(size), str(source)])
(root/'app/apple-icon.png').write_bytes(png(180))
sizes = (16, 32, 48, 64, 128, 256)
images = [png(size) for size in sizes]
header = struct.pack('<HHH', 0, 1, len(sizes))
offset = 6 + 16*len(sizes)
entries = []
for size, data in zip(sizes, images):
    entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
    offset += len(data)
(root/'app/favicon.ico').write_bytes(header + b''.join(entries) + b''.join(images))
print('Generated favicon.ico and apple-icon.png from app/icon.svg')
