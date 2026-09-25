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
command -v nft >/dev/null
if systemctl is-active --quiet stock-watch-web.service; then
  echo 'StockWatch is already active; review migration state first.' >&2; exit 1
fi

readonly BACKUP=/root/app-migration-access-before-20260925
[[ ! -e "$BACKUP" ]] || { echo 'Preparation already attempted; inspect before retry.' >&2; exit 1; }
install -d -m 700 "$BACKUP"
cp -a /etc/ufw "$BACKUP/ufw"
nft list ruleset > "$BACKUP/nft-ruleset.txt"
if nft list table inet app_migration >/dev/null 2>&1; then
  echo 'Existing app_migration table: inspect before replacing it.' >&2; exit 1
fi
[[ ! -e /etc/app-migration && ! -e /etc/systemd/system/app-migration-access.service ]] || {
  echo 'Existing access configuration: inspect before replacing it.' >&2; exit 1;
}

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

# A dedicated table changes only these four app ports. Do not enable UFW or
# flush the global ruleset: existing SSH, SMB, VPN, and other services retain
# their current behavior. The transaction replaces only our own table on restart.
install -d -m 700 /etc/app-migration
cat > /etc/app-migration/access.nft <<'RULES'
destroy table inet app_migration
table inet app_migration {
  chain app_input {
    type filter hook input priority -10; policy accept;
    iifname "lo" accept
    ip saddr 192.168.4.0/22 tcp dport { 3001, 3020, 5210, 9100 } accept
    tcp dport { 3001, 3020, 5210, 9100 } counter drop
  }
}
RULES
chmod 600 /etc/app-migration/access.nft
nft --check --file /etc/app-migration/access.nft
cat > /etc/systemd/system/app-migration-access.service <<'UNIT'
[Unit]
Description=Trusted LAN access for hosted applications
After=nftables.service ufw.service
Before=stock-watch-web.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft --file /etc/app-migration/access.nft
ExecReload=/usr/sbin/nft --file /etc/app-migration/access.nft
RemainAfterExit=yes
# Rules intentionally persist if the unit is stopped.

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now app-migration-access.service
nft list table inet app_migration
getfacl -p /var/backups/stock-watch
echo 'Access prerequisites prepared; no application services, schedules, or DNS changed.'
echo "Previous firewall configuration preserved at $BACKUP"
