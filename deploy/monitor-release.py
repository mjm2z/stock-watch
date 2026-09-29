#!/usr/bin/env python3
"""Read-only release monitor. Runs over one SSH connection; needs no packages."""
import argparse
from datetime import datetime
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


def command(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8)
        return result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return '(status query timed out)'


def disk_snapshot():
    result = {}
    for line in Path('/proc/diskstats').read_text().splitlines():
        fields = line.split()
        name = fields[2]
        if not Path('/sys/block', name).exists() or name.startswith(('loop', 'ram', 'dm-')):
            continue
        result[name] = (int(fields[5]) * 512, int(fields[9]) * 512, int(fields[12]))
    return result


def monitor(args):
    previous, sampled = disk_snapshot(), time.monotonic()
    print('Read-only monitor; Ctrl-C stops monitoring, not the installer.', flush=True)
    print('Disk rates are HOST-WIDE, not a release completion percentage.', flush=True)
    for sample in range(args.samples or 10**9):
        print('\n' + datetime.now().astimezone().isoformat(timespec='seconds'), flush=True)
        state = command('systemctl', 'show', args.unit, '--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp,ExecMainStatus')
        print(state, flush=True)
        properties = dict(line.split('=', 1) for line in state.splitlines() if '=' in line)
        main = int(properties.get('MainPID', '0'))
        rows = []
        for line in command('ps', '-eo', 'pid=,ppid=,etime=,stat=,pcpu=,comm=').splitlines():
            fields = line.split(None, 5)
            if len(fields) == 6 and fields[0].isdigit():
                rows.append(fields)
        owned = {str(main)} if main else set()
        while True:
            expanded = owned | {r[0] for r in rows if r[1] in owned}
            if expanded == owned:
                break
            owned = expanded
        print('Installer process tree: PID / parent / elapsed / state / CPU% / program', flush=True)
        for row in rows:
            if row[0] in owned:
                print('  ' + ' '.join(row), flush=True)
        print('D = waiting for kernel I/O; this alone does not mean a stall.', flush=True)
        now, current = time.monotonic(), disk_snapshot()
        if sample:
            elapsed = now - sampled
            for device, counters in current.items():
                if device in previous:
                    old = previous[device]
                    print(f'{device}: read {(counters[0]-old[0])/elapsed/1048576:.2f} MiB/s, '
                          f'write {(counters[1]-old[1])/elapsed/1048576:.2f} MiB/s, '
                          f'busy {(counters[2]-old[2])/elapsed/10:.1f}% (host-wide)', flush=True)
        previous, sampled = current, now
        pressure = Path('/proc/pressure/io')
        if pressure.exists():
            print('I/O pressure: ' + pressure.read_text().strip().replace('\n', ' | '), flush=True)
        print('Last log message (may describe an earlier phase):', flush=True)
        print(command('journalctl', '-u', args.unit, '-n', '1', '--no-pager'), flush=True)
        if properties.get('ActiveState') in ('inactive', 'failed'):
            print('Unit stopped. Verify installed receipt and service health before declaring success.', flush=True)
            return
        if not args.watch or (args.samples and sample + 1 >= args.samples):
            return
        time.sleep(args.interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='a1347-m')
    parser.add_argument('--unit', default='stock-watch-release-6e7120fe1e9d.service')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=int, default=30)
    parser.add_argument('--samples', type=int, default=0, help='Stop after N samples; zero watches until stopped')
    parser.add_argument('--local', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch(r'stock-watch-release-[0-9a-f]{12,40}(?:\.service)?', args.unit):
        parser.error('Expected a StockWatch release unit with a hexadecimal revision')
    if args.interval < 2 or args.samples < 0 or args.host.startswith('-'):
        parser.error('Use interval >= 2, samples >= 0 and a valid SSH host')
    if args.local:
        monitor(args)
    else:
        remote = ['python3', '-u', '-', '--local', '--unit', args.unit,
                  '--interval', str(args.interval), '--samples', str(args.samples)]
        if args.watch:
            remote.append('--watch')
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                                 args.host, shlex.join(remote)], input=Path(__file__).read_text(), text=True)
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
