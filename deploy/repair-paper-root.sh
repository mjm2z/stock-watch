#!/usr/bin/env bash
set -euo pipefail

readonly SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly UNIT=stock-watch-repair
if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi
if [[ ${1:-} != --run ]]; then
  systemd-run --no-block --unit="${UNIT}" --collect --property=Type=oneshot \
    --property=TimeoutStartSec=45min \
    /bin/bash "${SOURCE}/deploy/repair-paper-root.sh" --run
  echo "Repair started in the background; you can close this SSH session."
  echo "Progress: journalctl -u stock-watch-repair --no-pager -n 30"
  echo "Dashboard: http://192.168.4.45:3001/operations"
  exit 0
fi

case "$(systemctl show stock-watch-backup.service --property=ActiveState --value)" in
  active|activating) echo "Backup is running; retry this repair after it finishes." >&2; exit 1 ;;
esac

readonly TIMERS=(stock-watch-worker.timer stock-watch-dispatch.timer stock-watch-maintenance.timer stock-watch-fundamentals.timer stock-watch-universe.timer stock-watch-backup.timer)
enabled=()
backup_acl=''
for timer in "${TIMERS[@]}"; do
  if systemctl is-enabled --quiet "${timer}"; then enabled+=("${timer}"); fi
done
restore_timers() {
  local result=$?
  if [[ -n ${backup_acl} && -f ${backup_acl} ]]; then setfacl --restore="${backup_acl}" || true; fi
  systemctl start stock-watch-web.service || true
  if ((${#enabled[@]})); then systemctl start "${enabled[@]}" || true; fi
  if [[ ${result} -ne 0 ]]; then
    echo "Repair failed. Review this journal and Operations; automatic paper activation was not completed." >&2
  fi
  exit "${result}"
}
trap restore_timers EXIT
systemctl stop "${TIMERS[@]}"
systemctl stop stock-watch-worker.service stock-watch-dispatch.service \
  stock-watch-maintenance.service stock-watch-fundamentals.service stock-watch-universe.service

readonly rollback="/var/backups/home-ops-code/stock-watch-repair-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "${rollback}"
backup_acl="${rollback}/backup-directory.acl"
getfacl -p /var/backups/stock-watch > "${backup_acl}"
cp -a /etc/stock-watch/stock-watch.env "${rollback}/stock-watch.env"
tar --exclude=node_modules --exclude=.venv --exclude=.next --exclude=.git \
  -czf "${rollback}/source.tar.gz" -C /opt/stock-watch .
echo "Installing repaired application; rollback source saved in ${rollback}"
# Timers stay stopped until validation ends. Bootstrap updates code, builds,
# migrates additively, and starts only the website.
systemctl stop stock-watch-web.service
bash "${SOURCE}/deploy/bootstrap-a1347-j.sh" "${SOURCE}"
setfacl --restore="${backup_acl}"
echo "Checking stock quotes and chart data through the deployed website"
curl --fail --silent --show-error --max-time 30 \
  http://127.0.0.1:3001/api/stock/AAPL/quote --output /dev/null
curl --fail --silent --show-error --max-time 60 \
  'http://127.0.0.1:3001/api/stock/AAPL/history?range=1D' --output /dev/null
echo "Refreshing company fundamentals; progress appears in Operations"
systemctl start stock-watch-fundamentals.service
echo "Validating a fresh research scan and the paper account"
systemd-run --unit=stock-watch-paper-validation --collect --wait --pipe \
  --property=User=stock-watch --property=Group=stock-watch \
  --property=EnvironmentFile=/etc/stock-watch/stock-watch.env \
  --property=WorkingDirectory=/opt/stock-watch \
  /opt/stock-watch/.venv/bin/python /opt/stock-watch/deploy/validate-paper-recovery.py

python3 - <<'PY'
from pathlib import Path
import os
import tempfile
path = Path('/etc/stock-watch/stock-watch.env')
lines = path.read_text().splitlines()
lines = [line for line in lines if not line.strip().startswith('STOCK_WATCH_STRATEGY_ID=')]
lines.append('STOCK_WATCH_STRATEGY_ID=sp500-long-paper-v1')
with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.stock-watch-env-', delete=False) as stream:
    stream.write('\n'.join(lines) + '\n')
    stream.flush()
    os.fsync(stream.fileno())
    temporary = Path(stream.name)
try:
    temporary.replace(path)
finally:
    temporary.unlink(missing_ok=True)
PY
systemctl restart stock-watch-web.service
systemctl enable stock-watch-worker.timer stock-watch-dispatch.timer stock-watch-maintenance.timer
systemctl start stock-watch-worker.timer stock-watch-dispatch.timer stock-watch-maintenance.timer
echo "Repair complete: quotes available, research scan passed, paper-only automation enabled."
echo "Scheduled scans: 9:45 AM and 4:15 PM Eastern on trading days."
