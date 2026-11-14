#!/usr/bin/env bash
# Deploy the Gaming Content Engine on the server (Phase 15).
#
#   ./scripts/deploy.sh            deploy the newest main (origin/main)
#   ./scripts/deploy.sh <commit>   deploy a specific commit or tag (also: roll back)
#
# Steps: check .env and safety switches -> back up the database (if the stack
# runs) -> check out the version -> build -> start (migrations run in "migrate")
# -> wait until /api/health/ready answers -> print the previous version for a
# rollback. Migrations only go forward; to undo one, restore the backup made in
# step 2 (docs/OPERATIONS.md, "Wiederherstellung").
set -euo pipefail

cd "$(dirname "$0")/.."
REF="${1:-origin/main}"
COMPOSE=(docker compose --profile proxy --profile monitoring)
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health/ready}"

say() { printf '\n== %s\n' "$*"; }
fail() { printf 'FEHLER: %s\n' "$*" >&2; exit 1; }

say "1. Konfiguration prüfen"
[[ -f .env ]] || fail ".env fehlt (Vorlage: .env.example)"
env_value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '"' || true; }
for key in POSTGRES_PASSWORD REDIS_PASSWORD SECRET_KEY CREDENTIALS_ENCRYPTION_KEY BACKUP_PASSPHRASE; do
  [[ -n "$(env_value "$key")" ]] || fail "$key ist in .env nicht gesetzt"
done
[[ "$(env_value APP_ENV)" == "production" ]] || echo "Hinweis: APP_ENV ist nicht 'production'."
if [[ "$(env_value AUTO_PUBLISH_ENABLED)" == "true" || "$(env_value PUBLISHING_MODE)" == "live" ]]; then
  echo "ACHTUNG: Echte Veröffentlichung ist in .env eingeschaltet (AUTO_PUBLISH_ENABLED/PUBLISHING_MODE)."
  echo "Das darf nur nach ausdrücklicher Freigabe so sein. Weiter mit Enter, Abbruch mit Strg+C."
  read -r _
fi
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail "Lokale Änderungen im Arbeitsverzeichnis – bitte erst klären"

PREVIOUS="$(git rev-parse HEAD)"

say "2. Datensicherung vor dem Update"
if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx postgres; then
  "${COMPOSE[@]}" run --rm --no-deps backup python -m app.backup run \
    || fail "Sicherung fehlgeschlagen – Update abgebrochen"
else
  echo "Stack läuft nicht – keine Sicherung nötig (Erstinstallation)."
fi

say "3. Version $REF holen"
git fetch --quiet origin
git checkout --quiet --detach "$REF"
echo "Neu: $(git log --oneline -1)"

say "4. Bauen und starten"
"${COMPOSE[@]}" build --pull
"${COMPOSE[@]}" up -d --remove-orphans

say "5. Bereitschaft prüfen"
for _ in $(seq 1 60); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "Backend bereit: $HEALTH_URL"
    "${COMPOSE[@]}" ps
    echo
    echo "Fertig. Zurück zur vorherigen Version: ./scripts/deploy.sh $PREVIOUS"
    exit 0
  fi
  sleep 5
done
"${COMPOSE[@]}" logs --tail 50 migrate backend || true
fail "Backend nach 5 Minuten nicht bereit. Zurück: ./scripts/deploy.sh $PREVIOUS"
