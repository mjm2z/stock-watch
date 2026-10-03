"""Install a reviewed research verifier and launch it under the StockWatch identity."""
import hashlib,json,os,pathlib,pwd,shutil,socket,subprocess,time
from urllib.request import urlopen

def main():
    if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='a1347-m':raise SystemExit('Run with sudo on a1347-m')
    receipt=json.loads(pathlib.Path('/opt/stock-watch/installed-release.json').read_text())
    if receipt['revision']!='992d909e0ec6eca061e4303b0eff3e86c65275f0':raise SystemExit('Expected reviewed LEAN app release is not installed')
    with urlopen('http://127.0.0.1:3001/api/health/lean',timeout=10) as response:health=json.load(response)
    if not health.get('healthy') or not health.get('configured'):raise SystemExit('LEAN bridge must be healthy before historical verification')
    source=pathlib.Path(__file__).with_name('verify-lean-history.py')
    if hashlib.sha256(source.read_bytes()).hexdigest()!=EXPECTED_SHA256:raise SystemExit('Historical verifier source differs from reviewed content')
    account=pwd.getpwnam('stock-watch');directory=pathlib.Path('/var/lib/stock-watch/lean-verification')
    directory.mkdir(mode=0o750,exist_ok=True);os.chown(directory,0,account.pw_gid);directory.chmod(0o750)
    target=directory/'verify-history.py';shutil.copyfile(source,target);os.chown(target,0,account.pw_gid);target.chmod(0o640)
    unit='stock-watch-lean-history-'+time.strftime('%Y%m%d%H%M%S')
    subprocess.run(['systemd-run','--no-block','--unit='+unit,'--uid=stock-watch','--gid=stock-watch','--working-directory=/opt/stock-watch/worker','--property=Type=oneshot','--property=EnvironmentFile=/etc/stock-watch/stock-watch.env','--property=TimeoutStartSec=10min','--property=CPUQuota=100%','--property=MemoryMax=512M','--property=UMask=0077','--property=Nice=10','/opt/stock-watch/.venv/bin/python',str(target),'--apply'],check=True)
    print('Research verification started as '+unit+'. No trading authority changes.',flush=True)

EXPECTED_SHA256='e604aa097fed0837700d9208f2fcff58cd508d3ec8fc1e85c730f8009c11835e'
if __name__=='__main__':main()
