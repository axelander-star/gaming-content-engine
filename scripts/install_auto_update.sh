#!/usr/bin/env bash
# Switch the automatic update on or off (cron job of the current user).
#
#   ./scripts/install_auto_update.sh         on: check every 5 minutes
#   ./scripts/install_auto_update.sh --off   off
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
    (crontab -l 2>/dev/null || true) | grep -vF "$MARK" | crontab -
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
chmod +x "$SCRIPT" scripts/deploy.sh
LINE="*/5 * * * * $SCRIPT >/dev/null 2>&1 $MARK"
{ (crontab -l 2>/dev/null || true) | grep -vF "$MARK"; echo "$LINE"; } | crontab -
echo "Automatisches Update ist an: alle 5 Minuten wird main geprüft und bei Neuem eingespielt."
echo "Protokoll: ./scripts/install_auto_update.sh --log   Ausschalten: ./scripts/install_auto_update.sh --off"
