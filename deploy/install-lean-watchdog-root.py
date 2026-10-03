"""Install only the dedicated LEAN monitor, reusing existing protected transport."""
import hashlib,json,os,pathlib,pwd,socket,subprocess
from urllib.request import urlopen
EXPECTED='21c667de60aec0b9d3b4269150c9cd696a1fa1ddd3b74b765a07da87c5b9c851'
def main():
    if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='a1347-j':raise SystemExit('Run with sudo on a1347-j')
    source=pathlib.Path(__file__).with_name('lean-watchdog.py')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=EXPECTED:raise SystemExit('Monitor source differs from reviewed digest')
    with urlopen('http://192.168.4.35:3001/api/health/lean',timeout=10) as response:
        health=json.load(response)
    if not health.get('healthy') or health.get('stale'):raise SystemExit('Establish healthy baseline before monitor installation')
    account=pwd.getpwnam('mjm2z')
    config=json.loads(pathlib.Path('/home/mjm2z/.config/home-ops/watchdog-migration.json').read_text())
    if config.get('delivery_transport')!='telegram' or not config.get('delivery_enabled',True):raise SystemExit('Existing Telegram transport must be enabled')
    if not pathlib.Path(config['telegram_credentials']).is_file():raise SystemExit('Existing credential file missing')
    destination=pathlib.Path('/opt/stockwatch-lean-watchdog');destination.mkdir(mode=0o755,exist_ok=True)
    target=destination/'watchdog.py'
    if target.exists() and target.read_bytes()!=source.read_bytes():raise SystemExit('Different monitor already installed; review upgrade first')
    target.write_bytes(source.read_bytes());target.chmod(0o644)
    state=pathlib.Path('/home/mjm2z/.local/state/stockwatch-lean-watchdog');state.mkdir(mode=0o700,exist_ok=True);os.chown(state,account.pw_uid,account.pw_gid)
    unit='''[Unit]
Description=Independent StockWatch LEAN research availability
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=mjm2z
Group=mjm2z
ExecStart=/usr/bin/python3 /opt/stockwatch-lean-watchdog/watchdog.py
Restart=on-failure
RestartSec=20
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/home/mjm2z/.local/state/stockwatch-lean-watchdog
[Install]
WantedBy=multi-user.target
'''
    pathlib.Path('/etc/systemd/system/stockwatch-lean-watchdog.service').write_text(unit)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','stockwatch-lean-watchdog.service'],check=True)
    subprocess.run(['systemctl','is-active','--quiet','stockwatch-lean-watchdog.service'],check=True)
    print('Dedicated LEAN monitor installed. Existing HomeOps watchdog unchanged. Outage/recovery delivery still requires verification.')
if __name__=='__main__':main()
