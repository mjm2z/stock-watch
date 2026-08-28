#!/usr/bin/env bash
set -euo pipefail

readonly UNIVERSE_CSV="${1:-}"
readonly UNIVERSE_SOURCE="${2:-}"
readonly UNIVERSE_SOURCE_URL="${3:-}"
readonly INSTALL_ROOT="/opt/stock-watch"
readonly STATE_ROOT="/var/lib/stock-watch"
readonly ENVIRONMENT_FILE="/etc/stock-watch/stock-watch.env"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run automation activation as root." >&2
  exit 1
fi
if [[ -z "${UNIVERSE_CSV}" || -z "${UNIVERSE_SOURCE}" || -z "${UNIVERSE_SOURCE_URL}" ]]; then
  echo "Usage: $0 /path/to/sp500.csv 'approved source' https://direct.csv/url" >&2
  exit 1
fi
if [[ ! "${UNIVERSE_SOURCE_URL}" =~ ^https:// ]]; then
  echo "Universe synchronization URL must use HTTPS." >&2
  exit 1
fi
if [[ ! -f "${UNIVERSE_CSV}" ]]; then
  echo "Universe CSV does not exist: ${UNIVERSE_CSV}" >&2
  exit 1
fi
if [[ ! -x "${INSTALL_ROOT}/.venv/bin/stock-watch-worker" ]]; then
  echo "Run bootstrap-a1347-j.sh before activation." >&2
  exit 1
fi
if [[ ! -f "${ENVIRONMENT_FILE}" ]]; then
  echo "Missing root-only environment file: ${ENVIRONMENT_FILE}" >&2
  exit 1
fi
if ! grep -Eq '^ALPACA_API_KEY_ID=.+$' "${ENVIRONMENT_FILE}" || \
   grep -Eq '^ALPACA_API_KEY_ID=replace_' "${ENVIRONMENT_FILE}"; then
  echo "Configure the Alpaca paper key ID before activation." >&2
  exit 1
fi
if ! grep -Eq '^ALPACA_API_SECRET_KEY=.+$' "${ENVIRONMENT_FILE}" || \
   grep -Eq '^ALPACA_API_SECRET_KEY=replace_' "${ENVIRONMENT_FILE}"; then
  echo "Configure the Alpaca paper secret before activation." >&2
  exit 1
fi
if ! grep -Eq '^SEC_USER_AGENT=.+@.+$' "${ENVIRONMENT_FILE}" || \
   grep -Fxq 'SEC_USER_AGENT=Stock Watch monitored-email@example.com' \
     "${ENVIRONMENT_FILE}"; then
  echo "Configure SEC_USER_AGENT with the monitored contact email." >&2
  exit 1
fi

strategy_id="$(sed -n 's/^STOCK_WATCH_STRATEGY_ID=//p' "${ENVIRONMENT_FILE}" | tail -1)"
if [[ -z "${strategy_id}" ]]; then
  echo "Configure STOCK_WATCH_STRATEGY_ID before activation." >&2
  exit 1
fi

effective_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
install -d -o stock-watch -g stock-watch -m 0700 "${STATE_ROOT}/imports"
stored_csv="${STATE_ROOT}/imports/sp500-${effective_at//:/}.csv"
install -o stock-watch -g stock-watch -m 0600 "${UNIVERSE_CSV}" "${stored_csv}"

import_arguments=(
  "${INSTALL_ROOT}/.venv/bin/stock-watch-worker" import-universe
  --database "${STATE_ROOT}/stock-watch.db"
  --csv "${stored_csv}"
  --effective-at "${effective_at}"
  --source "${UNIVERSE_SOURCE}"
  --minimum-members 450
  --maximum-members 550
  --minimum-cik-coverage 0.95
)
import_arguments+=(--source-url "${UNIVERSE_SOURCE_URL}")
runuser -u stock-watch -- "${import_arguments[@]}"
runuser -u stock-watch -- \
  "${INSTALL_ROOT}/.venv/bin/stock-watch-worker" sync-universe \
  --database "${STATE_ROOT}/stock-watch.db" \
  --now "${effective_at}"

systemctl start stock-watch-assets.service
runuser -u stock-watch -- \
  "${INSTALL_ROOT}/.venv/bin/stock-watch-worker" deployment-check \
  --database "${STATE_ROOT}/stock-watch.db" \
  --strategy-id "${strategy_id}"
systemctl start stock-watch-fundamentals.service

systemctl enable --now \
  stock-watch-worker.timer \
  stock-watch-dispatch.timer \
  stock-watch-maintenance.timer \
  stock-watch-fundamentals.timer \
  stock-watch-universe.timer \
  stock-watch-backup.timer

systemctl list-timers 'stock-watch-*' --no-pager
echo "Automation enabled for immutable strategy ${strategy_id}."
echo "Paper orders remain impossible unless that registered version has status=paper."
