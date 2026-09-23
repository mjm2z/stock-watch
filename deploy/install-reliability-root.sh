#!/usr/bin/env bash
set -euo pipefail
readonly SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly APP=/opt/stock-watch
if [[ ${EUID} -ne 0 ]]; then echo 'Run with sudo.' >&2; exit 1; fi
if [[ ${1:-} != --run ]]; then
  systemd-run --no-block --collect --unit=stock-watch-reliability-install \
    --property=Type=oneshot --property=TimeoutStartSec=15min \
    /bin/bash "${SOURCE}/deploy/install-reliability-root.sh" --run
  echo 'Installation started independently of SSH.'
  echo 'Progress: journalctl -u stock-watch-reliability-install --no-pager -n 40'
  exit 0
fi
test -s "${SOURCE}/.next/BUILD_ID"
(cd "${SOURCE}" && sha256sum --check --quiet release.sha256)
cmp --silent "${SOURCE}/package-lock.json" "${APP}/package-lock.json"
# Refuse a different selected strategy without exposing the environment file.
"${APP}/.venv/bin/python" - <<'PYCODE'
from pathlib import Path
values=[line.split('=',1)[1].strip().strip('"').strip("'")
        for line in Path('/etc/stock-watch/stock-watch.env').read_text().splitlines()
        if line.startswith('STOCK_WATCH_STRATEGY_ID=')]
if values != ['sp500-long-paper-v2']:
    raise SystemExit('Expected selected paper-v2; review this release for the current strategy.')
PYCODE
policy_present="$(runuser -u stock-watch -- "${APP}/.venv/bin/python" - <<'PYCODE'
from stock_watch_worker.database import connect
with connect('/var/lib/stock-watch/stock-watch.db') as db:
    table=db.execute("SELECT 1 FROM sqlite_master WHERE name='paper_exit_timing_policies'").fetchone()
    print(int(bool(table and db.execute("SELECT 1 FROM paper_exit_timing_policies WHERE strategy_version_id='sp500-long-paper-v2'").fetchone())))
PYCODE
)"
if [[ ${policy_present} == 1 ]]; then echo 'Policy already installed; verify live service and scan status.'; exit 0; fi
readonly saved="/var/backups/home-ops-code/stock-watch-reliability-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "${saved}"
readonly installed_package="$("${APP}/.venv/bin/python" -c 'import pathlib,stock_watch_worker; print(pathlib.Path(stock_watch_worker.__file__).parent)')"
tar -cf "${saved}/source.tar" -C "${APP}" app components lib types worker/src worker/migrations deploy
cp -a "${installed_package}" "${saved}/installed-worker"
rsync -a --exclude=cache/ "${SOURCE}/.next/" "${saved}/new-next/"
chown -R root:root "${saved}/new-next"
timers=()
modified=0
published=0
policy_added=0
restore() {
  local result=$?
  trap - EXIT
  if [[ ${result} -ne 0 && ${modified} -eq 1 ]]; then
    systemctl stop stock-watch-exits.timer || true
    # Let an exit request finish before rolling back executable code.
    for attempt in {1..60}; do
      exit_state="$(systemctl show stock-watch-exits.service -p ActiveState --value)"
      if [[ ${exit_state} != active && ${exit_state} != activating ]]; then break; fi
      sleep 2
    done
    if [[ ${exit_state:-inactive} == active || ${exit_state:-inactive} == activating ]]; then
      echo "Rollback paused: exit service still active. Timers remain stopped; inspect ${saved}." >&2
      exit 1
    fi
    if [[ ${policy_added} -eq 1 ]]; then
      runuser -u stock-watch -- "${APP}/.venv/bin/python" - <<'PY'
from stock_watch_worker.database import connect
with connect('/var/lib/stock-watch/stock-watch.db') as db:
    db.execute("DELETE FROM paper_exit_timing_policies WHERE strategy_version_id='sp500-long-paper-v2'")
    db.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,payload_json) VALUES ('paper_exit_policy_rollback','strategy_version','sp500-long-paper-v2','{}')")
PY
    fi
    systemctl stop stock-watch-web.service || true
    tar -xf "${saved}/source.tar" -C "${APP}"
    rsync -a --delete "${saved}/installed-worker/" "${installed_package}/"
    if [[ ${published} -eq 1 ]]; then
      if [[ -d ${APP}/.next ]]; then mv "${APP}/.next" "${saved}/failed-next"; fi
      mv "${saved}/previous-next" "${APP}/.next"
    fi
    systemctl disable stock-watch-exits.timer || true
    systemctl start stock-watch-web.service || true
    echo "Release failed; previous code restored. Additive schema and audit records retained at ${saved}." >&2
  fi
  for timer in "${timers[@]}"; do systemctl start "${timer}" || true; done
  exit "${result}"
}
trap restore EXIT
for name in worker dispatch maintenance fundamentals universe backup; do
  unit="stock-watch-${name}.timer"
  if systemctl is-active --quiet "${unit}"; then timers+=("${unit}"); fi
  systemctl stop "${unit}"
done
# Never interrupt a scan, network order, SEC writer, or database backup.
for name in worker dispatch maintenance fundamentals universe backup; do
  for attempt in {1..240}; do
    state="$(systemctl show "stock-watch-${name}.service" -p ActiveState --value)"
    if [[ ${state} != active && ${state} != activating ]]; then break; fi
    sleep 2
  done
  if [[ ${state} == active || ${state} == activating ]]; then echo "Service still busy: ${name}" >&2; exit 1; fi
done
systemctl stop stock-watch-web.service
modified=1
for directory in app components lib types deploy; do rsync -a "${SOURCE}/${directory}/" "${APP}/${directory}/"; done
rsync -a --exclude=__pycache__/ "${SOURCE}/worker/src/" "${APP}/worker/src/"
rsync -a "${SOURCE}/worker/migrations/" "${APP}/worker/migrations/"
rsync -a --exclude=__pycache__/ "${SOURCE}/worker/src/stock_watch_worker/" "${installed_package}/"
install -d "${APP}/.venv/share/stock-watch-worker/migrations"
rsync -a "${SOURCE}/worker/migrations/" "${APP}/.venv/share/stock-watch-worker/migrations/"
chown -R root:root "${APP}/app" "${APP}/components" "${APP}/lib" "${APP}/types" "${APP}/deploy" "${APP}/worker/src" "${APP}/worker/migrations" "${installed_package}"
runuser -u stock-watch -- "${APP}/.venv/bin/python" - <<'PY'
from stock_watch_worker.database import connect,apply_migrations
with connect('/var/lib/stock-watch/stock-watch.db') as db:
    print('Migrations:',apply_migrations(db))
    if db.execute("SELECT 1 FROM paper_exit_timing_policies WHERE strategy_version_id='sp500-long-paper-v2'").fetchone():
        raise SystemExit('Exit policy is already installed; do not rerun this first-install wrapper.')
    print('Original articles:',db.execute('SELECT COUNT(*) FROM news_articles').fetchone()[0])
    print('Retained revisions:',db.execute('SELECT COUNT(*) FROM news_revisions').fetchone()[0])
PY
install -m 0644 "${SOURCE}/deploy/systemd/stock-watch-exits."{timer,service} /etc/systemd/system/
systemctl daemon-reload
mv "${APP}/.next" "${saved}/previous-next"
published=1
mv "${saved}/new-next" "${APP}/.next"
# The hardened web unit requires this mount target to exist before startup.
# Build caches are intentionally not copied from staging.
install -d -o stock-watch -g stock-watch -m 0750 "${APP}/.next/cache"
systemctl start stock-watch-web.service
curl --fail --silent --show-error --retry 30 --retry-delay 1 --retry-connrefused http://127.0.0.1:3001/api/health
curl --fail --silent --show-error http://127.0.0.1:3001/portfolio >/dev/null
runuser -u stock-watch -- "${APP}/.venv/bin/python" - <<'PY'
from stock_watch_worker.database import connect
from stock_watch_worker.exit_runtime import activate_exit_policy
with connect('/var/lib/stock-watch/stock-watch.db') as db:
    activate_exit_policy(db,'sp500-long-paper-v2')
    print('Activated near-close-v1 for paper-v2; no orders submitted by installer.')
PY
policy_added=1
runuser -u stock-watch -- "${APP}/.venv/bin/python" "${APP}/deploy/verify-reliability-release.py" \
  --database /var/lib/stock-watch/stock-watch.db
systemctl enable --now stock-watch-exits.timer
echo "Installed. Rollback source/build: ${saved}. Verify the next scan and exit tick."
