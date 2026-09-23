#!/usr/bin/env bash
set -euo pipefail
readonly SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly APP=/opt/stock-watch
if [[ ${EUID} -ne 0 ]]; then echo 'Run with sudo.' >&2; exit 1; fi
if [[ ${1:-} != --run ]]; then
  systemd-run --no-block --collect --unit=stock-watch-evaluation-install \
    --property=Type=oneshot --property=TimeoutStartSec=10min \
    /bin/bash "${SOURCE}/deploy/install-evaluation-root.sh" --run
  echo 'Installation started independently of SSH.'
  echo 'Progress: journalctl -u stock-watch-evaluation-install --no-pager -n 30'
  exit 0
fi
cmp --silent "${SOURCE}/package-lock.json" "${APP}/package-lock.json"
test -s "${SOURCE}/.next/BUILD_ID"
test -s "${SOURCE}/release.sha256"
(cd "${SOURCE}" && sha256sum --check --quiet release.sha256)
readonly saved="/var/backups/home-ops-code/stock-watch-evaluation-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "${saved}"
readonly installed_package="$("${APP}/.venv/bin/python" -c 'import pathlib, stock_watch_worker; print(pathlib.Path(stock_watch_worker.__file__).parent)')"
tar -cf "${saved}/source.tar" -C "${APP}" app components lib types worker/src worker/migrations
cp -a "${installed_package}" "${saved}/installed-worker"
rsync -a --exclude=cache/ "${SOURCE}/.next/" "${saved}/new-next/"
chown -R root:root "${saved}/new-next"
timers=()
modified=0
published=0
restore() {
  local result=$?
  if [[ ${result} -ne 0 && ${modified} -eq 1 ]]; then
    echo 'Install failed. Restoring previous application code; additive database migrations are retained.' >&2
    systemctl stop stock-watch-web.service || true
    tar -xf "${saved}/source.tar" -C "${APP}" || true
    rsync -a "${saved}/installed-worker/" "${installed_package}/" || true
    if [[ ${published} -eq 1 ]]; then
      if [[ -d "${APP}/.next" ]]; then mv "${APP}/.next" "${saved}/failed-next"; fi
      mv "${saved}/previous-next" "${APP}/.next"
    fi
  fi
  systemctl start stock-watch-web.service || true
  if ((${#timers[@]})); then systemctl start "${timers[@]}" || true; fi
  exit "${result}"
}
trap restore EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
for unit in stock-watch-worker stock-watch-dispatch stock-watch-maintenance stock-watch-fundamentals stock-watch-universe; do
  if systemctl is-active --quiet "${unit}.timer"; then timers+=("${unit}.timer"); fi
  systemctl stop "${unit}.timer"
done
echo 'Waiting for current jobs to finish without interrupting orders.'
for unit in stock-watch-worker stock-watch-dispatch stock-watch-maintenance stock-watch-fundamentals stock-watch-universe; do
  for attempt in {1..120}; do
    state="$(systemctl show "${unit}.service" -p ActiveState --value)"
    [[ ${state} != active && ${state} != activating && ${state} != deactivating ]] && break
    if [[ ${attempt} == 120 ]]; then echo "${unit} is still busy; retry installation after it finishes." >&2; exit 1; fi
    sleep 2
  done
done
systemctl stop stock-watch-web.service
modified=1
for directory in app components lib types; do rsync -a "${SOURCE}/${directory}/" "${APP}/${directory}/"; done
rsync -a --exclude=__pycache__/ "${SOURCE}/worker/src/" "${APP}/worker/src/"
rsync -a "${SOURCE}/worker/migrations/" "${APP}/worker/migrations/"
rsync -a --exclude=__pycache__/ "${SOURCE}/worker/src/stock_watch_worker/" "${installed_package}/"
install -d "${APP}/.venv/share/stock-watch-worker/migrations"
rsync -a "${SOURCE}/worker/migrations/" "${APP}/.venv/share/stock-watch-worker/migrations/"
chown -R root:root "${APP}/app" "${APP}/components" "${APP}/lib" "${APP}/types" "${APP}/worker/src" "${APP}/worker/migrations" "${installed_package}"
echo 'Applying additive evaluation and research migrations.'
runuser -u stock-watch -- "${APP}/.venv/bin/python" - <<'PY'
from stock_watch_worker.database import connect, apply_migrations
with connect('/var/lib/stock-watch/stock-watch.db') as db:
    print('Applied:', apply_migrations(db))
    db.execute("INSERT INTO audit_events(event_type,entity_type,entity_id,payload_json) VALUES ('evaluation_release_installed','service','stock-watch-worker','{\"evaluation_version\":\"mature-validation-labels-v2\",\"outcomes\":\"completed-sessions-v2\"}')")
PY
mv "${APP}/.next" "${saved}/previous-next"
# Track this before the second move so rollback also handles its failure.
published=1
mv "${saved}/new-next" "${APP}/.next"
install -d -o stock-watch -g stock-watch -m 0755 "${APP}/.next/cache"
systemctl start stock-watch-web.service
for endpoint in api/health api/dashboard/signals api/research signals research; do
  curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 \
    --max-time 20 "http://127.0.0.1:3001/${endpoint}" --output /dev/null
done
echo "Installed and verified. Rollback files: ${saved}"
echo 'Shared research, decision history, and corrected evaluations are live. Existing paper strategy thresholds and order limits are unchanged.'
