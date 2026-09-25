#!/usr/bin/env bash
# Install rehearsed code and disabled user units, without starting any app/job.
set -euo pipefail
[[ $(hostname -s) == a1347-m && $(id -un) == mjm2z ]] || {
  echo 'Run as mjm2z on a1347-m.' >&2; exit 1;
}
readonly STAGING="$HOME/app-migration-20260924"
readonly UNITS="$HOME/.config/systemd/user"
for app in job-watch app-demand-radar; do
  [[ ! -e "$HOME/$app" && ! -L "$HOME/$app" ]] || {
    echo "Existing app path needs review: $app" >&2; exit 1;
  }
  [[ ! -e "$HOME/.config/app-migration/$app.cutover-ready" ]] || {
    echo 'Cutover marker already exists; refusing staging.' >&2; exit 1;
  }
  [[ -d "$STAGING/$app" && -f "$HOME/.config/$app/runtime.env" ]] || exit 1
done
[[ -f "$STAGING/job-watch/.next/BUILD_ID" ]] || exit 1
[[ -f "$STAGING/app-demand-radar/frontend/dist/index.html" ]] || exit 1
for source in "$STAGING/service-units-v2/"*; do
  name=$(basename "$source")
  [[ ! -e "$UNITS/$name" && ! -L "$UNITS/$name" ]] || {
    echo "Existing unit requires review: $name" >&2; exit 1;
  }
  if systemctl --user is-active --quiet "$name"; then
    echo "Unit already active: $name" >&2; exit 1
  fi
done
systemd-analyze --user verify "$STAGING/service-units-v2/"*
for app in job-watch app-demand-radar; do
  cp -a "$STAGING/$app" "$HOME/$app"
done
mkdir -p "$UNITS" "$HOME/.local/state/app-demand-radar/logs"
for source in "$STAGING/service-units-v2/"*; do
  install -m 644 "$source" "$UNITS/$(basename "$source")"
done
systemctl --user daemon-reload
echo 'Code and disabled units installed. No cutover markers created; no jobs started.'
systemctl --user list-unit-files 'job-watch-*' 'app-demand-radar*' --no-pager
