#!/usr/bin/env python3
"""Hash-guarded backup-only repair; run as root on the existing installed release."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
from datetime import datetime, timezone

BASELINE = '61809f87a8340d114df02cf62d140b40194baad3d4081be5aa8012bb56771a83'
REVISION = 'cd89d63efaa65ed4359f89ff7dd1b81d6e96930f'
ROOT = Path('/opt/stock-watch')


def main():
    if os.geteuid() != 0:
        raise SystemExit('Root required to update the protected StockWatch installation')
    if (ROOT/'source-revision.txt').read_text().strip() != REVISION:
        raise SystemExit('Installed application revision changed; review the repair again')
    active=subprocess.check_output(['systemctl','show','stock-watch-backup.service','-p','ActiveState','--value'],text=True).strip()
    if active in ('active','activating','deactivating'):
        raise SystemExit('An active backup must finish before this repair')
    package=ROOT/'.venv/lib/python3.12/site-packages/stock_watch_worker/backup.py'
    source=ROOT/'worker/src/stock_watch_worker/backup.py'
    staged=Path(__file__).resolve().with_name('backup.py')
    expected=Path(__file__).resolve().with_name('backup.sha256').read_text().strip()
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(staged)!=expected or any(digest(p)!=BASELINE for p in (source,package)):
        raise SystemExit('Module hash mismatch; refusing to overwrite unknown changes')
    compile(staged.read_text(),str(staged),'exec')
    archive=Path('/var/backups/stock-watch-module-repair')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive.mkdir(parents=True,mode=0o700)
    for name,path in (('source.py',source),('installed.py',package)):
        shutil.copy2(path,archive/name)
        temporary=path.with_suffix('.repair-tmp')
        shutil.copy2(staged,temporary);os.chmod(temporary,path.stat().st_mode & 0o777);os.chown(temporary,path.stat().st_uid,path.stat().st_gid)
        temporary.replace(path)
    (archive/'receipt.txt').write_text('previous='+BASELINE+'\ninstalled='+expected+'\n')
    print('Backup-only module updated; rollback:',archive)
    print('Run systemctl start --no-block stock-watch-backup.service after other disk-heavy backups complete.')

if __name__=='__main__':main()
