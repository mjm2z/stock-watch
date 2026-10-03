#!/usr/bin/env python3
"""Run on a1990: review by default; sudo with --apply activates LAN routing."""
import argparse
import difflib
import os
from pathlib import Path
import shlex
import socket
import subprocess
import tempfile
import time
import urllib.request

SITE = Path('/etc/home-ops/lan-proxy.conf')
DNS = Path('/etc/systemd/system/sandbox-dns.service')
ROUTE = '''    server {
        listen 80;
        listen 3001;
        server_name stockwatch.home.arpa;
        allow 192.168.4.0/22;
        allow 127.0.0.0/8;
        deny all;
        client_max_body_size 2m;
        location / {
            proxy_pass http://192.168.4.35:3001;
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_cache off;
            proxy_read_timeout 1h;
        }
    }
'''


def check_http(host, path, port=80):
    request = urllib.request.Request(f'http://127.0.0.1:{port}' + path, headers={'Host': host})
    for attempt in range(10):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError('Unexpected HTTP response')
            return
        except OSError:
            if attempt == 9:
                raise
            time.sleep(.5)


def render(old_site, old_dns):
    if 'server_name ops.home.arpa;' not in old_site or not old_site.endswith('}\n'):
        raise SystemExit('Unexpected shared proxy configuration; review manually')
    if 'server_name stockwatch.home.arpa;' in old_site and ROUTE not in old_site:
        raise SystemExit('Existing StockWatch route differs; review manually')
    new_site = old_site if ROUTE in old_site else old_site[:-2] + ROUTE + '}\n'
    before = '--address=/stockwatch.home.arpa/192.168.4.35'
    after = '--address=/stockwatch.home.arpa/192.168.4.36'
    if old_dns.count(before) + old_dns.count(after) != 1:
        raise SystemExit('Unexpected StockWatch DNS registration; review manually')
    new_dns = old_dns.replace(before, after)
    return new_site, new_dns


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if socket.gethostname() != 'a1990':
        raise SystemExit('Run on a1990')
    old_site, old_dns = SITE.read_text(), DNS.read_text()
    new_site, new_dns = render(old_site, old_dns)
    for path, old, new in [(SITE, old_site, new_site), (DNS, old_dns, new_dns)]:
        print(''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=str(path), tofile=str(path))), end='')
    if not args.apply:
        return
    if os.geteuid() != 0:
        raise SystemExit('--apply requires sudo')
    command = next(line.removeprefix('ExecStart=') for line in new_dns.splitlines() if line.startswith('ExecStart='))
    subprocess.run(['/usr/sbin/dnsmasq', '--test', *shlex.split(command)[1:]], check=True)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.conf') as config:
        config.write(new_site)
        config.flush()
        subprocess.run(['/usr/sbin/nginx', '-t', '-c', config.name], check=True)
    if ROUTE not in old_site:
        with socket.socket() as probe:
            probe.bind(('0.0.0.0', 3001))
    if SITE.read_text() != old_site or DNS.read_text() != old_dns:
        raise SystemExit('Configuration changed during review; retry')
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for path, old in [(SITE, old_site), (DNS, old_dns)]:
        path.with_name(path.name + '.before-stockwatch-' + stamp).write_text(old)
    try:
        SITE.write_text(new_site)
        DNS.write_text(new_dns)
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
        subprocess.run(['systemctl', 'restart', 'sandbox-http', 'sandbox-dns'], check=True)
        for host, path in [('stockwatch.home.arpa', '/api/health'), ('jobwatch.home.arpa', '/api/health'), ('ops.home.arpa', '/api/health'), ('sandbox.home.arpa', '/')]:
            check_http(host, path)
        check_http('stockwatch.home.arpa:3001', '/api/health', port=3001)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'sandbox-http', 'sandbox-dns', 'sandbox-https'], check=True)
    except Exception:
        SITE.write_text(old_site)
        DNS.write_text(old_dns)
        subprocess.run(['systemctl', 'daemon-reload'], check=False)
        subprocess.run(['systemctl', 'restart', 'sandbox-http', 'sandbox-dns'], check=False)
        raise
    print('Active: http://stockwatch.home.arpa/ (DNS caches may need to expire)')


if __name__ == '__main__':
    main()
