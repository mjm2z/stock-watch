#!/usr/bin/env bash
set -euo pipefail
readonly SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly APP=/opt/stock-watch
if [[ ${EUID} -ne 0 ]]; then echo 'Run with sudo.' >&2; exit 1; fi
if [[ ${1:-} != --run ]]; then
  systemd-run --no-block --collect --unit=stock-watch-status-install \
    --property=Type=oneshot --property=TimeoutStartSec=5min \
    /bin/bash "${SOURCE}/deploy/install-status-root.sh" --run
  echo 'Dashboard update started independently of SSH.'
  echo 'Progress: journalctl -u stock-watch-status-install --no-pager -n 30'
  exit 0
fi
cmp --silent "${SOURCE}/package-lock.json" "${APP}/package-lock.json"
test -s "${SOURCE}/.next/BUILD_ID"
(cd "${SOURCE}" && sha256sum --check --quiet release.sha256)
readonly saved="/var/backups/home-ops-code/stock-watch-status-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "${saved}"
tar -cf "${saved}/source.tar" -C "${APP}" app components lib types
rsync -a --exclude=cache/ "${SOURCE}/.next/" "${saved}/new-next/"
chown -R root:root "${saved}/new-next"
modified=0
published=0
restore() {
  local result=$?
  if [[ ${result} -ne 0 && ${modified} -eq 1 ]]; then
    echo 'Dashboard validation failed; restoring the previous website.' >&2
    systemctl stop stock-watch-web.service || true
    tar -xf "${saved}/source.tar" -C "${APP}" || true
    if [[ ${published} -eq 1 ]]; then
      if [[ -d "${APP}/.next" ]]; then mv "${APP}/.next" "${saved}/failed-next"; fi
      mv "${saved}/previous-next" "${APP}/.next"
    fi
  fi
  systemctl start stock-watch-web.service || true
  exit "${result}"
}
trap restore EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
systemctl stop stock-watch-web.service
modified=1
for directory in app components lib types; do
  rsync -a "${SOURCE}/${directory}/" "${APP}/${directory}/"
  chown -R root:root "${APP}/${directory}"
done
mv "${APP}/.next" "${saved}/previous-next"
published=1
mv "${saved}/new-next" "${APP}/.next"
install -d -o stock-watch -g stock-watch -m 0755 "${APP}/.next/cache"
systemctl start stock-watch-web.service
for endpoint in api/health api/dashboard/execution api/dashboard/liquidity signals operations; do
  curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 \
    --max-time 20 "http://127.0.0.1:3001/${endpoint}" --output /dev/null
done
python3 - <<'PY'
import json, urllib.request
for endpoint in ('execution','liquidity'):
    with urllib.request.urlopen('http://127.0.0.1:3001/api/dashboard/'+endpoint, timeout=20) as response:
        data=json.load(response)
    if endpoint=='execution':
        print(json.dumps({'state':data['state'],'next_scan':data['nextScan'],'issues':data['issues']}))
    else:
        diagnostic=data['diagnostics']
        print(json.dumps({key:value for key,value in diagnostic.items() if key!='examples'}) if diagnostic else 'No scan diagnostics yet')
PY
echo "Dashboard installed and verified. Rollback files: ${saved}"
