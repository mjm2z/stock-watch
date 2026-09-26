#!/usr/bin/env python3
"""Apply a reviewed chart-only worker fix without a database migration or web restart."""
import argparse
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
import shutil,socket,subprocess,time
from zipfile import ZipFile

OLD_SHA='147370d43bf451f6920a1f86357779e2a67b7aa7ed0614d82e97c47b67ce30a5'
BASE='fc3086a257c4628364821dd0a021402b5224d33b'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(*args):subprocess.run(args,check=True)
def output(*args):return subprocess.check_output(args,text=True).strip()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    if socket.gethostname().split('.')[0]!='a1347-m':raise SystemExit('Run on a1347-m')
    source=args.source.resolve()
    if source.parent!=Path('/home/mjm2z/stock-watch-releases'):raise SystemExit('Unexpected staging directory')
    manifest=json.loads((source/'chart-fix.json').read_text())
    for name,digest in manifest['files'].items():
        path=source/name
        if not path.resolve().is_relative_to(source) or sha(path)!=digest:raise RuntimeError('Staged file verification failed: '+name)
    root=Path('/opt/stock-watch');receipt_path=root/'installed-release.json';receipt=json.loads(receipt_path.read_text())
    if receipt['revision']!=BASE or receipt.get('chart_pagination_patch'):raise RuntimeError('Unexpected installed revision; review before updating')
    module=Path(output(str(root/'.venv/bin/python'),'-c','import stock_watch_worker.systems.workspace as w;print(w.__file__)'))
    target=root/'worker/src/stock_watch_worker/systems/workspace.py'
    if not module.resolve().is_relative_to(root/'.venv') or sha(module)!=OLD_SHA or sha(target)!=OLD_SHA:raise RuntimeError('Installed worker differs from expected baseline')
    wheels=list((source/'release-wheels').glob('*.whl'))
    if len(wheels)!=1:raise RuntimeError('Expected one reviewed worker wheel')
    replacement=source/'worker/src/stock_watch_worker/systems/workspace.py'
    with ZipFile(wheels[0]) as wheel:
        if wheel.read('stock_watch_worker/systems/workspace.py')!=replacement.read_bytes():raise RuntimeError('Wheel/source mismatch')
        # Every other Python module must match the installed package exactly.
        package=module.parents[1]
        for name in wheel.namelist():
            if name.startswith('stock_watch_worker/') and name.endswith('.py') and name!='stock_watch_worker/systems/workspace.py':
                if wheel.read(name)!=(package/Path(name).relative_to('stock_watch_worker')).read_bytes():raise RuntimeError('Patch changes an unrelated Python module: '+name)
    if args.check:print('Chart-only patch preflight passed. No files, data, or services changed.');return
    if os.geteuid()!=0:raise SystemExit('Installation requires root')
    backup=Path('/var/backups/stock-watch-code-fixes')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True,mode=0o700)
    old_wheel=root/'release-wheels'/wheels[0].name
    shutil.copy2(old_wheel,backup/old_wheel.name);shutil.copy2(target,backup/'workspace.py');shutil.copy2(receipt_path,backup/'installed-release.json')
    timers=[line.split()[0] for line in output('systemctl','list-units','--type=timer','--state=active','--no-legend','--plain','stock-watch-*').splitlines()]
    services=[line.split()[0] for line in output('systemctl','list-units','--all','--type=service','--no-legend','--plain','stock-watch-*').splitlines() if line.split()[0]!='stock-watch-web.service']
    if timers:run('systemctl','stop',*timers)
    can_resume=True
    try:
        deadline=time.monotonic()+300
        while any(output('systemctl','show',unit,'-p','ActiveState','--value') in ('active','activating','deactivating') for unit in services):
            if time.monotonic()>deadline:raise RuntimeError('Workers did not drain; retry after its current job finishes')
            time.sleep(2)
        os.umask(0o022)
        try:
            can_resume=False
            run(str(root/'.venv/bin/pip'),'install','--no-index','--no-deps','--force-reinstall',str(wheels[0]))
            shutil.copy2(replacement,target);shutil.copy2(wheels[0],old_wheel)
            if sha(module)!=sha(replacement):raise RuntimeError('Installed worker hash mismatch')
            receipt['chart_pagination_patch']={'revision':manifest['revision'],'recovery':str(backup),'installed_at':datetime.now(timezone.utc).isoformat()}
            temporary=receipt_path.with_suffix('.tmp');temporary.write_text(json.dumps(receipt,indent=2)+'\n');temporary.chmod(0o644);temporary.replace(receipt_path)
            can_resume=True
        except Exception:
            run(str(root/'.venv/bin/pip'),'install','--no-index','--no-deps','--force-reinstall',str(backup/old_wheel.name))
            shutil.copy2(backup/'workspace.py',target);shutil.copy2(backup/old_wheel.name,old_wheel);shutil.copy2(backup/'installed-release.json',receipt_path)
            can_resume=True
            raise
    finally:
        if timers and can_resume:run('systemctl','start',*timers)
    print('Chart pagination fix installed. No database migration, history changes, or trading activation.')
    print('Code recovery:',backup)
    print('Cached partial charts refresh with the next five-minute chart window.')

if __name__=='__main__':main()
