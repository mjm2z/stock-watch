#!/usr/bin/env bash
# Infrastructure preparation only: does not migrate data or start app services.
set -euo pipefail
[[ ${EUID} -eq 0 && $(hostname -s) == a1347-m ]] || {
  echo 'Run as root on a1347-m only.' >&2; exit 1;
}
readonly NODE_VERSION=24.16.0
readonly NODE_ARCHIVE="node-v${NODE_VERSION}-linux-x64.tar.xz"
readonly NODE_SHA256=d804845d34eddc21dc1092b519d643ef40b1f58ec5dec5c22b1f4bd8fabde6c9
readonly NODE_ROOT="/opt/node-v${NODE_VERSION}-linux-x64"

# Fail before changing anything if this is no longer the inventoried fresh host.
if [[ -d /etc/postgresql ]] && find /etc/postgresql -name postgresql.conf -print -quit | grep -q .; then
  echo 'Existing PostgreSQL cluster: review it before rerunning preparation.' >&2
  exit 1
fi
for target in /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx; do
  if [[ -e "$target" || -L "$target" ]]; then
    echo "Existing runtime link needs review: $target" >&2; exit 1
  fi
done
[[ ! -e "$NODE_ROOT" ]] || { echo 'Existing Node installation needs review.' >&2; exit 1; }

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl xz-utils python3.12-venv postgresql-16 postgresql-client-16

readonly DOWNLOAD_DIR=$(mktemp -d /tmp/app-host-node.XXXXXX)
curl --fail --location --silent --show-error \
  "https://nodejs.org/dist/v${NODE_VERSION}/${NODE_ARCHIVE}" \
  --output "${DOWNLOAD_DIR}/${NODE_ARCHIVE}"
echo "${NODE_SHA256}  ${DOWNLOAD_DIR}/${NODE_ARCHIVE}" | sha256sum --check --status
tar -xJf "${DOWNLOAD_DIR}/${NODE_ARCHIVE}" -C /opt
ln -s "$NODE_ROOT/bin/node" /usr/local/bin/node
ln -s "$NODE_ROOT/bin/npm" /usr/local/bin/npm
ln -s "$NODE_ROOT/bin/npx" /usr/local/bin/npx

# Ubuntu's fresh cluster defaults to localhost. Check, rather than silently
# rewriting shared cluster settings or opening any firewall ports.
readonly PG_LISTEN=$(runuser -u postgres -- psql -XAt -c 'SHOW listen_addresses')
[[ "$PG_LISTEN" == localhost ]] || {
  echo 'Unexpected PostgreSQL listener: stop and inspect configuration.' >&2; exit 1;
}
runuser -u postgres -- pg_isready
/usr/local/bin/node --version
echo 'Runtime preparation complete. No application data, roles, schedules, DNS,'
echo 'firewall rules, or existing application services were changed.'
echo 'Next: prepare protected database roles/configs and rehearse restores.'
