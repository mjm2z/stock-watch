#!/usr/bin/env bash
# Target access/backup prerequisites only. Never starts application services.
set -euo pipefail
[[ ${EUID} -eq 0 && $(hostname -s) == a1347-m ]] || {
  echo 'Run as root on a1347-m only.' >&2; exit 1;
}

# Refuse to alter a host whose database/network no longer match the migration.
ip -4 -o address show | grep -q '192\.168\.4\.35/' || {
  echo 'Expected LAN address is absent.' >&2; exit 1;
}
[[ $(runuser -u postgres -- psql -XAt -c 'SHOW listen_addresses') == localhost ]] || {
  echo 'PostgreSQL must remain loopback-only.' >&2; exit 1;
}
ufw status | grep -qx 'Status: active' || {
  echo 'Review inactive firewall before making application rules.' >&2; exit 1;
}
if systemctl is-active --quiet stock-watch-web.service; then
  echo 'StockWatch is already active; review migration state first.' >&2; exit 1
fi

readonly BACKUP=/root/app-migration-access-before-20260925
[[ ! -e "$BACKUP" ]] || { echo 'Preparation already attempted; inspect before retry.' >&2; exit 1; }
install -d -m 700 "$BACKUP"
cp -a /etc/ufw "$BACKUP/ufw"
ufw status numbered > "$BACKUP/ufw-status.txt"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y acl
getent passwd stock-watch >/dev/null
if [[ -e /var/backups/stock-watch ]]; then
  [[ -d /var/backups/stock-watch && ! -L /var/backups/stock-watch ]] || exit 1
  getfacl -p /var/backups/stock-watch > "$BACKUP/stock-watch-backup.acl"
else
  install -d -o stock-watch -g stock-watch -m 700 /var/backups/stock-watch
fi
# The backup worker grants file-read ACLs only to finalized, verified snapshots.
# This grants directory listing/traversal, never access to the live database.
setfacl -m u:mjm2z:r-x /var/backups/stock-watch

# Put scoped rules before any existing broad LAN/application allowances.
# Leave all unrelated ports, VPN services, and existing rules intact.
for port in 3001 3020 5210 9100; do
  ufw insert 1 deny proto tcp from any to any port "$port" comment 'app migration perimeter'
  ufw insert 1 allow proto tcp from 192.168.4.0/22 to any port "$port" comment 'trusted LAN applications'
  ufw insert 1 allow in on lo proto tcp to any port "$port" comment 'loopback applications'
done
ufw status numbered
getfacl -p /var/backups/stock-watch
echo 'Access prerequisites prepared; no application services, schedules, or DNS changed.'
echo "Previous firewall configuration preserved at $BACKUP"
