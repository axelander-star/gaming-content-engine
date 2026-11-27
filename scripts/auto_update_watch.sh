#!/usr/bin/env bash
# Instant update: start the update within seconds after a merge to main.
#
# GitHub reports every push to the backend (/api/hooks/github, signed). For a
# push to main the backend drops infrastructure/deploy-hook/trigger. This watcher
# looks for that file every 2 seconds and then runs scripts/auto_update.sh, which
# does the actual work (green main only, backup, rollback on failure). It needs
# no daemon: cron starts it every minute, it runs for about a minute, and only
# one copy runs at a time. Installed by scripts/install_auto_update.sh (and set up
# automatically by auto_update.sh).
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/content-engine"
mkdir -p "$STATE_DIR"
if [[ "${AUTO_UPDATE_WATCH_COPY:-}" != "1" ]]; then
  exec 8>"$STATE_DIR/auto-update-watch.lock"
  flock -n 8 || exit 0  # a watcher is already running (or deploying)
  # an update replaces this file on disk: run from a copy
  cp "$0" "$STATE_DIR/auto-update-watch-run.sh"
  AUTO_UPDATE_WATCH_COPY=1 AUTO_UPDATE_REPO="$REPO" exec bash "$STATE_DIR/auto-update-watch-run.sh"
fi
REPO="${AUTO_UPDATE_REPO:-$REPO}"
HOOK_DIR="$REPO/infrastructure/deploy-hook"
TRIGGER="$HOOK_DIR/trigger"
RUN_SECONDS="${AUTO_UPDATE_WATCH_SECONDS:-55}"
POLL="${AUTO_UPDATE_WATCH_POLL:-2}"
[[ -d "$HOOK_DIR" ]] || exit 0

end=$((SECONDS + RUN_SECONDS))
touch "$HOOK_DIR/watcher" 2>/dev/null || true
while ((SECONDS < end)); do
  if [[ -e "$TRIGGER" ]]; then
    rm -f "$TRIGGER"
    # waits if the five-minute check is deploying right now, then fetches again
    AUTO_UPDATE_WAIT=1 "$REPO/scripts/auto_update.sh" || true
    touch "$HOOK_DIR/watcher" 2>/dev/null || true
  fi
  sleep "$POLL"
done
exit 0
