#!/usr/bin/env bash
set -euo pipefail

readonly RELEASE_SOURCE="${1:-/home/mjm2z/stock-watch-staging}"
readonly TIMER_UNITS=(
  stock-watch-exits.timer
  stock-watch-worker.timer
  stock-watch-dispatch.timer
  stock-watch-maintenance.timer
  stock-watch-fundamentals.timer
  stock-watch-universe.timer
  stock-watch-backup.timer
  stock-watch-bitcoin-monitor.timer
  stock-watch-bitcoin-trading.timer
  stock-watch-systems-stock-shadow.timer
  stock-watch-systems-stocks.timer
  stock-watch-systems-research.timer
)
readonly SERVICE_UNITS=(
  stock-watch-exits.service
  stock-watch-worker.service
  stock-watch-dispatch.service
  stock-watch-maintenance.service
  stock-watch-fundamentals.service
  stock-watch-universe.service
  stock-watch-assets.service
  stock-watch-backup.service
  stock-watch-bitcoin-monitor.service
  stock-watch-bitcoin-trading.service
  stock-watch-systems-stock-shadow.service
  stock-watch-systems-stocks.service
  stock-watch-systems-research.service
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this update as root." >&2
  exit 1
fi
if [[ ! -x "${RELEASE_SOURCE}/deploy/bootstrap-a1347-j.sh" ]]; then
  echo "Staged release is missing its bootstrap: ${RELEASE_SOURCE}" >&2
  exit 1
fi

enabled_timers=()
for timer in "${TIMER_UNITS[@]}"; do
  if systemctl is-enabled --quiet "${timer}"; then
    enabled_timers+=("${timer}")
  fi
done

for unit in "${TIMER_UNITS[@]}" "${SERVICE_UNITS[@]}" stock-watch-web.service; do
  if [[ "$(systemctl show --property=LoadState --value "$unit")" != "not-found" ]]; then
    systemctl stop "$unit"
  fi
done

bash "${RELEASE_SOURCE}/deploy/bootstrap-a1347-j.sh" "${RELEASE_SOURCE}"

if ((${#enabled_timers[@]})); then
  systemctl enable --now "${enabled_timers[@]}"
fi

curl --fail --silent --show-error --retry 10 --retry-delay 1 \
  --retry-connrefused http://127.0.0.1:3001/api/health
echo
echo "Update complete; restored ${#enabled_timers[@]} previously enabled timers."
