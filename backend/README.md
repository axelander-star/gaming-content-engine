# Backend

FastAPI-API, RQ-Worker und Datenmodell der Gaming Content Engine. Python 3.12+, Importwurzel ist dieser Ordner.

## Aufbau

| Ordner | Inhalt |
|---|---|
| `app/` | Einstiegspunkte: `main.py` (API), `worker.py` (Queue-Worker), `scheduler.py` (Zeitsteuerung), `seed.py` (Basisdaten) |
| `api/` | HTTP-Router: Health, Auth, Benutzer, Einstellungen, Kanäle, Übersicht, Agenten, Trends |
| `core/` | Konfiguration, Logging, Enums, Statusabläufe (`states.py`) |
| `database/` | Engine/Session, Basisklassen, Alembic-Migrationen |
| `models/` | SQLAlchemy-Modelle aller 27 Tabellen, nach Bereich gruppiert |
| `services/` | Geschäftslogik: Statuswechsel (`workflow.py`), Gates, Orchestrator, Budget, Trends, Trendquellen (`sources/`), Queue, Health, Seed |
| `workflows/` | Queue-Jobs (Heartbeat); Agenten-Jobs: `services/orchestrator.run_agent_job` |
| `agents/` | Basisklasse, Registry aller 18 Agenten, Master, Budget & Cost, Trend Research, Game Intelligence |
| `tests/` | `unit/` ohne Abhängigkeiten, `integration/` gegen PostgreSQL + Redis |

## Lokal entwickeln

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# PostgreSQL + Redis aus dem Compose-Setup (im Projektordner):
#   docker compose up -d postgres redis
export DATABASE_URL=postgresql+psycopg://gce:<passwort>@127.0.0.1:5432/gce
export REDIS_PASSWORD=<passwort>

alembic upgrade head        # Schema anlegen
python -m app.seed          # 4 Plattformen + 8 Kanäle (idempotent)
python -m app.create_admin --email du@example.com   # erster Admin (Passwort-Abfrage)
uvicorn app.main:app --reload
python -m app.worker        # in zweitem Terminal
python -m app.scheduler     # in drittem Terminal (Master-Takt, Budgetprüfung)
```

API-Dokumentation (nur außerhalb von Production): http://127.0.0.1:8000/api/docs

## Endpunkte

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/health` | Prozess läuft (Liveness) |
| GET | `/api/health/ready` | PostgreSQL und Redis erreichbar; sonst HTTP 503 |
| POST | `/api/auth/login` | Anmeldung; setzt HttpOnly-Session- und CSRF-Cookie; Sperre nach 5 Fehlversuchen |
| POST | `/api/auth/logout`, `/api/auth/logout-all` | Abmelden (dieses Gerät / alle Geräte) |
| GET | `/api/auth/me` | Angemeldeter Benutzer |
| GET/POST/PATCH | `/api/users` | Benutzerverwaltung (Admin) |
| GET | `/api/settings` | Wirksame Steuerung + Betriebseinstellungen (alle Rollen) |
| PATCH | `/api/settings/controls` | Not-Aus auslösen (Operator) bzw. lösen und Auto-Publish (Admin) |
| PATCH | `/api/settings/operations` | Budget, Job-Limits, Mindestqualität usw. (Admin) |
| GET | `/api/channels` | Kanäle |
| POST | `/api/channels/{id}/pause`, `/resume` | Pausieren (Operator) / Fortsetzen (Admin) |
| PUT | `/api/channels/{id}/limits` | Sicherheitsgrenzen pro Kanal (Admin) |
| GET | `/api/overview` | Kennzahlen für die Übersichtsseite |
| GET | `/api/agents` | Status aller 18 Agenten (letzter Lauf, Aufgabe, Fehler, Kosten) |
| POST | `/api/agents/{name}/pause`, `/resume` | Agent pausieren (Operator) / fortsetzen (Admin) |
| POST | `/api/agents/{name}/run` | Master oder Budget-Agent sofort einreihen (Admin) |
| GET | `/api/agents/{name}/runs` | Letzte Läufe eines Agenten |
| GET | `/api/agents/decisions` | Letzte Entscheidungen (optional `?agent=`) |
| GET | `/api/agents/budget` | Budgetstand und -stufe des laufenden Monats |
| GET | `/api/trends?language=de` | Aktuelle Trends je Sprache (Score, Wachstum, Zielgruppe, Quellen) |
| GET | `/api/trends/report?language=de` | Neuester Trendbericht |
| GET | `/api/games`, `/api/games/{id}` | Spiele mit Profil (Zielgruppe, Modi, Videoideen) |

Alle Endpunkte außer Health und Login brauchen eine Sitzung. Schreibende Anfragen brauchen zusätzlich den Header `X-CSRF-Token` mit dem Wert des Cookies `gce_csrf`.

## Tests

Integrationstests brauchen eine **eigene, leere Datenbank**, weil sie das Schema bei jedem Lauf neu aufbauen:

```bash
export TEST_DATABASE_URL=postgresql+psycopg://gce:<passwort>@127.0.0.1:5432/gce_test
export REDIS_PASSWORD=<passwort>     # Tests nutzen Redis-DB 15
../scripts/test_backend.sh           # ruff, mypy --strict, pytest mit Coverage
```

Sind PostgreSQL oder Redis nicht erreichbar, werden die Integrationstests übersprungen, nicht als bestanden gewertet.

## Migrationen

```bash
alembic revision --autogenerate -m "beschreibung"
alembic upgrade head
alembic check          # muss "No new upgrade operations detected" melden
```

## Regeln

- Status von Material (`gameplay_files`) und Videos (`variants`) nur über `services/workflow.py` ändern.
- Keine Secrets im Code; alles über Umgebungsvariablen (`core/config.py`).
- Sicherheitsschalter bleiben standardmäßig aus: `AUTO_PUBLISH_ENABLED=false`, `PUBLISHING_MODE=mock`, `PAID_API_CALLS_ENABLED=false`.
