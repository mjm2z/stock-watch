#!/usr/bin/env bash
set -euo pipefail

readonly NODE_VERSION="24.16.0"
readonly NODE_ARCHIVE="node-v${NODE_VERSION}-linux-x64.tar.xz"
readonly NODE_SHA256="d804845d34eddc21dc1092b519d643ef40b1f58ec5dec5c22b1f4bd8fabde6c9"
readonly NODE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_ARCHIVE}"
readonly RELEASE_SOURCE="${1:-/home/mjm2z/stock-watch-staging}"
readonly INSTALL_ROOT="/opt/stock-watch"
readonly STATE_ROOT="/var/lib/stock-watch"
readonly BACKUP_ROOT="/var/backups/stock-watch"
readonly ENVIRONMENT_ROOT="/etc/stock-watch"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this bootstrap as root." >&2
  exit 1
fi
if [[ ! -f "${RELEASE_SOURCE}/package-lock.json" || ! -d "${RELEASE_SOURCE}/worker" ]]; then
  echo "Release source is incomplete: ${RELEASE_SOURCE}" >&2
  exit 1
fi
if [[ -e "${RELEASE_SOURCE}/.env" || -e "${RELEASE_SOURCE}/.env.local" ]]; then
  echo "Refusing a release source containing environment secrets." >&2
  exit 1
fi

task_temp_dir="$(mktemp -d /tmp/stock-watch-bootstrap.XXXXXX)"
trap 'rm -rf -- "${task_temp_dir}"' EXIT

if ! id stock-watch >/dev/null 2>&1; then
  useradd --system --home "${STATE_ROOT}" --shell /usr/sbin/nologin stock-watch
fi
install -d -o root -g root -m 0755 "${INSTALL_ROOT}"
install -d -o stock-watch -g stock-watch -m 0700 \
  "${STATE_ROOT}" "${STATE_ROOT}/data" "${BACKUP_ROOT}"
install -d -o root -g root -m 0700 "${ENVIRONMENT_ROOT}"

if [[ ! -x "/opt/node-v${NODE_VERSION}/bin/node" ]]; then
  curl --fail --location --silent --show-error \
    --output "${task_temp_dir}/${NODE_ARCHIVE}" "${NODE_URL}"
  echo "${NODE_SHA256}  ${task_temp_dir}/${NODE_ARCHIVE}" | sha256sum --check --status
  tar -xJf "${task_temp_dir}/${NODE_ARCHIVE}" -C /opt
fi
ln -sfn "/opt/node-v${NODE_VERSION}-linux-x64" "/opt/node-v${NODE_VERSION}"
ln -sfn "/opt/node-v${NODE_VERSION}/bin/node" /usr/local/bin/node
ln -sfn "/opt/node-v${NODE_VERSION}/bin/npm" /usr/local/bin/npm
ln -sfn "/opt/node-v${NODE_VERSION}/bin/npx" /usr/local/bin/npx

rsync -a \
  --exclude='.git/' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='.next/' \
  --exclude='node_modules/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='*.db' \
  --exclude='*.sqlite' \
  --exclude='*.sqlite3' \
  "${RELEASE_SOURCE}/" "${INSTALL_ROOT}/"
chown -R root:root "${INSTALL_ROOT}"

if ! dpkg-query --show --showformat='${Status}' python3.12-venv 2>/dev/null \
    | grep -q 'install ok installed'; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3.12-venv
fi
python3.12 -m venv --clear "${INSTALL_ROOT}/.venv"
"${INSTALL_ROOT}/.venv/bin/pip" install --disable-pip-version-check \
  "${INSTALL_ROOT}/worker"
(
  cd "${INSTALL_ROOT}"
  /usr/local/bin/npm ci
  /usr/local/bin/npm run build
)

if [[ ! -f "${ENVIRONMENT_ROOT}/stock-watch.env" ]]; then
  install -o root -g root -m 0600 \
    "${INSTALL_ROOT}/deploy/stock-watch.env.example" \
    "${ENVIRONMENT_ROOT}/stock-watch.env"
fi
runuser -u stock-watch -- \
  "${INSTALL_ROOT}/.venv/bin/stock-watch-worker" init-db \
  --database "${STATE_ROOT}/stock-watch.db" \
  --strategy "${INSTALL_ROOT}/worker/config/strategy-v0.json"
chown -R stock-watch:stock-watch "${STATE_ROOT}" "${BACKUP_ROOT}"
chown -R stock-watch:stock-watch "${INSTALL_ROOT}/.next/cache"

install -o root -g root -m 0644 \
  "${INSTALL_ROOT}"/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now stock-watch-web.service

curl --fail --silent --show-error --retry 10 --retry-delay 1 --retry-connrefused \
  http://127.0.0.1:3001/api/health
echo
echo "Dashboard installed. Worker timers remain disabled."
echo "Trusted-LAN dashboard addresses (no application login):"
for address in $(hostname -I 2>/dev/null); do
  if [[ "${address}" != *:* && "${address}" != 127.* ]]; then
    echo "  http://${address}:3001"
  fi
done
echo "Next: configure ${ENVIRONMENT_ROOT}/stock-watch.env, then run the separate"
echo "activation script with an approved universe CSV and its direct HTTPS CSV URL."
