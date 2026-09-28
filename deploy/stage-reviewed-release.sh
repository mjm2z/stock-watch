#!/usr/bin/env bash
# Stage and verify a committed StockWatch release; never installs production services.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "$(git status --porcelain)" ]]; then
  echo 'Commit all reviewed source before staging.' >&2
  exit 1
fi
revision=$(git rev-parse HEAD)
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
reuse=${1:-}
if [[ -n "$reuse" && ! "$reuse" =~ ^/home/mjm2z/stock-watch-releases/[0-9a-f]{12}$ ]]; then
  echo 'Optional dependency source must be an incomplete release staging directory.' >&2
  exit 1
fi
staging="/home/mjm2z/stock-watch-releases/${revision:0:12}"
archive=$(mktemp /tmp/stock-watch-release.XXXXXX)
trap 'rm -f "$archive"' EXIT
git archive --format=tar "$revision" > "$archive"
ssh -o BatchMode=yes a1347-m "mkdir '$staging'"
scp "$archive" "a1347-m:$staging/source.tar"
ssh -o BatchMode=yes a1347-m "bash -s -- '$staging' '$revision' '$reuse'" <<'REMOTE'
set -euo pipefail
cd "$1"
tar -xf source.tar
printf '%s\n' "$2" > source-revision.txt
if [[ -n "$3" ]]; then
  test ! -e "$3/reviewed-release.json"
  cmp package-lock.json "$3/package-lock.json"
  mv "$3/node_modules" node_modules
else
  npm ci --no-audit --no-fund
fi
# SQLite test fixtures do many fsyncs; isolate them from the production disk.
test_tmp=$(mktemp -d /dev/shm/stock-watch-tests.XXXXXX)
trap 'rm -rf "$test_tmp"' EXIT
export TMPDIR="$test_tmp"
npm run type-check
npm run lint
npm test -- --runInBand
npm run test:feed
npm run build
PYTHONPATH=worker/src python3.12 -m unittest discover -s worker/tests -q
python3.12 -m venv .build-venv
.build-venv/bin/pip wheel --no-deps ./worker --wheel-dir release-wheels
rm -rf .build-venv
python3.12 deploy/build-reviewed-manifest.py "$2"
python3.12 deploy/install-reviewed-release.py "$1" --check
printf 'Verified staging: %s\nRevision: %s\n' "$1" "$2"
REMOTE
