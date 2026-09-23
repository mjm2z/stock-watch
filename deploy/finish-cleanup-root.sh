#!/usr/bin/env bash
set -euo pipefail
readonly SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly APP=/opt/stock-watch
if [[ ${EUID} -ne 0 ]]; then echo 'Run with sudo.' >&2; exit 1; fi
if [[ ${1:-} != --run ]]; then
  systemd-run --no-block --collect --unit=stock-watch-cleanup \
    --property=Type=oneshot --property=TimeoutStartSec=30min \
    /bin/bash "${SOURCE}/deploy/finish-cleanup-root.sh" --run
  echo 'Cleanup started independently of SSH.'
  echo 'Progress: journalctl -u stock-watch-cleanup --no-pager -n 30'
  exit 0
fi
cmp --silent "${SOURCE}/package-lock.json" "${APP}/package-lock.json"
# The earlier recovery only scans in development mode. Stop that oversized
# read before building; its EXIT handler restores normal timers.
systemctl stop stock-watch-repair.service stock-watch-paper-validation.service || true
timers=()
for unit in stock-watch-worker stock-watch-dispatch stock-watch-maintenance stock-watch-fundamentals stock-watch-universe; do
  if systemctl is-enabled --quiet "${unit}.timer"; then timers+=("${unit}.timer"); fi
  systemctl stop "${unit}.timer" "${unit}.service"
done
restore() {
  local result=$?
  systemctl start stock-watch-web.service || true
  if ((${#timers[@]})); then systemctl start "${timers[@]}" || true; fi
  if [[ ${result} -ne 0 ]]; then echo 'Cleanup failed; see journal for the exact stage.' >&2; fi
  exit "${result}"
}
trap restore EXIT
readonly saved="/var/backups/home-ops-code/stock-watch-cleanup-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "${saved}"
cp -a /etc/stock-watch/stock-watch.env "${saved}/stock-watch.env"
tar -cf "${saved}/source.tar" -C "${APP}" \
  'app/stock/[ticker]/page.tsx' app/api/analyze/route.ts worker/src/stock_watch_worker/scan_data.py
echo 'Building the AI-free interface in the staging directory; existing website stays up.'
runuser -u mjm2z -- env PATH=/usr/local/bin:/usr/bin:/bin \
  /usr/local/bin/npm --prefix "${SOURCE}" run build
echo 'Installing the memory-bounded scan loader.'
install -m 0644 "${SOURCE}/worker/src/stock_watch_worker/scan_data.py" "${APP}/worker/src/stock_watch_worker/scan_data.py"
"${APP}/.venv/bin/python" - "${SOURCE}" <<'PY'
import shutil, sys
from pathlib import Path
import stock_watch_worker.scan_data as module
shutil.copyfile(Path(sys.argv[1]) / 'worker/src/stock_watch_worker/scan_data.py', module.__file__)
PY
echo 'Publishing the rebuilt website.'
rsync -a --exclude=cache/ "${SOURCE}/.next/" "${saved}/new-next/"
chown -R root:root "${saved}/new-next"
systemctl stop stock-watch-web.service
install -m 0644 "${SOURCE}/app/stock/[ticker]/page.tsx" "${APP}/app/stock/[ticker]/page.tsx"
install -m 0644 "${SOURCE}/app/api/analyze/route.ts" "${APP}/app/api/analyze/route.ts"
install -m 0644 "${SOURCE}/lib/server-features.ts" "${APP}/lib/server-features.ts"
mv "${APP}/.next" "${saved}/previous-next"
mv "${saved}/new-next" "${APP}/.next"
install -d -o stock-watch -g stock-watch -m 0755 "${APP}/.next/cache"
systemctl start stock-watch-web.service
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 \
  --max-time 30 http://127.0.0.1:3001/api/stock/AAPL/quote --output /dev/null
status="$(curl --silent --show-error --max-time 15 -X POST -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/api/analyze)"
[[ ${status} == 404 ]]
echo 'AI controls disabled. Closing any interrupted development scan records.'
runuser -u stock-watch -- "${APP}/.venv/bin/python" - <<'PY'
from stock_watch_worker.database import connect
with connect('/var/lib/stock-watch/stock-watch.db') as db:
    db.execute("""UPDATE scan_runs SET status='failed', completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
        error='Recovery replaced with memory-bounded CompanyFacts loader'
        WHERE status='running' AND id LIKE 'scan-recovery-%'
          AND strategy_version_id='sp500-long-v0'""")
    db.execute("""UPDATE operation_runs SET status='failed', completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now'),
        error_message='Recovery replaced with memory-bounded CompanyFacts loader'
        WHERE status='running' AND command='repair-paper'""")
    db.execute("""INSERT INTO audit_events(event_type, entity_type, entity_id, payload_json)
        VALUES ('recovery_memory_fix_installed', 'service', 'stock-watch-worker',
        '{"reason":"Bounded CompanyFacts loading; prior development recovery interrupted if running"}')""")
PY
echo 'Validating a fresh research scan with bounded memory before paper activation.'
systemd-run --unit=stock-watch-paper-validation --collect --wait --pipe \
  --property=User=stock-watch --property=Group=stock-watch \
  --property=EnvironmentFile=/etc/stock-watch/stock-watch.env \
  --property=WorkingDirectory="${APP}" \
  "${APP}/.venv/bin/python" "${APP}/deploy/validate-paper-recovery.py"
python3 - <<'PY'
from pathlib import Path
import os, tempfile
path = Path('/etc/stock-watch/stock-watch.env')
lines = [line for line in path.read_text().splitlines() if not line.strip().startswith('STOCK_WATCH_STRATEGY_ID=')]
lines.append('STOCK_WATCH_STRATEGY_ID=sp500-long-paper-v1')
with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.stock-watch-env-', delete=False) as stream:
    stream.write('\n'.join(lines) + '\n'); stream.flush(); os.fsync(stream.fileno())
    temporary = Path(stream.name)
try: temporary.replace(path)
finally: temporary.unlink(missing_ok=True)
PY
systemctl restart stock-watch-web.service
systemctl enable --now stock-watch-worker.timer stock-watch-dispatch.timer stock-watch-maintenance.timer
echo 'Cleanup complete: AI hidden, research scan validated, paper strategy selected.'
