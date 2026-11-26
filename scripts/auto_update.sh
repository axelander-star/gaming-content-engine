#!/usr/bin/env bash
# Automatic update: deploy the newest main as soon as it changes.
#
# Run every few minutes by cron (install: ./scripts/install_auto_update.sh).
# Only main is deployed, and main only receives changes after a green CI run.
# If an update fails, the previous version is deployed again and the failed
# commit is not retried until a newer one arrives. Nothing here changes .env,
# so the safety switches (AUTO_PUBLISH_ENABLED, PUBLISHING_MODE) stay as they are;
# if real publishing is switched on, deploy.sh asks for Enter and the automatic
# run stops there instead of deploying.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/content-engine"
mkdir -p "$STATE_DIR"
# one run at a time (a deploy can take several minutes); the lock stays held
# through the exec below because the file descriptor is inherited
if [[ "${AUTO_UPDATE_COPY:-}" != "1" ]]; then
  exec 9>"$STATE_DIR/auto-update.lock"
  flock -n 9 || exit 0
fi
# the update replaces this file on disk: run from a copy so bash never reads a
# half-old, half-new script
if [[ "${AUTO_UPDATE_COPY:-}" != "1" ]]; then
  cp "$0" "$STATE_DIR/auto-update-run.sh"
  AUTO_UPDATE_COPY=1 AUTO_UPDATE_REPO="$REPO" exec bash "$STATE_DIR/auto-update-run.sh"
fi
cd "${AUTO_UPDATE_REPO:-$REPO}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
LOG="$STATE_DIR/auto-update.log"
FAILED="$STATE_DIR/failed-commit"

log() { printf '%s %s\n' "$(date -Is)" "$*" >>"$LOG"; }

git fetch --quiet origin main 2>>"$LOG" || { log "fetch fehlgeschlagen"; exit 1; }
CURRENT="$(git rev-parse HEAD)"
TARGET="$(git rev-parse origin/main)"
[[ "$CURRENT" == "$TARGET" ]] && exit 0
if [[ -f "$FAILED" && "$(cat "$FAILED")" == "$TARGET" ]]; then
  exit 0  # this commit failed before; wait for a newer one
fi

log "Update ${CURRENT:0:7} -> ${TARGET:0:7}: $(git log --format=%s -1 "$TARGET")"
if ./scripts/deploy.sh "$TARGET" </dev/null >>"$LOG" 2>&1; then
  rm -f "$FAILED"
  log "Update fertig"
  # keep the log short
  tail -n 2000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  exit 0
fi

echo "$TARGET" >"$FAILED"
log "Update fehlgeschlagen, zurück auf ${CURRENT:0:7}"
if ./scripts/deploy.sh "$CURRENT" </dev/null >>"$LOG" 2>&1; then
  log "Vorherige Version läuft wieder"
else
  log "ACHTUNG: Zurückspringen fehlgeschlagen, bitte ./scripts/deploy.sh $CURRENT von Hand"
fi
exit 1
