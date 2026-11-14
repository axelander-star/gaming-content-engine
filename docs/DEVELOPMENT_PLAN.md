# Entwicklungsplan

Die Engine wird in 15 Phasen gebaut (Spezifikation Abschnitt 18). Jede Phase endet mit Tests, Fehlerbehebung, aktualisierter Dokumentation, aktualisierter [PROJECT_STATUS.md](PROJECT_STATUS.md) und dem Bericht in sechs Punkten (Abschnitt 19). Die nächste Phase beginnt erst nach Prüfung der aktuellen.

**Durchgängige Regeln:** Mock-Adapter als Standard, keine echten Veröffentlichungen, keine kostenpflichtigen Aufrufe ohne Freigabe, Tests für jede wichtige Funktion.

---

### Phase 1 – Repository, Dokumentation, Architektur ✅

- Projektstruktur, PROJECT_SPEC.md, CLAUDE.md, README, .gitignore, .env.example
- docker-compose-Grundgerüst (PostgreSQL, Redis, optional Caddy, n8n, Uptime Kuma)
- Architektur, Entwicklungsplan, Sicherheit, API-Integrationen, Agenten, Status

**Abnahme:** Struktur vollständig, Compose-Datei valide, keine Secrets im Repo (`scripts/verify_phase1.sh`).

### Phase 2 – Docker, PostgreSQL, Redis, Backend ✅

- FastAPI-Projekt (`backend/`) mit Python 3.12, `pyproject.toml`, Ruff, mypy (strict), pytest, GitHub-Actions-CI
- Konfiguration über Pydantic Settings (sichere Standardwerte, Pflichtfelder)
- SQLAlchemy-2.x-Modelle für alle Tabellen aus Abschnitt 10, Alembic-Erstmigration
- Statusmaschine mit erlaubten Übergängen als Code + Tests
- Redis-Anbindung, Job-Queue mit RQ (idempotente Job-IDs), Worker-Prozess
- Health-Endpunkte (`/api/health`, `/api/health/ready`), strukturierte JSON-Logs mit Secret-Maskierung
- Backend-, Worker- und Migrations-Container im Compose, Caddy-Route `/api`
- Basisdaten: 4 Plattformen, 8 Kanäle (DE/EN), alle pausiert und ohne Veröffentlichungsfreigabe

**Abnahme:** `docker compose up` startet alles healthy; Migration läuft; Tests für Modelle, Statusübergänge und Health grün.

### Phase 3 – Anmeldung, Benutzerverwaltung, Dashboard-Grundgerüst ✅

- Benutzer, Rollen (`admin`, `operator`, `viewer`), Passwort-Hashing (Argon2id), signiertes Session-Token im HttpOnly-Cookie, CSRF-Schutz, Login-Sperre
- Audit-Log für Logins, Benutzer-, Kanal- und Einstellungsänderungen
- Next.js-App (App Router, TypeScript strict) mit Login und Navigation: Übersicht, Agenten, Videoproduktion, Publishing, Analytics, Einstellungen, Kosten
- Einstellungen-Seite mit Not-Aus und Auto-Publish-Schalter (Standard aus), Budget/Limits, Kanal-Pausen und -Grenzen, Benutzerverwaltung

**Abnahme:** Login/Logout, Rollenprüfung serverseitig getestet; Frontend baut ohne Typfehler; E2E-Smoke-Test (Playwright).

### Phase 4 – Master Agent und Agentenverwaltung ✅

- Basisklasse `Agent` (Name, Aufgabe, Status, `run()`, Kostenerfassung, Protokollierung)
- Registry aller 18 Agenten; Aktivieren/Pausieren je Agent
- Master Orchestrator: Job-Verteilung, Gate-Prüfungen, Retry/Backoff, Fehlerstatus
- `agent_runs`, `agent_decisions` befüllt; Dashboard-Seite „Agenten" mit Echtdaten

**Abnahme:** Pipeline-Durchlauf mit Dummy-Agenten bis `READY_TO_PUBLISH`; pausierter Agent blockiert; Not-Aus stoppt alles.

### Phase 5 – Trend Research und Game Intelligence ✅

- Adapter: YouTube Data API, Twitch Helix, Steam (jeweils Mock + Live)
- Trend-Scoring (Wachstum, Volumen, Sprache, eigene Performance), Trendberichte
- Game Intelligence: Spielprofile, Zielgruppen, Videoideen

**Abnahme:** Trenderkennung aus Mock-Daten reproduzierbar getestet; Live-Adapter nur mit freigegebenem Schlüssel und Quota-Begrenzung.

### Phase 6 – Material Scout und Rights Agent ✅

- Verwaltung von Creatorn, Quellen, Lizenzen inkl. Dokument-Upload als Nachweis
- Rechteprüfung gegen alle Kriterien aus Abschnitt 5; Ablaufüberwachung; Sperrliste
- Publisher-Policies als gepflegte Regeln (z. B. kein pauschaler Freibrief für GTA 6)

**Abnahme:** Material ohne vollständige Lizenz erreicht nie `RIGHTS_APPROVED` (Tests für jedes Kriterium).

### Phase 7 – Gameplay-Analyse und Videoproduktion ✅

- Upload, technische Prüfung (ffprobe), R2-Speicher (Mock: lokal)
- Szenenerkennung (PySceneDetect), Bewertung (Bewegung, Audiopegel, Schnittdichte via OpenCV)
- Schnitt, 9:16-Reframing, Export MP4/H.264/AAC 1080×1920
- Kapazitätsmessung auf Zielhardware

**Abnahme:** Testvideo (selbst erzeugt, lizenzfrei) wird zu Clip mit korrekten technischen Parametern verarbeitet.

### Phase 8 – Creative Director, Hooks und Skripte

- Formatkatalog, Hook-Strukturen, Skripterzeugung
- LLM-Adapter (Mock + Live, budgetgeprüft); Variantenlogik A–D mit echtem Unterschied

### Phase 9 – Lokalisierung, Voiceover, Untertitel

- Getrennte DE/EN-Fassungen mit eigener Hook-/Titellogik
- TTS-Adapter (nur kommerziell lizenzierte Stimmen), lokale Option prüfen
- Untertitel (SRT/VTT + eingebrannt), Hochformat-Positionierung

### Phase 10 – Quality Control und Duplikaterkennung

- Technische Prüfungen (Auflösung, Codec, Lautheit, Dauer, Dateigröße je Plattform)
- Rechte-Gate erneut, Untertitelprüfung, Hash + perzeptueller Fingerprint

**Abnahme:** Fehlerhafte Exporte und Duplikate werden zuverlässig blockiert.

### Phase 11 – Publishing Strategy Agent

- Kanal-Baselines je Messzeitpunkt, gedämpfte Mengenanpassung, Grenzen, Mindestabstand
- `strategy_versions` mit Rollback; Entscheidungsbegründung im Dashboard

**Abnahme:** Simulationstests mit synthetischen Kanalverläufen (inkl. Einzel-Viral, Qualitätsabfall, Datenmangel).

### Phase 12 – YouTube-Integration

- OAuth 2.0, verschlüsselte Tokens, Upload über YouTube Data API, Quota-Verwaltung
- Autorisierungsprüfung je Kanal; Tests nur mit Mock bzw. privatem Testkanal nach Freigabe

### Phase 13 – TikTok, Instagram, Facebook

- TikTok Content Posting API (Audit-Status beachten), Instagram Graph API (Reels), Facebook Graph API (Reels)
- Ohne Freigabe bleibt das Video `READY_TO_PUBLISH`

### Phase 14 – Analytics, Learning Agent, Budgetkontrolle

- Metrikabruf je Plattform und Messzeitpunkt, Snapshots, Berichte
- Learning Agent mit Mindestdatenmenge und kontrollierten Experimenten
- Budget-Agent vollständig: Stufen 50/70/85/95 %, Kosten pro Video und pro 1.000 Aufrufe

### Phase 15 – Monitoring, Sicherheit, Backups, Skalierung

- Uptime Kuma, Fehlerüberwachung, Alarme; tägliche verschlüsselte PostgreSQL-Backups mit Restore-Test
- Sicherheitsreview, Härtung des Servers, Deployment-Skript
- Lasttest und Skalierungskriterien

---

## Abschlusskriterium des Gesamtprojekts

Der End-to-End-Ablauf aus Spezifikation Abschnitt 20 (Trend → … → angepasste Strategie, alles im Dashboard sichtbar) ist erfolgreich getestet.
