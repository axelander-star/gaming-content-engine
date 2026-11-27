#!/usr/bin/env bash
# Switch the automatic update on or off (cron job of the current user).
#
#   ./scripts/install_auto_update.sh         on: check every 5 minutes, plus the
#                                            instant update right after a merge
#                                            (GitHub webhook, docs/INSTANT_UPDATE.md)
#   ./scripts/install_auto_update.sh --off   off (both)
#   ./scripts/install_auto_update.sh --log   show the last log lines
set -euo pipefail

cd "$(dirname "$0")/.."
SCRIPT="$(pwd)/scripts/auto_update.sh"
MARK="# content-engine auto-update"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/content-engine/auto-update.log"

case "${1:-}" in
  --log)
    tail -n 40 "$LOG" 2>/dev/null || echo "Noch kein Protokoll: $LOG"
    exit 0
    ;;
  --off)
    # also removes the watcher line ("# content-engine auto-update-watch")
    current="$(crontab -l 2>/dev/null || true)"
    grep -vF "$MARK" <<<"$current" | grep -v '^$' | crontab - || true
    echo "Automatisches Update ist aus."
    exit 0
    ;;
  "") ;;
  *)
    echo "Unbekannte Option: $1 (erlaubt: --off, --log)" >&2
    exit 2
    ;;
esac

command -v crontab >/dev/null || { echo "FEHLER: cron fehlt (sudo apt install cron)" >&2; exit 1; }
command -v flock >/dev/null || { echo "FEHLER: flock fehlt (sudo apt install util-linux)" >&2; exit 1; }
chmod +x "$SCRIPT" scripts/deploy.sh scripts/auto_update_watch.sh
LINE="*/5 * * * * $SCRIPT >/dev/null 2>&1 $MARK"
WATCH="* * * * * $(pwd)/scripts/auto_update_watch.sh >/dev/null 2>&1 $MARK-watch"
# Read first, then filter without letting grep's "no line left" status stop the
# script (set -e/pipefail): with an empty crontab that used to end it silently.
CURRENT="$(crontab -l 2>/dev/null || true)"
{ grep -vF "$MARK" <<<"$CURRENT" | grep -v '^$' || true; echo "$LINE"; echo "$WATCH"; } | crontab -
HOOK_DIR=infrastructure/deploy-hook
chmod 0733 "$HOOK_DIR"
if [[ ! -s "$HOOK_DIR/secret" ]]; then
  (umask 022 && head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' >"$HOOK_DIR/secret")
fi
echo "Automatisches Update ist an: nach einem Merge sofort (GitHub-Webhook), sonst alle 5 Minuten."
echo "Webhook-Geheimnis und Status: im Studio unter System > Sofort-Update."
echo "Protokoll: ./scripts/install_auto_update.sh --log   Ausschalten: ./scripts/install_auto_update.sh --off"
