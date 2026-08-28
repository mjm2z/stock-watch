#!/usr/bin/env bash
set -u

readonly HEALTH_URL="http://127.0.0.1:3001/api/health"
readonly DASHBOARD_PORT="3001"
readonly SERVICES=(
  stock-watch-web.service
  stock-watch-universe.service
  stock-watch-assets.service
  stock-watch-fundamentals.service
  stock-watch-dispatch.service
  stock-watch-worker.service
  stock-watch-maintenance.service
  stock-watch-backup.service
)

echo "Stock Watch health"
if ! curl --fail --silent --show-error "${HEALTH_URL}"; then
  echo "health endpoint failed" >&2
fi
echo

echo "Dashboard addresses (trusted LAN only; no application login)"
for address in $(hostname -I 2>/dev/null); do
  if [[ "${address}" != *:* && "${address}" != 127.* ]]; then
    echo "http://${address}:${DASHBOARD_PORT}"
  fi
done
echo

echo "Service state"
for service in "${SERVICES[@]}"; do
  systemctl show "${service}" \
    --property=Id \
    --property=ActiveState \
    --property=SubState \
    --property=Result \
    --property=ExecMainStatus \
    --property=MemoryPeak \
    --property=CPUUsageNSec \
    --no-pager | tr '\n' ' '
  echo
done

echo "Scheduled timers"
systemctl list-timers 'stock-watch-*' --all --no-pager

echo "Recent warnings and errors"
journalctl \
  -u 'stock-watch-*' \
  --priority=warning \
  --since '24 hours ago' \
  --no-pager \
  --output=short-iso
