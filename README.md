# Gaming Content Engine

Cloudbasiertes KI-System, das Gaming-Trends erkennt, rechtlich freigegebenes Gameplay zu eigenständigen Kurzvideos verarbeitet, diese auf Deutsch und Englisch auf YouTube Shorts, TikTok, Instagram Reels und Facebook Reels veröffentlicht und anhand der tatsächlichen Ergebnisse selbst entscheidet, wann und wie viel pro Kanal veröffentlicht wird.

> **Status:** Phase 1 von 15 (Repository, Dokumentation, Architektur). Es gibt noch keinen lauffähigen Anwendungscode. Siehe [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

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
| [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) | Aktueller Stand, offene Punkte |

## Projektstruktur

```
backend/          FastAPI-Anwendung, Agenten, Services, Tests (ab Phase 2)
frontend/         Next.js-Dashboard (ab Phase 3)
infrastructure/   Docker-, Caddy- und Monitoring-Konfiguration
scripts/          Hilfs- und Prüfskripte
docs/             Projektdokumentation
```

## Schnellstart (Phase 1: nur Infrastruktur)

Voraussetzungen: Docker mit Compose-Plugin, Python 3.11+.

```bash
cp .env.example .env
# In .env alle Werte "change-me" ersetzen (siehe Kommentare in der Datei)
docker compose up -d            # PostgreSQL + Redis
docker compose ps               # beide Dienste sollten "healthy" sein
./scripts/verify_phase1.sh      # Strukturprüfung der Phase 1
```

Optionale Profile: `--profile proxy` (Caddy), `--profile workflow` (n8n), `--profile monitoring` (Uptime Kuma).

## Technologie

Python/FastAPI · Next.js/React/TypeScript · PostgreSQL · Redis · n8n · FFmpeg/OpenCV/PySceneDetect · Cloudflare R2 · Caddy · Docker Compose · Uptime Kuma. Zielserver: Hetzner Cloud CX33 (Ubuntu 24.04 LTS).
