# Gaming Content Engine

Cloudbasiertes KI-System, das Gaming-Trends erkennt, rechtlich freigegebenes Gameplay zu eigenständigen Kurzvideos verarbeitet, diese auf Deutsch und Englisch auf YouTube Shorts, TikTok, Instagram Reels und Facebook Reels veröffentlicht und anhand der tatsächlichen Ergebnisse selbst entscheidet, wann und wie viel pro Kanal veröffentlicht wird.

> **Status:** Phase 3 von 15 abgeschlossen (Backend, Datenbank, Queue, Anmeldung, Dashboard-Grundgerüst). Noch keine Agenten. Siehe [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## Grundprinzipien

- **Keine Veröffentlichung ohne Rechteprüfung und Qualitätsfreigabe.**
- **Keine feste Tagesmenge.** Der Publishing Strategy Agent entscheidet pro Kanal anhand von Daten.
- **Automatische Veröffentlichung ist standardmäßig aus** (`AUTO_PUBLISH_ENABLED=false`, `PUBLISHING_MODE=mock`).
- **Keine kostenpflichtigen API-Aufrufe ohne Freigabe** (`PAID_API_CALLS_ENABLED=false`).
- **Nur offizielle Plattform-APIs**, keine Passwort-Bots.

## Dokumentation

| Datei | Inhalt |
|---|---|
| [PROJECT_SPEC.md](PROJECT_SPEC.md) | Vollständige Spezifikation (verbindlich) |
| [CLAUDE.md](CLAUDE.md) | Arbeitsregeln für Claude Code |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Systemarchitektur, Datenfluss, Datenmodell, Statusmaschine |
| [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) | 15 Phasen mit Lieferumfang und Abnahmekriterien |
| [docs/AGENTS.md](docs/AGENTS.md) | Die 18 Agenten: Aufgaben, Ein-/Ausgaben, Grenzen |
| [docs/API_INTEGRATIONS.md](docs/API_INTEGRATIONS.md) | Externe Schnittstellen, Berechtigungen, offene Prüfpunkte |
| [docs/SECURITY.md](docs/SECURITY.md) | Sicherheitskonzept, Secrets, Not-Aus |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Betrieb: Deployment, Überwachung, Datensicherung, Härtung, Skalierung |
| [docs/ACCEPTANCE_TEST.md](docs/ACCEPTANCE_TEST.md) | Abnahmetest nach Spezifikation Abschnitt 20: echt vs. simuliert, Befunde, Voraussetzungen für den Livebetrieb |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Entwicklungsplan nach Phase 15 (Phasen A–D) mit Kosten und Freigaben |
| [docs/PRODUCTION_CHECKLIST.md](docs/PRODUCTION_CHECKLIST.md) | Checkliste bis zum Produktivstart auf Hetzner (Betreiber, Agent, Server) |
| [docs/PRIVATE_ACCESS.md](docs/PRIVATE_ACCESS.md) | Private Nutzung: Cloudflare Tunnel + Access, Einzelbenutzer, Datenschutz-URLs, Impressum |
| [docs/UPLOADS.md](docs/UPLOADS.md) | Fortsetzbarer Upload großer Dateien in Teilstücken (Protokoll, Verbraucher) |
| [docs/CONTENT_PLATFORM_PLAN.md](docs/CONTENT_PLATFORM_PLAN.md) | Erweiterung zur KI-Content-Plattform (Themenbereiche, Chat, Phasen E1–E10) |
| [docs/HETZNER_VORBEREITUNG.md](docs/HETZNER_VORBEREITUNG.md) | Vorbereitung Hetzner: Speicherbedarf, Aufräumregeln, Checkliste je Plattform-App, Ablauf am Bestelltag |
| [docs/BEDIENUNGSANLEITUNG.md](docs/BEDIENUNGSANLEITUNG.md) | Bedienung der neuen Seiten und gesammelte offene Freigaben |
| [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) | Aktueller Stand, offene Punkte |

## Projektstruktur

```
backend/          FastAPI-Anwendung, Worker, Datenmodell, Tests (siehe backend/README.md)
frontend/         Next.js-Dashboard (siehe frontend/README.md)
infrastructure/   Docker-, Caddy- und Monitoring-Konfiguration
scripts/          Hilfs- und Prüfskripte
docs/             Projektdokumentation
```

## Schnellstart

Voraussetzungen: Docker mit Compose-Plugin.

```bash
cp .env.example .env
# In .env alle Werte "change-me" ersetzen (siehe Kommentare in der Datei)
docker compose up -d --build    # PostgreSQL, Redis, Migration + Seed, Backend, Worker, Dashboard
docker compose ps               # postgres/redis "healthy", migrate "exited (0)"
docker compose run --rm backend python -m app.create_admin --email du@example.com
```

Dashboard: http://127.0.0.1:3000 (lokal über HTTP nur mit `SESSION_COOKIE_SECURE=false` in `.env`; auf dem Server über Caddy mit HTTPS).

Prüfungen: `./scripts/verify_phase1.sh` (Struktur, Secrets, Compose) und `./scripts/test_backend.sh` (Lint, Typen, Tests; siehe [backend/README.md](backend/README.md)).

Optionale Profile: `--profile proxy` (Caddy), `--profile workflow` (n8n), `--profile monitoring` (Uptime Kuma).

## Technologie

Python/FastAPI · Next.js/React/TypeScript · PostgreSQL · Redis · n8n · FFmpeg/OpenCV/PySceneDetect · Cloudflare R2 · Caddy · Docker Compose · Uptime Kuma. Zielserver: Hetzner Cloud CX33 (Ubuntu 24.04 LTS).
