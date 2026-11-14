# Projektstatus

**Stand:** 14.11.2026 · **Aktuelle Phase:** 4 abgeschlossen · **Nächste Phase:** 5 (Trend Research und Game Intelligence)

**Repository:** [axelander-star/gaming-content-engine](https://github.com/axelander-star/gaming-content-engine) (privat). Phasen werden ohne Zwischenfreigabe nacheinander umgesetzt; Phasen-PRs werden nach grüner CI gemergt (Anweisungen des Betreibers vom 14.11.2026).

## Phasenübersicht

| Phase | Inhalt | Status |
|---|---|---|
| 1 | Repository, Dokumentation, Architektur, Projektgrundlage | ✅ abgeschlossen |
| 2 | Docker, PostgreSQL, Redis, Backend | ✅ abgeschlossen |
| 3 | Anmeldung, Benutzerverwaltung, Dashboard-Grundgerüst | ✅ abgeschlossen |
| 4 | Master Agent und Agentenverwaltung | ✅ abgeschlossen |
| 5 | Trend Research und Game Intelligence | ⏳ offen |
| 6 | Material Scout und Rights Agent | ⏳ offen |
| 7 | Gameplay-Analyse und Videoproduktion | ⏳ offen |
| 8 | Creative Director, Hooks, Skripte | ⏳ offen |
| 9 | Lokalisierung, Voiceover, Untertitel | ⏳ offen |
| 10 | Quality Control und Duplikaterkennung | ⏳ offen |
| 11 | Publishing Strategy Agent | ⏳ offen |
| 12 | YouTube-Integration | ⏳ offen |
| 13 | TikTok, Instagram, Facebook | ⏳ offen |
| 14 | Analytics, Learning Agent, Budgetkontrolle | ⏳ offen |
| 15 | Monitoring, Sicherheit, Backups, Skalierung | ⏳ offen |

## Phase 4 – Bericht

### 1. Was wurde erstellt?

- **Agenten-Grundgerüst:** Basisklasse mit Protokoll (`agent_runs`), Entscheidungen mit Begründung (`agent_decisions`), Kostenfreigabe vor jedem kostenpflichtigen Aufruf und Kostenbuchung; Registry aller 18 Agenten mit Phase, Kostenart und Pipeline-Stufe
- **Master Orchestrator:** verteilt wartende Materialien und Videos an die zuständigen Agenten, setzt fehlgeschlagene Einträge mit Wartezeit (exponentiell) bis zu 3-mal zurück, beachtet das tägliche Produktionslimit und protokolliert jede Verteilung mit Begründung
- **Zentrale Gates** vor jedem Job und nochmals direkt vor der Ausführung: Not-Aus, Agent pausiert, Budgetstufe, Tageslimit, richtiger Status, gültige Rechte (Lizenz, Zeitraum, gesperrte Quelle), Qualitätsfreigabe vor dem Veröffentlichen, Kanal/Plattform pausiert, im Live-Modus Auto-Publish und autorisierter Kanal
- **Budget & Cost Agent:** Budgetstufen 50/70/85/95 %, Monatsbudget aus dem Dashboard, Benachrichtigung einmal pro Monat und Stufe; 0 € Budget sperrt kostenpflichtige Aufrufe
- **Fehlerbehandlung:** ein Agentenfehler stoppt den Worker nie; Lauf `failed`, Eintrag `FAILED` mit Schritt und Meldung; Budget-Ablehnung zählt als `skipped`
- **Zeitsteuerung:** neuer Dienst `scheduler` (Master alle 5 Min., Budget stündlich, bei Not-Aus nichts)
- **Agenten pausieren/fortsetzen** (neue Tabelle `agent_states`, Migration `cfe08a41f655`), im Audit-Log festgehalten
- **API** `/api/agents` (Status, Läufe, Entscheidungen, Budget, Pausieren, manueller Start) und **Dashboard-Seite „Agenten“** mit Echtdaten (Screenshot: `screenshots/phase4-agenten.png` im Projektordner)

### 2. Geänderte Dateien

- Neu: `backend/agents/{base,registry,master,budget_cost}.py`, `backend/services/{budget,gates,orchestrator,agent_control}.py`, `backend/api/agents.py`, `backend/app/scheduler.py`, Migration `20261114_cfe08a41f655_agent_states.py`, Tests `tests/integration/test_agents.py`, `test_agents_api.py`, `test_pipeline.py`, `frontend/dashboard/AgentsView.tsx`
- Geändert: `backend/models/control.py`, `models/__init__.py`, `core/config.py`, `app/main.py`, `app/worker.py`, `workflows/jobs.py`, `docker-compose.yml`, `.env.example`, `.github/workflows/ci.yml` (Worker im E2E-Lauf), `frontend/lib/{api,types,labels}.ts`, `frontend/app/(dashboard)/agenten/page.tsx`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, Dokumentation (`AGENTS.md`, `ARCHITECTURE.md`, `DEVELOPMENT_PLAN.md`, READMEs)

### 3. Durchgeführte Tests

- `scripts/test_backend.sh`: ruff, ruff format, mypy --strict, pytest mit Abdeckung gegen PostgreSQL 16 und Redis
- `alembic upgrade head` und `alembic check` auf frischer Datenbank
- Frontend: `npm run typecheck`, `npm run build`
- E2E (Playwright) gegen echtes Backend, echten Worker und Dashboard, inklusive manuellem Start des Master Orchestrators
- Scheduler-Probelauf gegen die lokale Entwicklungsumgebung (Master und Budget-Agent liefen über den Worker)
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 128 Backend-Tests bestanden, Abdeckung 96 %; ruff und mypy ohne Befund
- **Abnahme Phase 4:** Pipeline-Durchlauf mit Dummy-Agenten von `DISCOVERED` bis `READY_TO_PUBLISH` (jede Stufe genau einmal, in der richtigen Reihenfolge); pausierter Agent hält die Pipeline an und sie läuft nach dem Fortsetzen weiter; Not-Aus stoppt alles
- Gates einzeln getestet (Rechte abgelaufen/widerrufen, Qualität unter Mindestwert, Kanal pausiert, Live ohne Freigabe, Tageslimit, Budget)
- Idempotenz: doppeltes Einreihen ergibt einen Job; zweite Ausführung wird übersprungen
- 11 E2E-Schritte bestanden; Frontend-Build ohne Typfehler; 68 Projektprüfungen bestanden

### 5. Bestehende Fehler / Einschränkungen

- Nur Master und Budget-Agent sind echt umgesetzt; die übrigen 16 Agenten erscheinen als „Folgt in Phase X“ und ihre Stufen warten
- Läuft ein Agent sehr lange (z. B. Rendering), sperrt nur der feste Job-Schlüssel parallele Doppelarbeit; eine Zeilensperre pro Eintrag folgt bei Bedarf in Phase 7
- `max_parallel_render_jobs` wird erst mit dem Render-Worker in Phase 7 durchgesetzt
- Der Budget-Agent protokolliert seine stündliche Prüfung auch im Normalzustand (24 Einträge am Tag); bei Bedarf in Phase 14 verdichten

### 6. Nächster Schritt

Phase 5: Trend Research und Game Intelligence mit Mock-Adaptern für YouTube, Twitch und Steam, Trend-Scoring und Trendberichten. Echte API-Schlüssel werden dafür nicht benötigt, solange Mocks laufen.

## Phase 3 – Bericht

### 1. Was wurde erstellt?

- **Anmeldung:** Argon2id-Passwörter mit Richtlinie, signiertes Session-Token im HttpOnly-Cookie, CSRF-Schutz (Double-Submit), Login-Sperre nach 5 Fehlversuchen, Abmelden auf einem bzw. allen Geräten, sofortiger Widerruf bei Rollen- oder Passwortänderung
- **Rollen** `admin`, `operator`, `viewer`, serverseitig in jedem Endpunkt geprüft; der letzte Admin kann nicht entfernt werden; erster Admin per CLI `python -m app.create_admin` (kein Standardpasswort)
- **Steuerung:** Not-Aus (Operator darf auslösen, nur Admin lösen) und Auto-Publish-Schalter (nur Admin, nur wenn die Serverkonfiguration es erlaubt); der Worker startet auch bei Not-Aus aus dem Dashboard nicht
- **Betriebseinstellungen** aus Spezifikation Abschnitt 8: Monatsbudget, max. Produktions- und Renderjobs, Mindestqualität, Mindestabstand, Sprachen, Plattformen, KI-/TTS-Anbieter
- **Kanäle:** pausieren/fortsetzen und Sicherheitsgrenzen pro Kanal
- **Audit-Log** für Logins, Fehlversuche, Benutzer-, Kanal- und Einstellungsänderungen
- **Dashboard** (Next.js 16, TypeScript strict): Login, Navigation mit allen sieben Seiten aus der Spezifikation, Übersicht mit echten Kennzahlen und Systemstatus, vollständige Einstellungsseite, Not-Aus-Banner; die übrigen Seiten zeigen, welche Phase sie füllt
- **Docker:** Dashboard-Image (standalone, Non-Root), Compose-Dienst `frontend`, Caddy leitet alles außer `/api` ans Dashboard
- **CI** erweitert um Frontend-Typprüfung, Build, Dashboard-Image und einen E2E-Test gegen echtes Backend

### 2. Geänderte Dateien

Neu: `backend/api/{auth,users,settings,channels,overview,deps,schemas}.py`, `backend/core/security.py`, `backend/services/{controls,audit,rate_limit}.py`, `backend/app/create_admin.py`, Migration `user_session_version`, Tests `test_auth.py`, `test_settings_and_channels.py`, `test_security.py`; komplettes `frontend/` (App, Komponenten, Dashboard-Module, API-Client, E2E-Test, Dockerfile, README).
Geändert: `backend/app/{main,worker}.py`, `backend/core/config.py`, `backend/models/access.py`, `backend/pyproject.toml`, `docker-compose.yml`, `Caddyfile`, `.env.example`, `.github/workflows/ci.yml` (vorher `backend.yml`), README, CLAUDE.md, ARCHITECTURE, DEVELOPMENT_PLAN, SECURITY, PROJECT_STATUS.

### 3. Durchgeführte Tests

- Backend: `pytest` mit 89 Tests gegen echtes PostgreSQL 16 und Redis 7 (u. a. Cookie-Attribute, gleiche Antwort für unbekannte Konten, Login-Sperre, manipuliertes Token, `alg=none`, CSRF, Abmelden überall, Rollenrechte, letzter Admin, Not-Aus-Regeln, Auto-Publish-Doppelsperre, Validierung der Einstellungen und Kanalgrenzen, Audit-Einträge)
- Ruff, mypy (strict), Alembic `upgrade` und `check`
- Frontend: `tsc --noEmit`, `next build`
- E2E (Playwright, echter Browser gegen echtes Backend, auch mit dem Standalone-Build wie in der CI): Weiterleitung zum Login, falsches Passwort, Anmeldung, alle Seiten, Auto-Publish gesperrt, Not-Aus an und aus mit Banner, Abmelden
- `docker compose config`, `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 89 von 89 Backend-Tests, Abdeckung 96 %
- Ruff, mypy, Typprüfung und Build ohne Befund
- 8 von 8 E2E-Schritten
- Beim ersten E2E-Lauf fiel auf, dass das Not-Aus-Banner nach dem Lösen sichtbar blieb; behoben und als E2E-Schritt abgesichert

### 5. Bestehende Fehler / Einschränkungen

- Dashboard-Image und `docker compose up` des Gesamtsystems konnten lokal nicht gebaut werden (kein Docker-Daemon); die CI baut beide Images.
- Zwei-Faktor-Anmeldung ist noch nicht umgesetzt (geplant für Phase 15).
- Die Seiten Agenten, Videoproduktion, Publishing, Analytics und Kosten sind Grundgerüste; ihre Daten entstehen in den jeweiligen Phasen.

### 6. Nächster Schritt

Phase 4: Agenten-Basisklasse und Registry der 18 Agenten, Master Orchestrator mit Gate-Prüfungen (Not-Aus, Agent pausiert, Budget, Rechte, Qualität), Retry und Protokollierung in `agent_runs`/`agent_decisions`, Agenten-Seite im Dashboard mit Aktivieren/Pausieren.

## Phase 2 – Bericht

### 1. Was wurde erstellt?

- **FastAPI-Backend** (`backend/`): App-Factory, Health-Endpunkte `/api/health` und `/api/health/ready` (503 bei Ausfall von DB oder Redis), API-Doku nur außerhalb von Production
- **Konfiguration** (`core/config.py`): typisiert, sichere Standardwerte, `publishing_allowed` nur wenn Auto-Publish an, Modus `live` und kein Not-Aus; Production startet nicht mit Platzhalter-Secrets
- **Strukturierte JSON-Logs** mit Maskierung von Passwörtern, Tokens und Zugangsdaten in URLs
- **Datenmodell:** alle 27 Tabellen aus Spezifikation Abschnitt 10 als SQLAlchemy-Modelle, Alembic-Erstmigration; Lizenzrechte standardmäßig verweigert; Kanal-Höchstgrenze standardmäßig 0; Schutz gegen Doppelposts per eindeutigem Index
- **Statusabläufe** (`core/states.py`) für Material und Videos, durchgesetzt über `services/workflow.py` mit Audit-Log, Fehlerstatus und begrenztem Retry
- **Redis-Queue mit RQ:** drei Prioritäten, idempotentes Einreihen, Worker-Prozess, der bei aktivem Not-Aus nicht startet
- **Basisdaten:** 4 Plattformen und 8 Kanäle (DE/EN), alle pausiert, nicht verbunden, ohne Veröffentlichungsfreigabe
- **Docker:** Backend-Image (Python 3.12, Non-Root), Compose-Dienste `migrate` (Migration + Seed), `backend`, `worker`; Caddy leitet `/api` ans Backend
- **CI:** GitHub-Actions-Workflow mit PostgreSQL und Redis (Lint, Typen, Tests, Migrationsabgleich, Phase-1-Prüfung)

### 2. Geänderte Dateien

Neu: `backend/` (pyproject, Dockerfile, alembic.ini, app/, api/, core/, database/, models/, services/, workflows/, tests/, README.md), `.github/workflows/backend.yml`, `scripts/test_backend.sh`.
Geändert: `docker-compose.yml`, `infrastructure/caddy/Caddyfile`, `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_PLAN.md`, `docs/PROJECT_STATUS.md`.

### 3. Durchgeführte Tests

Gegen echtes PostgreSQL 16 und Redis 7 (lokal gestartet):

- `pytest`: 52 Tests (27 Unit, 25 Integration) – Konfiguration, Log-Maskierung, Statusabläufe, alle Tabellen vorhanden, Constraints (Enum, min/max, Doppelpost, Idempotenzschlüssel, Lizenzpflicht), Rückverfolgbarkeit Post → Lizenz, Workflow mit Audit/Fehler/Retry, Health-Endpunkte inkl. Redis-Ausfall, Queue und Worker
- `ruff check`, `ruff format --check`, `mypy --strict`
- Alembic: `upgrade head`, `downgrade base`, erneutes `upgrade`, `alembic check`
- Seed zweimal ausgeführt (idempotent)
- Smoke-Test: uvicorn und Worker als echte Prozesse, Job über Redis ausgeführt; Worker mit `EMERGENCY_STOP=true` beendet sich mit Exit-Code 1
- `docker compose config` mit allen Profilen, `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 52 von 52 Tests bestanden, Testabdeckung 97 %
- Ruff und mypy (strict) ohne Befund
- Migration hin und zurück fehlerfrei, Modelle und Migration deckungsgleich
- Smoke-Test und Not-Aus-Test erfolgreich
- Compose-Datei gültig, Phase-1-Prüfung 68/68

### 5. Bestehende Fehler / Einschränkungen

- Docker-Image und `docker compose up` konnten nicht gebaut bzw. gestartet werden, weil in der Entwicklungsumgebung kein Docker-Daemon läuft. Code, Migration und Prozesse wurden ohne Container gegen echte Dienste getestet. Der CI-Job `docker-build` hat das Image auf GitHub erfolgreich gebaut und gestartet (PR #1).
- Caddyfile weiterhin nicht mit `caddy validate` geprüft (gleicher Grund).
- Hinweis aus Abhängigkeiten: Starlette meldet eine Deprecation für den Testclient mit httpx (nur Tests betroffen).
- Noch keine Anmeldung: Die API hat bisher nur Health-Endpunkte; alles Weitere kommt mit Phase 3 hinter einer Anmeldung.

### 6. Nächster Schritt

Phase 3: Benutzer und Rollen, sichere Anmeldung, Audit-Log für Logins und Einstellungen, Next.js-Dashboard mit Login, Navigation und Einstellungsseite (Not-Aus, Auto-Publish standardmäßig aus).

## Phase 1 – Bericht

### 1. Was wurde erstellt?

- Projektstruktur gemäß Spezifikation Abschnitt 18 (backend/, frontend/, infrastructure/, scripts/, docs/)
- PROJECT_SPEC.md (vollständige Spezifikation, Abschnitte 1–20) und CLAUDE.md (Projektregeln)
- README.md, .gitignore, .env.example mit sicheren Standardwerten
- docker-compose.yml: PostgreSQL 16, Redis 7 (Kern), Caddy, n8n, Uptime Kuma (als optionale Profile); Backend/Frontend als kommentierte Platzhalter für Phase 2/3
- Caddyfile-Grundgerüst mit Sicherheitsheadern
- docs/: ARCHITECTURE, DEVELOPMENT_PLAN, SECURITY, PROJECT_STATUS, API_INTEGRATIONS, AGENTS
- scripts/verify_phase1.py und verify_phase1.sh (automatische Phase-1-Prüfung)

### 2. Geänderte Dateien

Alle Dateien neu angelegt (siehe Liste oben); leere Ordner enthalten `.gitkeep`.

### 3. Durchgeführte Tests

- `scripts/verify_phase1.sh`: Struktur, Compose-Dienste, lokale Port-Bindung, sichere Standardwerte, keine Secrets, `.gitignore`, Markdown-Links, Vollständigkeit der Spezifikation
- `docker compose config` mit allen Profilen
- Negativtest: Prüfskript erkennt fehlende Datei, `AUTO_PUBLISH_ENABLED=true` und defekten Link (Exit-Code 1)

### 4. Erfolgreiche Tests

- 68 von 68 Einzelprüfungen bestanden
- `docker compose config` gültig (alle Profile)
- Negativtest schlägt erwartungsgemäß fehl

### 5. Bestehende Fehler / Einschränkungen

- Container wurden in Phase 1 nicht gestartet (in der Entwicklungsumgebung lief kein Docker-Daemon). Der erste echte Start erfolgt in Phase 2.
- Caddyfile wurde nicht mit `caddy validate` geprüft (gleicher Grund).
- Noch kein GitHub-Repository verbunden.

### 6. Nächster Schritt

Phase 2: FastAPI-Backend, Datenmodell mit Alembic-Migration, Statusmaschine, Redis-Queue, Health-Endpunkte, Backend-Container.

## Entscheidungen

| Datum | Entscheidung | Begründung |
|---|---|---|
| 14.11.2026 | Zwei getrennte Statusmaschinen (Material, Video) | `ANALYZED` kommt in der Spezifikation doppelt vor; pro Entität eindeutig |
| 14.11.2026 | API und Worker aus einem Python-Paket | gemeinsame Modelle, passt auf CX33 |
| 14.11.2026 | Adapter-Muster mit Mock als Standard für alle externen Dienste | keine Kosten, keine echten Veröffentlichungen in der Entwicklung |
| 14.11.2026 | n8n optional, nur Zeitsteuerung/Benachrichtigung | Geschäftslogik bleibt testbar im Code |
| 14.11.2026 | Ergänzende Status `FAILED`, `RIGHTS_REJECTED`, `QUALITY_REJECTED` | Fehlerdokumentation und erneute Verarbeitung (Spezifikation Abschnitt 16) |
| 14.11.2026 | Queue-Bibliothek RQ statt arq | synchrone, CPU-lastige Jobs (FFmpeg); aktiv gepflegt |
| 14.11.2026 | Enums als VARCHAR + CHECK statt PostgreSQL-ENUM | einfachere Migrationen, trotzdem Validierung in der DB |
| 14.11.2026 | Neue Kanäle: pausiert, `max_posts_per_day = 0` | nichts kann versehentlich veröffentlicht werden, bevor der Betreiber den Kanal einrichtet |
| 14.11.2026 | Spalte `metrics.measure_window` statt `window` | `window` ist ein reserviertes SQL-Wort |
| 14.11.2026 | Session im HttpOnly-Cookie + CSRF-Double-Submit statt Token im Browser-Speicher | Token für Skripte unerreichbar (XSS), Dashboard und API auf gleicher Origin |
| 14.11.2026 | Steuerung in zwei Ebenen (Serverkonfiguration als Obergrenze, Dashboard darunter) | Auto-Publish kann nicht allein per Dashboard-Klick scharf geschaltet werden |
| 14.11.2026 | Not-Aus: Operator darf auslösen, nur Admin lösen | Im Zweifel schnell stoppen, Wiederanlauf bewusst |
| 14.11.2026 | Zwei-Faktor-Anmeldung auf Phase 15 verschoben | Bis dahin ein Betreiber; Härtung gebündelt in Phase 15 |
| 14.11.2026 | Gates werden beim Verteilen **und** direkt vor der Ausführung geprüft | Lage kann sich ändern, während ein Job wartet (Not-Aus, Pause, Budget) |
| 14.11.2026 | Wiederholungen steuert der Master, nicht die Queue | Wartezeit und Höchstzahl sind im Dashboard sichtbar und protokolliert |
| 14.11.2026 | Budget-Gate für kostenpflichtige Agenten nur, wenn kostenpflichtige Aufrufe erlaubt sind | Mit `PAID_API_CALLS_ENABLED=false` laufen diese Agenten gegen Mocks; jeder echte Aufruf wird trotzdem einzeln geprüft |
| 14.11.2026 | Eigener Dienst `scheduler` statt n8n für den Master-Takt | Kern-Ablauf ohne Zusatzdienst testbar; n8n bleibt optional |

## Offene Punkte

- `docker compose up` des Gesamtsystems auf einem echten Docker-Host bestätigen (Image-Build ist in der CI grün)
- Entwickler-Apps bei Google, TikTok und Meta anlegen (Betreiber); Audits können Wochen dauern
- LLM- und TTS-Anbieter nach aktueller Preisprüfung auswählen – vor Phase 8/9
- Zwei-Faktor-Anmeldung für Admins – Phase 15
- Alle ⚠️-Angaben in API_INTEGRATIONS.md gegen aktuelle Anbieterdokumentation prüfen
- Image-Versionen (n8n `stable`, Uptime Kuma `1`) vor Produktivbetrieb fest pinnen – Phase 15
