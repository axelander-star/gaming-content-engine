#!/usr/bin/env bash
# Creates or completes .env on the server for private operation behind Cloudflare.
#
# Run on the server in the repository folder (as the deploy user, no root needed):
#   ./scripts/setup_env.sh
#
# What it does:
#   - copies .env.example to .env if there is no .env yet
#   - generates every password and key that is still empty or "change-me"
#     (existing values are never replaced, so running it again is safe)
#   - sets the switches for private operation (production, Cloudflare Access,
#     single user, Caddy only on 127.0.0.1)
#   - asks for the few values only the operator knows (e-mail, tunnel token, ...);
#     Enter keeps the value shown in brackets
#   - sets the file mode to 600 and runs the read-only preflight check
#
# Safety switches (AUTO_PUBLISH_ENABLED, PUBLISHING_MODE, PAID_API_CALLS_ENABLED)
# are not touched. No value is ever written anywhere but .env.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
umask 077

if [[ ! -f "$ENV_FILE" ]]; then
  cp .env.example "$ENV_FILE"
  echo "Neue $ENV_FILE aus .env.example angelegt."
else
  cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
  echo "$ENV_FILE gefunden, Sicherungskopie angelegt. Vorhandene Werte bleiben erhalten."
fi
chmod 600 "$ENV_FILE"

get() {  # current value without inline comment and quotes
  grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- \
    | sed 's/[[:space:]]\{1,\}#.*$//; s/[[:space:]]*$//; s/^"//; s/"$//' || true
}

set_kv() {  # set_kv KEY VALUE: replace the first KEY= line, drop duplicates, or append
  local tmp
  tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
  KEY="$1" VALUE="$2" awk '
    BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["VALUE"]; done = 0 }
    index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 } ; next }
    { print }
    END { if (!done) print k "=" v }
  ' "$ENV_FILE" > "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

random_secret() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 32
  else head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

is_unset() { local v; v="$(get "$1")"; [[ -z "$v" || "$v" == "change-me" ]]; }

ask() {  # ask KEY "question" [default] [secret]
  local key="$1" question="$2" default="${3:-}" secret="${4:-}" current answer shown
  current="$(get "$key")"
  [[ "$current" == "change-me" ]] && current=""
  [[ -z "$current" ]] && current="$default"
  if [[ -n "$secret" ]]; then
    shown="$([[ -n "$current" ]] && echo "gesetzt, Enter behält ihn" || echo "leer")"
    read -r -s -p "$question [$shown]: " answer || answer=""
    echo
  else
    read -r -p "$question [${current}]: " answer || answer=""
  fi
  answer="${answer:-$current}"
  # A value must stay on one line and must not start an inline comment.
  answer="$(printf '%s' "$answer" | tr -d '\r\n')"
  if [[ "$answer" == *" #"* ]]; then
    echo "Das Zeichen ' #' ist in $key nicht erlaubt." >&2
    exit 1
  fi
  set_kv "$key" "$answer"
}

echo
echo "== 1. Passwörter und Schlüssel erzeugen =="
for key in SECRET_KEY CREDENTIALS_ENCRYPTION_KEY POSTGRES_PASSWORD REDIS_PASSWORD \
           BACKUP_PASSPHRASE N8N_ENCRYPTION_KEY N8N_BASIC_AUTH_PASSWORD; do
  if is_unset "$key"; then
    set_kv "$key" "$(random_secret)"
    echo "  $key erzeugt"
  else
    echo "  $key war schon gesetzt, unverändert"
  fi
done

echo
echo "== 2. Schalter für den privaten Betrieb =="
set_kv APP_ENV production
set_kv SESSION_COOKIE_SECURE true
set_kv ACCESS_GUARD cloudflare
set_kv SINGLE_USER_MODE true
set_kv CADDY_BIND 127.0.0.1
set_kv DOMAIN localhost
echo "  APP_ENV=production, ACCESS_GUARD=cloudflare, SINGLE_USER_MODE=true, CADDY_BIND=127.0.0.1"

echo
echo "== 3. Deine Angaben (Enter übernimmt den Wert in Klammern) =="
ask APP_HOST "Adresse des Dashboards (ohne https://)" "studio.example.de"
host="$(get APP_HOST)"
host="${host#https://}"; host="${host%%/*}"
set_kv APP_HOST "$host"
for provider in youtube tiktok meta instagram; do
  upper="$(printf '%s' "$provider" | tr '[:lower:]' '[:upper:]')"
  set_kv "${upper}_OAUTH_REDIRECT_URI" "https://${host}/api/oauth/${provider}/callback"
done
echo "  Rückleitungs-Adressen für YouTube, TikTok, Meta und Instagram auf https://${host}/api/oauth/…/callback gesetzt"
ask CF_ACCESS_TEAM_DOMAIN "Cloudflare-Teamdomäne (steht oben auf der Access-Anmeldeseite, z. B. name.cloudflareaccess.com)"
ask CF_ACCESS_ALLOWED_EMAILS "E-Mail-Adresse(n) mit Zugang, durch Komma getrennt"
ask CF_ACCESS_AUD "AUD-Tag der Cloudflare-Access-Anwendung (leer lassen, wenn noch nicht vorhanden)"
ask CLOUDFLARE_TUNNEL_TOKEN "Cloudflare-Tunnel-Token (wird beim Tippen nicht angezeigt)" "" secret
token="$(get CLOUDFLARE_TUNNEL_TOKEN)"
token="${token##*--token }"; token="${token## }"
set_kv CLOUDFLARE_TUNNEL_TOKEN "$token"
ask LEGAL_OPERATOR_NAME "Name für die Datenschutzseite"
ask LEGAL_CONTACT_EMAIL "Kontakt-E-Mail für die Datenschutzseite" "$(get CF_ACCESS_ALLOWED_EMAILS | cut -d, -f1)"
# Caddy needs a contact address even when only the tunnel is used (empty value = crash loop).
if is_unset ACME_EMAIL; then
  set_kv ACME_EMAIL "$(get LEGAL_CONTACT_EMAIL)"
  echo "  ACME_EMAIL auf die Kontakt-E-Mail gesetzt"
fi
ask LEGAL_UPDATED "Stand der Rechtstexte" "$(date +%d.%m.%Y)"
ask SERVER_MONTHLY_EUR "Servermiete pro Monat in Euro (für die Kostenübersicht, z. B. 13.33)" "0"

chmod 600 "$ENV_FILE"

echo
echo "== 4. Bitte jetzt in deinen Passwortmanager übernehmen =="
echo "Ohne diese beiden Werte sind Sicherungen und gespeicherte Plattform-Zugänge"
echo "nach einem Serververlust nicht mehr lesbar:"
echo "  BACKUP_PASSPHRASE=$(get BACKUP_PASSPHRASE)"
echo "  CREDENTIALS_ENCRYPTION_KEY=$(get CREDENTIALS_ENCRYPTION_KEY)"
echo "(Danach mit 'clear' den Bildschirm leeren.)"

echo
echo "== 5. Vorabprüfung =="
if [[ -z "$(get CF_ACCESS_AUD)" ]]; then
  echo "Hinweis: CF_ACCESS_AUD fehlt noch. Nach dem Anlegen der Access-Anwendung"
  echo "dieses Skript erneut starten und nur den AUD-Tag eintragen (Enter für alles andere)."
fi
./infrastructure/server/preflight.sh --env "$ENV_FILE" || true
