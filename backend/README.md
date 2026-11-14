# Backend

FastAPI-API, RQ-Worker und Datenmodell der Gaming Content Engine. Python 3.12+, Importwurzel ist dieser Ordner.

## Aufbau

| Ordner | Inhalt |
|---|---|
| `app/` | Einstiegspunkte: `main.py` (API), `worker.py` (Queue-Worker), `seed.py` (Basisdaten) |
| `api/` | HTTP-Router (aktuell: Health) |
| `core/` | Konfiguration, Logging, Enums, Statusabläufe (`states.py`) |
| `database/` | Engine/Session, Basisklassen, Alembic-Migrationen |
| `models/` | SQLAlchemy-Modelle aller 27 Tabellen, nach Bereich gruppiert |
| `services/` | Geschäftslogik: Statuswechsel (`workflow.py`), Queue, Health, Seed |
| `workflows/` | Queue-Jobs (ab Phase 4 die Agenten-Jobs) |
| `agents/` | Agenten (ab Phase 4) |
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
uvicorn app.main:app --reload
python -m app.worker        # in zweitem Terminal
```

API-Dokumentation (nur außerhalb von Production): http://127.0.0.1:8000/api/docs

## Endpunkte

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/health` | Prozess läuft (Liveness) |
| GET | `/api/health/ready` | PostgreSQL und Redis erreichbar; sonst HTTP 503 |

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
