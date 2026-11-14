#!/usr/bin/env bash
# Phase-1-Prüfung: Struktur, Konfiguration, Secrets, Links, Compose-Validierung.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Struktur- und Inhaltsprüfung =="
python3 scripts/verify_phase1.py

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "== docker compose config =="
  docker compose --env-file .env.example \
    --profile proxy --profile workflow --profile monitoring config -q
  echo "  OK    docker-compose.yml ist gültig (alle Profile)"
else
  echo "WARNUNG: Docker Compose nicht verfügbar, Compose-Validierung übersprungen"
fi
