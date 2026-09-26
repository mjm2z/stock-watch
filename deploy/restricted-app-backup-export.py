#!/usr/bin/env python3
"""Forced SSH command for read-only finalized backup exports; no shell execution."""
import json
import os
from pathlib import Path
import re
import shlex
import sys


ROOTS = {
    'homeops': '/home/mjm2z/.local/state/home-ops/backups',
    'stockwatch': '/var/backups/stock-watch',
    'postgres': '/home/mjm2z/.local/state/app-backups',
}


def restricted_command(kind, command):
    root = ROOTS[kind]
    args = shlex.split(command)
    if args[:3] != ['rsync', '--server', '--sender']:
        raise ValueError('Only read-only backup rsync is permitted')
    # Existing clients use the full source path. rrsync anchors absolute paths
    # inside its restricted root, so translate only the final source argument.
    if args[-1] == root or args[-1].startswith(root + '/'):
        args[-1] = '/' + args[-1][len(root):].lstrip('/')
    return root, shlex.join(args)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ROOTS:
        raise SystemExit('Unknown backup export')
    kind = sys.argv[1]
    command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    if kind == 'stockwatch' and command == 'stock-watch-latest':
        files = sorted(p for p in Path(ROOTS[kind]).iterdir()
                       if re.fullmatch(r'stock-watch-\d{8}T\d{12}Z\.db', p.name)
                       and p.is_file() and not p.is_symlink())
        if not files:
            raise SystemExit('No finalized StockWatch backup available')
        path = files[-1]
        print(json.dumps(dict(name=path.name, size=path.stat().st_size)))
        return
    try:
        root, command = restricted_command(kind, command)
    except ValueError as error:
        raise SystemExit(str(error))
    os.environ['SSH_ORIGINAL_COMMAND'] = command
    os.execv('/usr/bin/rrsync', ['rrsync', '-ro', root])


if __name__ == '__main__':
    main()
