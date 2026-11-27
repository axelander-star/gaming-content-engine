#!/usr/bin/env bash
# Automatic update: deploy the newest main as soon as it changes.
#
# Run every few minutes by cron (install: ./scripts/install_auto_update.sh) and,
# right after a merge, by scripts/auto_update_watch.sh (GitHub webhook).
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
  if [[ "${AUTO_UPDATE_WAIT:-}" == "1" ]]; then
    flock -w 1800 9 || exit 0  # webhook: wait for a running update, then check again
  else
    flock -n 9 || exit 0
  fi
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

HOOK_DIR="$(pwd)/infrastructure/deploy-hook"
WATCH_MARK="# content-engine auto-update-watch"

log() { printf '%s %s\n' "$(date -Is)" "$*" >>"$LOG"; }

# Instant update (27.11.2026): make sure the webhook secret exists and the
# watcher runs. Idempotent and cheap, so every run simply checks it; this is how
# servers that only had the five-minute check get the instant update without
# anyone logging in. Off again with ./scripts/install_auto_update.sh --off.
setup_instant_update() {
  [[ -d "$HOOK_DIR" && -x ./scripts/auto_update_watch.sh ]] || return 0
  # the backend (other user id in its container) writes the trigger file here
  chmod 0733 "$HOOK_DIR" 2>/dev/null || true
  if [[ ! -s "$HOOK_DIR/secret" ]]; then
    (umask 022 && head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' >"$HOOK_DIR/secret.tmp" \
      && mv "$HOOK_DIR/secret.tmp" "$HOOK_DIR/secret") && log "Webhook-Geheimnis angelegt"
  fi
  command -v crontab >/dev/null || return 0
  local current
  current="$(crontab -l 2>/dev/null || true)"
  if ! grep -qF "$WATCH_MARK" <<<"$current"; then
    local line="* * * * * $(pwd)/scripts/auto_update_watch.sh >/dev/null 2>&1 $WATCH_MARK"
    printf '%s\n%s\n' "$current" "$line" | grep -v '^$' | crontab - \
      && log "Sofort-Update eingeschaltet"
  fi
}

# Result of the last run for the dashboard (System page).
record() {
  local subject
  subject="$(git log --format=%s -1 "$2" 2>/dev/null | sed 's/\\/\\\\/g; s/"/\\"/g' | tr -d '\000-\037')"
  printf '{"at": "%s", "from": "%s", "to": "%s", "subject": "%s", "result": "%s"}\n' \
    "$(date -Is)" "${1:0:7}" "${2:0:7}" "$subject" "$3" >"$HOOK_DIR/last-update.tmp" 2>/dev/null \
    && mv "$HOOK_DIR/last-update.tmp" "$HOOK_DIR/last-update" 2>/dev/null || true
}

setup_instant_update

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
  record "$CURRENT" "$TARGET" ok
  # keep the log short
  tail -n 2000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  exit 0
fi

echo "$TARGET" >"$FAILED"
log "Update fehlgeschlagen, zurück auf ${CURRENT:0:7}"
if ./scripts/deploy.sh "$CURRENT" </dev/null >>"$LOG" 2>&1; then
  log "Vorherige Version läuft wieder"
  record "$CURRENT" "$TARGET" rolled_back
else
  record "$CURRENT" "$TARGET" failed
  log "ACHTUNG: Zurückspringen fehlgeschlagen, bitte ./scripts/deploy.sh $CURRENT von Hand"
fi
exit 1
