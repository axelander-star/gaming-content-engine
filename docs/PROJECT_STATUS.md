# Projektstatus

**Stand:** 14.11.2026 · **Aktuelle Phase:** 7 abgeschlossen · **Nächste Phase:** 8 (Creative Director, Hooks und Skripte)

**Repository:** [axelander-star/gaming-content-engine](https://github.com/axelander-star/gaming-content-engine) (privat). Phasen werden ohne Zwischenfreigabe nacheinander umgesetzt; Phasen-PRs werden nach grüner CI gemergt (Anweisungen des Betreibers vom 14.11.2026).

## Phasenübersicht

| Phase | Inhalt | Status |
|---|---|---|
| 1 | Repository, Dokumentation, Architektur, Projektgrundlage | ✅ abgeschlossen |
| 2 | Docker, PostgreSQL, Redis, Backend | ✅ abgeschlossen |
| 3 | Anmeldung, Benutzerverwaltung, Dashboard-Grundgerüst | ✅ abgeschlossen |
| 4 | Master Agent und Agentenverwaltung | ✅ abgeschlossen |
| 5 | Trend Research und Game Intelligence | ✅ abgeschlossen |
| 6 | Material Scout und Rights Agent | ✅ abgeschlossen |
| 7 | Gameplay-Analyse und Videoproduktion | ✅ abgeschlossen |
| 8 | Creative Director, Hooks, Skripte | ⏳ offen |
| 9 | Lokalisierung, Voiceover, Untertitel | ⏳ offen |
| 10 | Quality Control und Duplikaterkennung | ⏳ offen |
| 11 | Publishing Strategy Agent | ⏳ offen |
| 12 | YouTube-Integration | ⏳ offen |
| 13 | TikTok, Instagram, Facebook | ⏳ offen |
| 14 | Analytics, Learning Agent, Budgetkontrolle | ⏳ offen |
| 15 | Monitoring, Sicherheit, Backups, Skalierung | ⏳ offen |

## Einschub: Live-Anbindung YouTube und Twitch (14.11.2026)

Der Betreiber hat einen YouTube-API-Schlüssel und eine Twitch-App angelegt. Vorbereitet wurde: Zugangsdaten nur über Umgebungsvariablen (Fehler behoben: die Variablen standen in `.env.example` doppelt, eine leere zweite Zeile hätte den Wert überschrieben; leere Werte zählen jetzt als „nicht gesetzt“), Verbindungsstatus mit Fehlern und Quote im Dashboard, Verbindungstest per Knopf (Admin), Wiederverwendung des Twitch-Tokens, Abbruch bei Rate Limit, Trendverlauf je Spiel. Details: `API_INTEGRATIONS.md`, Abschnitt „Live-Anbindung einrichten“. Verbindungstest nach Hinterlegung der Schlüssel (14.11.2026): Die Twitch-Zugangsdaten sind gültig (Token wird ausgestellt). Der YouTube-Schlüssel wird von Google als ungültig abgelehnt und muss neu erstellt werden. Steam ist aus der Entwicklungsumgebung nicht erreichbar und wird auf dem Server geprüft. Die versehentlich eingecheckte `.env` wurde aus dem Repository entfernt; die Schlüssel daraus müssen rotiert werden.

## Phase 7 – Bericht

### 1. Was wurde erstellt?

- **Gameplay-Upload** (`POST /api/materials/upload`, Dashboard-Seite „Videoproduktion“): MP4, MOV oder MKV bis 4 GiB, Datei wird gestreamt, mit ffprobe geprüft (Format, Länge 10 s bis 4 h, mindestens 720p, Bildrate) und erst danach inhaltsadressiert gespeichert. Doppelte Dateien werden abgelehnt (409). Danach läuft dieselbe Kette wie bei registriertem Material: Material Scout, Rechteprüfung, erst dann Analyse
- **Gameplay Analysis Agent** (Agent 6): misst je Sekunde Bewegung und deren Bildposition (OpenCV), Lautstärke (RMS) und Schnitte (PySceneDetect), bewertet alle Fenster in Zielclip-Länge (Standard 30 s) und wählt die besten, sich nicht überschneidenden Szenen (Mindestwert 0,35, höchstens 3 je Material). Start und Ende rücken an einen nahen Schnitt. Die besten 10 Szenen werden mit Einzelwerten und Schlagworten gespeichert, für jede gewählte Szene entstehen ein Clip und eine Variante je Sprache (`SCENE_SELECTED`)
- **Clip Production Agent** (Agent 7): rendert jeden Clip einmal (die zweite Sprachfassung nutzt dieselbe Datei): Schnitt, 0,3 s Ein- und Ausblendung, 9:16-Ausschnitt um die Action oder bei weit verteilter Action das ganze Bild auf unscharfem Hintergrund, H.264 High/AAC, 1080×1920 (bei 720p-Quellen 720×1280, kein Hochskalieren), höchstens 60 fps, `faststart`. Das Ergebnis wird erneut mit ffprobe geprüft; Abweichungen führen zu einem Fehler statt zu einem fehlerhaften Clip. Pro Sekunde wird ein Bild-Fingerabdruck (dHash) für die Duplikaterkennung in Phase 10 gespeichert
- **Renderslots:** höchstens `max_parallel_render_jobs` (Betreiber-Einstellung) gleichzeitig; ist alles belegt, wird der Lauf übersprungen und später erneut verteilt
- **Dauerhafte Fehler** (Datei unlesbar, technische Prüfung nicht bestanden) werden ohne automatische Wiederholung als Fehler markiert
- **API:** `/api/production/clips`, `/api/materials/{id}/scenes`, `/api/clips/{id}/file` (Vorschau), `/api/production/capacity` (gemessene Kapazität der letzten 7 Tage)
- **Dashboard „Videoproduktion“:** Kapazitätskacheln, Upload, Clip-Liste mit Szenenbewertung, Schlagworten, technischen Werten, Renderzeit, Status je Sprachfassung und Videovorschau (Screenshot: `screenshots/phase7-produktion.png`)

**Kapazitätsmessung** (4 vCPU wie CX33, Standard-Einstellungen `medium`/CRF 20, 30-s-Clip aus synthetischem Testvideo):

| Quelle | Bildaufbau | Ausgabe | Renderzeit | Echtzeitfaktor | Clips/Stunde je Slot |
|---|---|---|---|---|---|
| 720p | Ausschnitt | 720×1280 | 7,0 s | 4,3× | ca. 510 |
| 720p | unscharfer Hintergrund | 720×1280 | 15,3 s | 2,0× | ca. 235 |
| 1080p | Ausschnitt | 1080×1920 | 12,1 s | 2,5× | ca. 300 |
| 1080p | unscharfer Hintergrund | 1080×1920 | 27,5 s | 1,1× | ca. 130 |

Echtes Gameplay ist detailreicher als das Testbild und rendert langsamer; als vorsichtige Planungsgröße gilt ein Drittel dieser Werte. Die Analyse eines Materials kommt hinzu (ungefähr ein Zehntel der Materiallänge). Das Dashboard zeigt künftig die auf dem Server tatsächlich gemessenen Werte; der Publishing Strategy Agent (Phase 11) plant mit ihnen.

### 2. Geänderte Dateien

- Neu: `backend/services/{media,analysis,render}.py`, `backend/agents/{gameplay_analysis,clip_production}.py`, `backend/api/production.py`, Migration `20261114_dc0f8da24d55_clip_production.py`, `tests/integration/test_production.py`, `frontend/dashboard/ProductionView.tsx`
- Geändert: `backend/agents/{base,registry}.py`, `services/{orchestrator,storage}.py`, `models/production.py`, `api/rights.py`, `app/main.py`, `core/config.py`, `pyproject.toml` (numpy, OpenCV, PySceneDetect), `Dockerfile` (FFmpeg), CI (FFmpeg), `tests/integration/test_agents.py`, `frontend/app/(dashboard)/produktion/page.tsx`, `frontend/lib/{api,types}.ts`, `frontend/next.config.ts` (Upload-Grenze des Entwicklungs-Proxys), `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, Dokumentation

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest), Migration und `alembic check`
- Mit selbst erzeugten, lizenzfreien Testvideos (FFmpeg-Testbild und Rauschen): ffprobe-Prüfung und Ablehnungsgründe, Szenenerkennung findet den lauten Action-Teil, Schnitt-Ausrichtung, Ausschnitt und unscharfer Hintergrund, Quelle ohne Ton, Prüfung der technischen Werte des fertigen Clips, Renderslots, Wiederverwendung für die zweite Sprache, Upload mit Ablehnung falscher Dateien und Duplikate, Produktions-API und Kapazität
- Frontend `typecheck` und `build`; E2E mit echtem Worker: Video erzeugen, im Dashboard hochladen, Master startet Scout, Rechteprüfung, Analyse und Rendering, Clip erscheint mit 720×1280 und spielt in der Vorschau
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 208 Backend-Tests bestanden; ruff, mypy und `alembic check` ohne Befund
- **Abnahme Phase 7:** Das selbst erzeugte Testvideo wird zu einem Clip mit korrekten technischen Parametern verarbeitet (9:16, H.264/AAC, erwartete Auflösung, Länge und Bildrate, per ffprobe geprüft)
- 15 E2E-Schritte bestanden

### 5. Bestehende Fehler / Einschränkungen

- Humor und Spielinhalte (z. B. ein Sieg) sind aus Bewegung, Lautstärke und Schnitten nicht erkennbar; dafür wäre ein Bildmodell nötig (kostenpflichtig, nur mit Freigabe)
- Material und Clips liegen lokal im Volume `media_data`. R2 braucht Zugangsdaten des Betreibers und kommt, sobald sie hinterlegt sind; bis dahin sind die Dateien nicht im Backup (Phase 15)
- Neue Varianten starten auf dem ersten Kanal ihrer Sprache; die Verteilung auf Kanäle übernimmt der Publishing Strategy Agent (Phase 11)
- Kapazitätswerte stammen aus einem synthetischen Testvideo, nicht vom Zielserver; die echte Messung entsteht automatisch im Betrieb

### 6. Nächster Schritt

Phase 8: Creative Director, Hooks und Skripte. Dafür wird ein Sprachmodell gebraucht; vor dem ersten kostenpflichtigen Aufruf frage ich nach Anbieter und Budget. Bis dahin arbeite ich mit regelbasierten Vorlagen und Mock.

## Phase 6 – Bericht

### 1. Was wurde erstellt?

- **Rechteprüfung mit 12 Kriterien** (`services/rights.py`): Lizenzstatus, geprüfter Nachweis, dokumentierte Herkunft ohne Sperre, kommerzielle Nutzung, Bearbeitung, Kurzvideos, alle Plattformen, Deutsch und Englisch, Gültigkeit, Monetarisierung, Musik/Bestandteile, Publisher-Richtlinie. Jedes Kriterium ist „erfüllt“, „nicht erlaubt“ oder „Nachweis fehlt“; freigegeben wird nur, wenn alle 12 erfüllt sind (deny by default). Die Gates nutzen dieselbe Prüfung vor jedem späteren Produktionsschritt
- **Material Scout:** dokumentiert Herkunft und Spiel je Material, meldet fehlende Nachweise und übergibt an die Rechteprüfung; täglich Bericht, für welche Trend-Spiele lizenziertes Material fehlt. Lädt oder zeichnet nichts selbst auf
- **Rights & License Agent:** prüft jedes Material, speichert das vollständige Ergebnis (`rights_checks`) und begründet jede Ablehnung; täglich Ablaufüberwachung (abgelaufene Lizenzen sperren, 14 Tage vorher warnen, Material neu prüfen)
- **Automatische Neuprüfung**, sobald sich Nachweise ändern: Lizenz bearbeitet, freigegeben oder widerrufen, Quelle oder Creator gesperrt, Richtlinie geändert
- **Nachweis-Upload:** PDF/PNG/JPEG bis 10 MB, Inhalt muss zum Typ passen, versioniert und unveränderlich (SHA-256), lokal im Volume `media_data` bis R2 kommt. Freigabe einer Lizenz nur durch einen Admin und nur mit Nachweis
- **Publisher-Richtlinien** je Spiel (erlaubt, nur mit Erlaubnis, untersagt). Für **GTA VI** ist „nur mit ausdrücklicher Erlaubnis des Rechteinhabers“ vorbelegt
- **API** für Creator, Quellen, Lizenzen, Nachweise, Spiele, Richtlinien und Material, alles im Audit-Log; **Dashboard-Seite „Rechte“** mit Material und aufklappbarer Prüfung aller Kriterien, Lizenzbearbeitung mit Upload und Freigabe, Quellen/Creator mit Sperren, Richtlinien (Screenshot: `screenshots/phase6-rechte.png`)

### 2. Geänderte Dateien

- Neu: `backend/services/{rights,storage}.py`, `backend/agents/{material_scout,rights_license}.py`, `backend/api/rights.py`, Migration `20261114_ed4c879d1ea9_rights_management.py`, `tests/integration/test_rights.py`, `frontend/dashboard/RightsView.tsx`, `frontend/app/(dashboard)/rechte/page.tsx`
- Geändert: `backend/models/rights.py`, `models/__init__.py`, `core/{enums,config}.py`, `services/{gates,orchestrator,seed}.py`, `agents/registry.py`, `api/agents.py`, `app/{main,scheduler}.py`, `pyproject.toml` (python-multipart), `Dockerfile`, `docker-compose.yml` (Volume `media_data`), `.env.example`, Tests (`factories.py`, `test_agents.py`, `test_pipeline.py`, `test_database.py`), `frontend/components/AppShell.tsx`, `frontend/lib/{api,types}.ts`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, Dokumentation

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest mit Abdeckung), Migration und `alembic check`
- Für **jedes Kriterium** eigene Fälle (23 Varianten, z. B. Lizenz offen/widerrufen, Nachweis fehlt/ungeprüft, Creator gesperrt, eine Plattform fehlt, abgelaufen, Richtlinie fehlt/untersagt/ohne Erlaubnis), jeweils durch Material Scout und Rights Agent über den Orchestrator
- Ablaufüberwachung, Materialbedarf, Upload-Prüfung, Pfadschutz, Rollen, Neuprüfung nach Sperre und Richtlinienänderung über die API
- Frontend `typecheck` und `build`; E2E mit echtem Worker: Creator, Quelle, Spiel und Richtlinie anlegen, Lizenz bearbeiten, PDF hochladen, freigeben, Material registrieren, Master startet Scout und Rights Agent, Material wird mit 12 erfüllten Kriterien freigegeben
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 185 Backend-Tests bestanden, Abdeckung 96 % (`services/rights.py` und `services/storage.py` 100 %); ruff und mypy ohne Befund
- **Abnahme Phase 6:** Material ohne vollständige Lizenz erreicht nie `RIGHTS_APPROVED`. Jeder der 23 Einzelfälle endet in `RIGHTS_REJECTED` mit genau dem verletzten Kriterium; nur vollständige Nachweise führen zur Freigabe
- 13 E2E-Schritte bestanden

### 5. Bestehende Fehler / Einschränkungen

- Material wird in Phase 6 nur registriert (Speicherort und SHA-256); Datei-Upload und technische Prüfung (ffprobe) folgen in Phase 7
- Nachweise liegen bis Phase 7 im lokalen Volume statt in R2; sie sind deshalb noch nicht im Backup enthalten (Phase 15)
- Die Richtlinie für GTA VI ist eine vorsichtige Voreinstellung, keine Rechtsberatung. Richtlinien weiterer Spiele muss der Betreiber pflegen; ohne Richtlinie wird nichts freigegeben
- Keine Virenprüfung hochgeladener Dokumente (nur Typ- und Inhaltsprüfung); Admin öffnet Nachweise über den Download

### 6. Nächster Schritt

Phase 7: Gameplay-Analyse und Videoproduktion (Upload und ffprobe-Prüfung, Szenenerkennung, Schnitt, 9:16-Reframing, Export MP4/H.264/AAC).

## Phase 5 – Bericht

### 1. Was wurde erstellt?

- **Trendquellen** für Twitch, Steam und YouTube mit gemeinsamer Schnittstelle. Standard sind Testdaten (zehn erfundene Spiele, reproduzierbar je Datum, kein Netzwerkzugriff). Live-Adapter nutzen nur offizielle Endpunkte, laufen nur mit `TREND_SOURCES_MODE=live` und eigenen Schlüsseln und zählen jeden Aufruf vorab gegen eine Tagesquote in Redis
- **Trend Research Agent:** erkennt neue Spiele, bewertet jedes Spiel je Sprache (Reichweite, Wachstum, Sprachpassung, eigene Performance, Neuheit), sortiert nach Zielgruppe und schreibt pro Sprache einen Trendbericht; Testdaten sind gekennzeichnet
- **Game Intelligence Agent:** Spielprofile mit Zielgruppe, Spielmodi, vier Videoideen auf Deutsch und Englisch (aus den Formaten der Spezifikation), Kanalperformance je Sprache und Gesamtbewertung; regelbasiert, ohne Kosten
- **Eigene Performance** fließt automatisch ein, sobald echte Videos Kennzahlen haben (Mock-Posts zählen nie)
- **Zeitsteuerung:** Trend Research alle 6 Stunden, Game Intelligence täglich; beide auch manuell auf der Agentenseite startbar
- **API** `/api/trends`, `/api/trends/report`, `/api/games` und **„Aktuelle Trends“ auf der Übersicht** mit Sprachumschaltung, Wachstum, Zielgruppe und aufklappbarem Spielprofil; dazu die Kosten des Monats als Kennzahl (Screenshot: `screenshots/phase5-trends.png`)

### 2. Geänderte Dateien

- Neu: `backend/services/sources/{__init__,base,mock,live}.py`, `backend/services/{trends,game_intel,quota}.py`, `backend/core/catalog.py`, `backend/agents/{trend_research,game_intelligence}.py`, `backend/api/trends.py`, Migration `20261114_8480860b980d_trend_research.py`, `tests/integration/test_trends.py`, `frontend/dashboard/TrendsPanel.tsx`
- Geändert: `backend/models/trends.py`, `models/__init__.py`, `core/config.py`, `agents/registry.py`, `api/agents.py`, `app/main.py`, `app/scheduler.py`, `pyproject.toml` (httpx), `.env.example`, `frontend/dashboard/OverviewView.tsx`, `frontend/lib/{api,types}.ts`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, Dokumentation

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest mit Abdeckung), Alembic-Migration und `alembic check`
- Live-Adapter gegen simulierte HTTP-Antworten (Twitch, Steam, YouTube), Quotengrenze in Redis
- Frontend `typecheck` und `build`, E2E mit echtem Worker: Trend Research und Game Intelligence starten, Trends und Spielprofil auf der Übersicht prüfen
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 141 Backend-Tests bestanden, Abdeckung 96 %; ruff und mypy ohne Befund
- **Abnahme Phase 5:** Trenderkennung aus Testdaten reproduzierbar (zwei Läufe am selben Tag ergeben dieselben Scores, keine doppelten Spiele); Live-Adapter laufen nur mit Schlüssel und brechen an der Quotengrenze ab; der YouTube-Schlüssel erscheint nie in Fehlermeldungen
- 12 E2E-Schritte bestanden; 68 Projektprüfungen bestanden

### 5. Bestehende Fehler / Einschränkungen

- Live-Trendquellen sind gebaut, aber nicht eingeschaltet: Dafür braucht es eigene Schlüssel (YouTube API-Key, Twitch Client-ID/Secret) und die Prüfung der ⚠️-Punkte in `API_INTEGRATIONS.md`. Die Dienste sind kostenlos
- YouTube-Aufrufe werden über Spielnamen in Titeln zugeordnet; das ist eine Näherung
- Game Intelligence arbeitet regelbasiert; eine KI-Verfeinerung wäre kostenpflichtig und bleibt bis zur Freigabe aus
- Steam-Spielerzahlen gibt es nur für Spiele mit bekannter App-ID (Pflege ab Phase 6)

### 6. Nächster Schritt

Phase 6: Material Scout und Rights Agent mit Verwaltung von Creatorn, Quellen und Lizenzen, Rechteprüfung nach allen Kriterien aus Abschnitt 5, Ablaufüberwachung und Publisher-Richtlinien.

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
| 14.11.2026 | Testdaten mit erfundenen Spielen | Testdaten können nie mit echten Marktdaten verwechselt werden; im Live-Modus werden sie ausgeblendet |
| 14.11.2026 | Trend-Score mit festen, dokumentierten Gewichten; unbekannte Werte neutral | Nachvollziehbar; Anpassung später durch den Learning Agent (Phase 14) |
| 14.11.2026 | Game Intelligence regelbasiert statt per KI | Keine Kosten ohne Freigabe; KI-Verfeinerung später optional hinter dem Budget-Gate |
| 14.11.2026 | Keine inoffiziellen Steam-Store-Endpunkte | Nur dokumentierte, offizielle APIs (Projektregel) |
| 14.11.2026 | Material Scout übergibt (`DISCOVERED` → `RIGHTS_PENDING`), nur der Rights Agent entscheidet | Klare Zuständigkeit; der Scout kann nie freigeben |
| 14.11.2026 | Rechteprüfung unterscheidet „nicht erlaubt“ und „Nachweis fehlt“ | Betreiber sieht, ob er Unterlagen nachreichen kann oder die Nutzung ausgeschlossen ist |
| 14.11.2026 | Ohne geprüfte Publisher-Richtlinie keine Freigabe; GTA VI vorbelegt mit „nur mit Erlaubnis“ | Spezifikation Abschnitt 5: keine pauschale Freigabe |
| 14.11.2026 | Lizenzfreigabe nur durch Admin und nur mit hochgeladenem Nachweis; jede spätere Änderung setzt sie zurück | Vier-Augen-Prinzip zwischen Erfassung und Freigabe |
| 14.11.2026 | Testdaten-Lauf zeigt nie „Verbunden“; echter Status nur aus Live-Lauf oder Verbindungstest | Keine erfundenen Verbindungen (Projektregel) |
| 14.11.2026 | Nachweise lokal (Volume) bis Phase 7, inhaltsadressiert und unveränderlich | R2 kommt mit den Mediendateien; Format bleibt gleich (`local://` → `r2://`) |
| 14.11.2026 | Mediendateien bleiben lokal, bis R2-Zugangsdaten vorliegen | Keine Zugangsdaten ohne Betreiber; Speicherformat ist schon vorbereitet |
| 14.11.2026 | Szenenbewertung regelbasiert (Bewegung 35 %, Lautstärke 25 %, Überraschung 20 %, Schnitte 10 %, Spannungsaufbau 10 %) | Kostenlos, nachvollziehbar, relativ zum jeweiligen Material |
| 14.11.2026 | Ein Clip je Szene, beide Sprachfassungen nutzen dieselbe gerenderte Datei | Halbiert die Renderzeit; Sprache unterscheidet sich erst ab Phase 9 |
| 14.11.2026 | Kein Hochskalieren: 720p-Quellen ergeben 720×1280 | Hochskalieren verschlechtert die Qualität sichtbar ohne Mehrwert |
| 14.11.2026 | Dauerhafte Fehler (Datei, technische Prüfung) ohne automatische Wiederholung | Ein erneuter Versuch kann das Ergebnis nicht ändern; der Betreiber ersetzt die Datei |

## Offene Punkte

- `docker compose up` des Gesamtsystems auf einem echten Docker-Host bestätigen (Image-Build ist in der CI grün)
- Entwickler-Apps bei Google, TikTok und Meta anlegen (Betreiber); Audits können Wochen dauern
- Live-Trends: Schlüssel sind angelegt; nach dem Hinterlegen Verbindungstest, dann `TREND_SOURCES_MODE=live`
- LLM- und TTS-Anbieter nach aktueller Preisprüfung auswählen – vor Phase 8/9
- Publisher-Richtlinien für die Spiele pflegen, für die Material beschafft werden soll (Betreiber)
- Lizenznachweise, Material und Clips nach R2 verschieben und ins Backup aufnehmen – sobald R2-Zugangsdaten vorliegen, spätestens Phase 15
- Neuen YouTube-API-Schlüssel erstellen und Twitch-Secret rotieren (Betreiber)
- Zwei-Faktor-Anmeldung für Admins – Phase 15
- Alle ⚠️-Angaben in API_INTEGRATIONS.md gegen aktuelle Anbieterdokumentation prüfen
- Image-Versionen (n8n `stable`, Uptime Kuma `1`) vor Produktivbetrieb fest pinnen – Phase 15
