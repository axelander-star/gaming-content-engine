#!/usr/bin/env bash
# Read-only check of a freshly ordered server before the first deploy.
#
# Run on the server (no root needed, changes nothing):
#   ./infrastructure/server/preflight.sh            # checks the machine
#   ./infrastructure/server/preflight.sh --env .env # also checks the .env file
#
# Checks: Ubuntu 24.04, CPU, RAM, free disk, swap, Docker with Compose, clock
# sync, open ports, and (with --env) required values and safe defaults.
# Exit code 0 = ready, 1 = something must be fixed first. Warnings do not fail.
set -uo pipefail

ENV_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_FILE="${2:-}"; shift 2 ;;
    *) echo "Unbekannte Option: $1 (erlaubt: --env DATEI)" >&2; exit 2 ;;
  esac
done

MIN_CPUS="${MIN_CPUS:-4}"
MIN_RAM_GB="${MIN_RAM_GB:-7}"      # CX33 has 8 GB, the kernel keeps some
MIN_FREE_GB="${MIN_FREE_GB:-40}"   # images ~10 GB plus room for media
FAIL=0
ok()   { printf '  OK    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; }
bad()  { printf '  FEHLT %s\n' "$*"; FAIL=1; }

echo "== System =="
if [ -r /etc/os-release ]; then
  . /etc/os-release
  if [ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID:-}" = "24.04" ]; then ok "Ubuntu 24.04"
  else warn "Betriebssystem ${PRETTY_NAME:-unbekannt} (getestet ist Ubuntu 24.04)"; fi
fi
cpus=$(nproc 2>/dev/null || echo 0)
[ "$cpus" -ge "$MIN_CPUS" ] && ok "$cpus CPU-Kerne" || bad "$cpus CPU-Kerne (mindestens $MIN_CPUS)"
ram_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
ram_gb=$((ram_kb / 1024 / 1024))
[ "$ram_gb" -ge "$MIN_RAM_GB" ] && ok "${ram_gb} GB RAM" || bad "${ram_gb} GB RAM (mindestens $MIN_RAM_GB)"
swap_kb=$(awk '/SwapTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
[ "$swap_kb" -gt 0 ] && ok "Swap vorhanden" || warn "kein Swap (empfohlen: 2–4 GB Swapdatei gegen Abstürze beim Rendern)"
free_gb=$(df -Pk / | awk 'NR==2 {print int($4/1024/1024)}')
[ "$free_gb" -ge "$MIN_FREE_GB" ] && ok "${free_gb} GB frei auf /" || bad "${free_gb} GB frei auf / (mindestens $MIN_FREE_GB)"

echo "== Docker =="
if command -v docker >/dev/null 2>&1; then
  server=$(docker version --format '{{.Server.Version}}' 2>/dev/null) || server=""
  [ -n "$server" ] && ok "Docker $server" || bad "Docker-Dienst nicht erreichbar (läuft er? Gruppe docker?)"
  docker compose version >/dev/null 2>&1 && ok "Compose-Plugin" || bad "Compose-Plugin fehlt"
else
  bad "Docker fehlt (offizielle Anleitung: docs.docker.com/engine/install/ubuntu/)"
fi
command -v ffmpeg >/dev/null 2>&1 && warn "FFmpeg auf dem Host ist nicht nötig (läuft im Container)" || true

echo "== Zeit und Netz =="
if command -v timedatectl >/dev/null 2>&1; then
  [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = "yes" ] && ok "Uhrzeit synchronisiert" \
    || bad "Uhrzeit nicht synchronisiert (OAuth und signierte Adressen brauchen die richtige Zeit)"
fi
if command -v ss >/dev/null 2>&1; then
  open=$(ss -Htln 2>/dev/null | awk '{print $4}' | sed 's/.*://' | sort -un | tr '\n' ' ')
  ok "lauschende Ports: ${open:-keine}"
  for p in 5432 6379 8000 3000; do
    if ss -Htln 2>/dev/null | awk '{print $4}' | grep -Eq "^(0\.0\.0\.0|\*|\[::\]):$p$"; then
      bad "Port $p ist von außen erreichbar (Datenbank, Redis und App gehören ins interne Netz)"
    fi
  done
fi

if [ -n "$ENV_FILE" ]; then
  echo "== $ENV_FILE =="
  if [ ! -r "$ENV_FILE" ]; then
    bad "$ENV_FILE nicht lesbar"
  else
    mode=$(stat -c '%a' "$ENV_FILE")
    [ "$mode" = "600" ] && ok "Rechte 600" || bad "Rechte $mode (erwartet 600: chmod 600 $ENV_FILE)"
    val() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/^"//; s/"$//'; }
    for k in POSTGRES_PASSWORD REDIS_PASSWORD SECRET_KEY CREDENTIALS_ENCRYPTION_KEY BACKUP_PASSPHRASE; do
      [ -n "$(val "$k")" ] && ok "$k gesetzt" || bad "$k leer"
    done
    [ "$(val APP_ENV)" = "production" ] && ok "APP_ENV=production" || warn "APP_ENV ist nicht production"
    [ "$(val PUBLISHING_MODE)" != "live" ] && ok "PUBLISHING_MODE bleibt mock" \
      || warn "PUBLISHING_MODE=live: nur mit ausdrücklicher Freigabe des Betreibers"
    [ "$(val AUTO_PUBLISH_ENABLED)" != "true" ] && ok "AUTO_PUBLISH_ENABLED bleibt aus" \
      || warn "AUTO_PUBLISH_ENABLED=true: nur mit ausdrücklicher Freigabe des Betreibers"
    [ "$(val PAID_API_CALLS_ENABLED)" != "true" ] && ok "kostenpflichtige API-Aufrufe aus" \
      || warn "PAID_API_CALLS_ENABLED=true: KI-Kosten laufen (Grenze 20 \$/Monat)"
    if [ "$(val ACCESS_GUARD)" = "cloudflare" ]; then
      for k in CF_ACCESS_TEAM_DOMAIN CF_ACCESS_AUD CF_ACCESS_ALLOWED_EMAILS CLOUDFLARE_TUNNEL_TOKEN; do
        [ -n "$(val "$k")" ] && ok "$k gesetzt" || bad "$k leer (privater Zugang)"
      done
    else
      warn "ACCESS_GUARD ist nicht cloudflare: das Dashboard wäre ohne Cloudflare Access erreichbar"
    fi
  fi
fi

echo
if [ "$FAIL" -eq 0 ]; then echo "Bereit für ./scripts/deploy.sh"; else echo "Erst die Punkte mit FEHLT beheben."; fi
exit "$FAIL"
