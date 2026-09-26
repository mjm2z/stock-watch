#!/usr/bin/env bash
# Run AFTER the reviewed application update has installed this release.
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo 'Run this installer as root on the application host.' >&2
  exit 1
fi
runtime=/opt/stock-watch
state=/var/lib/stock-watch/stock-watch.db
[[ -f "$runtime/worker/migrations/016_systems.sql" ]]
[[ -x "$runtime/.venv/bin/stock-watch-systems" ]]
[[ -f "$state" ]]
# The CLI performs additive migration and seeds four immutable baseline templates.
runuser -u stock-watch -- "$runtime/.venv/bin/stock-watch-systems" --database "$state" init
for name in bitcoin-monitor bitcoin-trading systems-stock-shadow systems-stocks systems-research; do
  install -o root -g root -m 0644 "$runtime/deploy/systemd/stock-watch-$name.service" /etc/systemd/system/
  install -o root -g root -m 0644 "$runtime/deploy/systemd/stock-watch-$name.timer" /etc/systemd/system/
done
if [[ ! -f /etc/stock-watch/systems.env ]]; then
  install -o root -g root -m 0600 "$runtime/deploy/systems.env.example" /etc/stock-watch/systems.env
fi
install -d -m 0755 /etc/systemd/system/stock-watch-web.service.d
cat > /etc/systemd/system/stock-watch-web.service.d/systems.conf <<'CONFIG'
[Service]
EnvironmentFile=-/etc/stock-watch/systems.env
CONFIG
systemctl daemon-reload
# Research and watch-only collection are safe to start without a broker account.
# Bitcoin execution remains off until credentials and shadow review are ready.
systemctl enable --now stock-watch-bitcoin-monitor.timer stock-watch-systems-research.timer stock-watch-systems-stock-shadow.timer
systemctl restart stock-watch-web.service
printf '%s\n' 'Systems research and blockchain monitoring installed. Bitcoin/stock system trading timers remain unchanged; no strategy was activated.'
