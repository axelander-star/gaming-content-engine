# Projektstatus

**Stand:** 15.11.2026 · **Aktuelle Phase:** 15 abgeschlossen, Abnahmetest nach Abschnitt 20 durchgeführt · **Nächster Schritt:** Phase B laut [ROADMAP.md](ROADMAP.md) (2FA, gültige Zugangsdaten, Backup nach Freigabe, Server-Vorbereitung)

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
| 8 | Creative Director, Hooks, Skripte | ✅ abgeschlossen |
| 9 | Lokalisierung, Voiceover, Untertitel | ✅ abgeschlossen |
| 10 | Quality Control und Duplikaterkennung | ✅ abgeschlossen |
| 11 | Publishing Strategy Agent | ✅ abgeschlossen |
| 12 | YouTube-Integration | ✅ abgeschlossen |
| 13 | TikTok, Instagram, Facebook | ✅ abgeschlossen |
| 14 | Analytics, Learning Agent, Budgetkontrolle | ✅ abgeschlossen |
| 15 | Monitoring, Sicherheit, Backups, Skalierung | ✅ abgeschlossen |

## Einschub: private Nutzung (15.11.2026)

Entscheidung des Betreibers: Die Anwendung ist ausschließlich für ihn bestimmt, kein öffentliches Produkt. Umgesetzt (ohne Deployment): Prüfung des Cloudflare-Access-Tokens im Backend (`ACCESS_GUARD=cloudflare`), Einzelbenutzer-Modus (`SINGLE_USER_MODE`), Dienst `cloudflared` (Profil `tunnel`), interner Caddy-Eingang für den Tunnel, `harden.sh --tunnel`, Warnungen in `deploy.sh`. 13 neue Tests, alle 372 Backend-Tests grün. Checkliste ohne öffentliche Website überarbeitet. Offen: Einrichtung von Cloudflare (nach Prüfung durch den Betreiber), Upload in Teilstücken wegen 100-MB-Grenze, Entscheidung zur Rechtstext-Seite für Google/Meta. Details: [PRIVATE_ACCESS.md](PRIVATE_ACCESS.md), [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md).

## Abnahmetest nach Abschnitt 20 (15.11.2026)

Alle 15 Schritte laufen in einem zusammenhängenden Durchlauf ohne Fehler (`backend/tests/acceptance/test_spec_section20.py`, ca. 55 s, Teil der CI). **Echt** funktionieren Rechteprüfung, Analyse, Szenenerkennung, Schnitt, DE/EN-Varianten, Untertitel, Qualitätskontrolle, Strategieentscheidung, Lernlogik und Dashboard. **Simuliert** sind Trenddaten, Materialbeschaffung (Testvideo), Stimme, Veröffentlichung und Kennzahlen; echte Plattformverbindungen sind damit nicht bewiesen. Befund: Der alte Standardwert `max_daily_production_jobs = 10` hielt schon ein Material in zwei Sprachen an (ca. 16 Aufträge nötig); Standard jetzt 50, einstellbar unter Einstellungen → „Max. tägliche Produktionsjobs“. Bericht mit Abweichungen, offenen Problemen und Inbetriebnahme-Voraussetzungen: [ACCEPTANCE_TEST.md](ACCEPTANCE_TEST.md). Weiterer Plan in Phasen A–D (2FA, Content-Projekte, mehrere Accounts, Regel-Steuerung, Clip Generator, Inbetriebnahme): [ROADMAP.md](ROADMAP.md).

## Einschub: Live-Anbindung YouTube und Twitch (14.11.2026)

Der Betreiber hat einen YouTube-API-Schlüssel und eine Twitch-App angelegt. Vorbereitet wurde: Zugangsdaten nur über Umgebungsvariablen (Fehler behoben: die Variablen standen in `.env.example` doppelt, eine leere zweite Zeile hätte den Wert überschrieben; leere Werte zählen jetzt als „nicht gesetzt“), Verbindungsstatus mit Fehlern und Quote im Dashboard, Verbindungstest per Knopf (Admin), Wiederverwendung des Twitch-Tokens, Abbruch bei Rate Limit, Trendverlauf je Spiel. Details: `API_INTEGRATIONS.md`, Abschnitt „Live-Anbindung einrichten“. Verbindungstest nach Hinterlegung der Schlüssel (14.11.2026): Die Twitch-Zugangsdaten sind gültig (Token wird ausgestellt). Der YouTube-Schlüssel wird von Google als ungültig abgelehnt und muss neu erstellt werden. Steam ist aus der Entwicklungsumgebung nicht erreichbar und wird auf dem Server geprüft. Die versehentlich eingecheckte `.env` wurde aus dem Repository entfernt; die Schlüssel daraus müssen rotiert werden.

## Phase 15 – Bericht

### 1. Was wurde erstellt?

- **Systemprüfung und Alarme:** Die Zeitsteuerung prüft jede Minute Datenbank, Redis, Worker, Zeitsteuerung, Warteschlangen, Agentenfehler, Serverfehler der API, Datensicherung, Speicherplatz und Auslastung. Wird eine Prüfung schlechter oder erholt sie sich, entsteht eine Benachrichtigung, jeweils nur bei einer Änderung. Optional meldet sie den Zustand an einen Uptime-Kuma-Push-Monitor; Uptime Kuma alarmiert dann über seine eigenen Kanäle und merkt auch, wenn die Zeitsteuerung ausfällt
- **Datensicherung:** neuer Dienst `backup`. Er sichert täglich mit `pg_dump`, verschlüsselt mit GnuPG (AES-256) und legt ein Manifest mit Prüfsumme und Zeilenzahlen aus demselben Schnappschuss an. Danach folgt ein Wiederherstellungstest in eine leere Datenbank mit exaktem Vergleich, dann das Aufräumen nach Aufbewahrungsregel. Die Wiederherstellung geht immer in eine neue Datenbank. Befehle: `python -m app.backup run|list|restore-test|restore|loop`
- **Dashboard-Seite „System“:** Zustand aller Prüfungen, letzte Sicherung, Ergebnis des Wiederherstellungstests, Skalierungsempfehlung und Verläufe (Wartezeit, CPU-Last, wartende Aufträge)
- **Skalierungskriterien:** Empfehlung erst bei einem dauerhaften Engpass (mind. 3 h Messwerte, Engpass in 75 % der Messungen der letzten 6 h); sie wird nie automatisch ausgeführt
- **Sicherheit:**
  - Abhängigkeiten geprüft, `cryptography` wegen bekannter Schwachstellen auf 50.x angehoben
  - Schlüsselwechsel für gespeicherte Plattform-Tokens (`CREDENTIALS_ENCRYPTION_KEY_OLD`, `python -m app.rotate_credentials`)
  - zusätzliche Sicherheitsheader in Caddy
  - Zählung von Serverfehlern
- **Betrieb:**
  - `infrastructure/server/harden.sh`: Firewall, SSH nur mit Schlüssel, fail2ban, automatische Updates
  - `scripts/deploy.sh`: Sicherung vor dem Update, Bereitschaftsprüfung, Rücksprung
  - `scripts/load_test.py`
  - neue Anleitung `docs/OPERATIONS.md`

### 2. Geänderte Dateien

- Neu: `backend/services/{monitoring,backup}.py`, `backend/app/{backup,rotate_credentials}.py`, `backend/api/system.py`, `backend/tests/integration/test_operations.py`, `frontend/dashboard/SystemView.tsx`, `frontend/app/(dashboard)/system/page.tsx`, `infrastructure/server/harden.sh`, `scripts/{deploy.sh,load_test.py}`, `docs/OPERATIONS.md`
- Geändert: `backend/app/{main,scheduler}.py`, `backend/core/{config,crypto}.py`, `backend/Dockerfile` (PostgreSQL-16-Client aus dem offiziellen PGDG-Repository, GnuPG), `backend/pyproject.toml`, `docker-compose.yml` (Dienst `backup`, Volume `backup_data`), `infrastructure/caddy/Caddyfile`, `.github/workflows/ci.yml`, `.env.example`, `frontend/{components/AppShell.tsx,lib/api.ts,lib/types.ts,e2e/smoke.mjs,package.json}`, README, SECURITY, DEVELOPMENT_PLAN, PROJECT_STATUS

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest)
- Sicherung: echte Sicherung der Testdatenbank. Geprüft wird, dass die Datei verschlüsselt ist und die Rechte 0600 hat, dass der Wiederherstellungstest besteht und die Testdatenbank danach gelöscht ist. Erkannt werden muss: falscher Schlüssel, manipulierte Datei, abweichende Zeilenzahl, fehlender Schlüssel. Außerdem: Wiederherstellung nur in eine neue Datenbank, Aufbewahrungsregel, Kommandozeile, Zeitplan über die Zeitumstellung, Zeilenzahlen aus dem Schnappschuss
- Überwachung: fehlender Worker und fehlende Zeitsteuerung, Wartezeit, Agentenfehler, 5xx-Zählung über die echte API, Speicher und Auslastung. Eine fehlerhafte Prüfung darf die anderen nicht verdecken. Alarme nur bei Änderung, Uptime-Kuma-Push gegen einen nachgebauten Server, Zeitsteuerung, API mit Rechteprüfung (der Sicherungsschlüssel erscheint nie in der Antwort)
- Skalierung: zu wenig Daten, einzelne Spitze, Renderengpass, Worker-Engpass, Arbeitsspeicher, Speicher
- Schlüsselwechsel der Plattform-Tokens
- `pip-audit` und `npm audit`
- Lasttest mit 20 gleichzeitigen Clients über 30 s
- Frontend `typecheck` und `build`, E2E mit neuem Schritt „System“
- Lokal echte Sicherung der Entwicklungsdatenbank mit Wiederherstellungstest (3.042 Zeilen)
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 358 Backend-Tests bestanden (95 % Abdeckung); ruff, mypy und `alembic check` ohne Befund
- `verify_phase1.sh`: 68 bestanden, 0 fehlgeschlagen
- `npm run typecheck` und `npm run build` fehlerfrei; Playwright-E2E: 19 Schritte bestanden
- `pip-audit` nach dem Update und `npm audit` ohne Befund
- Lasttest: 2.275 Anfragen, 0 Fehler, p95 757 ms

### 5. Bestehende Fehler / Einschränkungen

- Zwei-Faktor-Anmeldung für Admins ist noch nicht umgesetzt (siehe SECURITY.md, Abschnitt 10)
- Die Sicherungen liegen bisher nur auf dem Server. Für die Kopie außerhalb (Hetzner Storage Box oder R2) müssen Ziel und Kosten noch freigegeben werden
- Das Docker-Image mit dem PostgreSQL-16-Client wird erst in der CI gebaut; hier läuft kein Docker-Dienst
- Härtungs- und Deployment-Skript sind nur als Probelauf geprüft (`--dry-run` bzw. Syntax), weil es noch keinen Server gibt
- Der Abnahmetest des Gesamtablaufs nach Spezifikation Abschnitt 20 (Trend bis angepasste Strategie in einem Durchlauf) steht noch aus. Die einzelnen Stufen sind getestet, aber noch nicht als ein zusammenhängender Lauf

### 6. Nächster Schritt

Abnahmetest nach Abschnitt 20 als zusammenhängender Lauf mit Mock-Diensten. Danach Inbetriebnahme auf dem Server (Härtung, `.env`, `deploy.sh`, Uptime Kuma), sobald der Betreiber den Server bereitstellt.

## Phase 14 – Bericht

### 1. Was wurde erstellt?

- **Analytics Agent** (Agent 16): misst jeden Post nach 1 h, 6 h, 24 h, 48 h und 7 Tagen und speichert die Zahlen je Zeitfenster. Ein verpasstes Fenster wird ausgelassen statt mit späteren Zahlen gefüllt, damit Videos immer im gleichen Alter verglichen werden. Einmal pro Tag und Kanal ein Bericht mit starken und schwachen Videos. Quellen: YouTube (Statistik und YouTube Analytics für Wiedergabedauer, Zuschauerbindung, Shares, Abonnenten), TikTok (Query Videos), Instagram (Media Insights), Facebook (Video Insights). Testposts bekommen gleichbleibende synthetische Zahlen, die im Live-Modus nirgends mitzählen
- **Learning Agent** (Agent 17): erkennt Spiele, Formate und Hooks, die über viele Videos klar besser oder schlechter laufen (mind. 8 Videos an 3 Tagen, Mehrheit auf derselben Seite, ein einzelnes virales Video zählt nicht). Daraus werden Faktoren zwischen 0,8 und 1,2, die die Auswahl im Publishing Strategy Agent und die Formatwahl im Creative Director beeinflussen, aber nichts sperren. Jede Änderung läuft zuerst 7 Tage als Test und wird zurückgenommen, wenn sie schlechter abschneidet. Alle Versionen bleiben gespeichert; Admins können jede wiederherstellen
- **Budget & Cost:** Fixkosten (Server, Backups, Domain) zählen von Monatsbeginn an voll gegen das Budget; Stufen 50/70/85/95 % wie bisher. Kosten pro produziertem und veröffentlichtem Video und pro 1.000 Aufrufe (nur echte Posts)
- **Dashboard „Analytics“:** Filter nach Zeitraum, Plattform, Sprache, Spiel, Format, Hook und Veröffentlichungszeit; Diagramme für Aufrufe, Zuschauerbindung, Wiedergabedauer, Interaktionsrate und Follower-Zuwachs; Performance pro Spiel, Format und Kanal; stärkste und schwächste Videos; Lernstand mit Versionen (Screenshot: `screenshots/phase14-analytics.png`)
- **Dashboard „Kosten“:** Gesamtkosten, Budgetstufe, Kosten nach Bereich, Speicher, API-Nutzung heute, Kosten pro Video (Screenshot: `screenshots/phase14-kosten.png`)
- Damit sind alle 18 Agenten gebaut

### 2. Geänderte Dateien

- Neu: `backend/services/{metrics,learning,costs}.py`, `backend/agents/{analytics,learning}.py`, `backend/api/analytics.py`, Migration `20261114_b4110411f3fb_learning_versions.py`, `tests/integration/test_analytics_learning.py`, `frontend/dashboard/{AnalyticsView,CostsView,charts}.tsx`
- Geändert: `backend/models/{analytics,__init__}.py`, `agents/{registry,publishing_strategy,creative_director}.py`, `services/{strategy,budget,youtube,tiktok,meta}.py` (Statistik-Berechtigungen), `app/{main,scheduler}.py`, `core/config.py`, Tests (`test_agents.py`, `test_agents_api.py`, `test_social_publishing.py`), `frontend/app/(dashboard)/{analytics,kosten}/page.tsx`, `frontend/lib/{api,types}.ts`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, `.env.example`, Dokumentation

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest), Migration und `alembic check`
- Messfenster und Toleranz, gleichbleibende Testzahlen, Analytics-Lauf mit Statuswechsel und Tagesbericht, YouTube-Statistik und -Analytics gegen nachgebauten Google-Server, Instagram- und Facebook-Insights, fehlende Berechtigung (keine Zahlen), abgelaufene Verbindung, Live-Modus ohne Testposts
- Learning: zu wenige Daten, einzelnes virales Video, alles an einem Tag, klare Muster; Test übernommen, Test zurückgenommen, Test ohne genug Daten; Rücksetzen per API mit Rechteprüfung
- Kosten: Fixkosten im Budget, Kosten pro Video und pro 1.000 Aufrufe, Speicher
- Frontend `typecheck` und `build`; E2E mit neuem Schritt „Analytics und Kosten“
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 337 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund; `verify_phase1.sh`: 67 bestanden, 0 fehlgeschlagen; `npm run typecheck` und `npm run build` fehlerfrei; Playwright-E2E: 18 Schritte bestanden

### 5. Bestehende Fehler / Einschränkungen

- Es gibt noch keine echten Posts, also auch keine echten Kennzahlen; der Learning Agent hat entsprechend noch nichts gelernt
- Server- und Speicherpreise stehen auf 0 €, bis die aktuellen Anbieterpreise geprüft und eingetragen sind (`SERVER_MONTHLY_EUR`, `OTHER_FIXED_MONTHLY_EUR`, `STORAGE_EUR_PER_GB_MONTH`)
- Für die neuen Statistik-Berechtigungen müssen Kanäle, die vor Phase 14 verbunden wurden, einmal neu verbunden werden
- TikTok liefert Zahlen nur für öffentliche Posts; private Testposts bleiben ohne Kennzahlen. Zuschauerbindung gibt es nur bei YouTube
- Die Speicherkosten zählen in der Kostenübersicht, aber (noch) nicht in der Budgetstufe
- Die Diagramme zeigen eine Reihe je Diagramm; Vergleiche mehrerer Kanäle in einem Diagramm folgen bei Bedarf

### 6. Nächster Schritt

Phase 15: Monitoring, Sicherheit, Backups und Skalierung (Uptime-Überwachung, Fehleralarme, tägliche verschlüsselte Backups mit Wiederherstellungstest).

## Phase 13 – Bericht

### 1. Was wurde erstellt?

- **TikTok** (Content Posting API, Direct Post): Anmeldung über Login Kit, verschlüsselte Tokens mit automatischer Erneuerung (der neue Refresh-Token wird jedes Mal gespeichert). Vor jedem Post wird geprüft, welche Sichtbarkeit das Konto erlaubt; Standard ist **privat** (`SELF_ONLY`). Upload in Stücken nach der offiziellen Anleitung, danach Statusabfrage. KI-Kennzeichnung (`is_aigc`), wenn eine KI-Stimme verwendet wurde
- **Nicht geprüfte TikTok-App:** Ein verbundener TikTok-Kanal bleibt „eingeschränkt“, bis TikTok die App geprüft hat (`TIKTOK_APP_AUDITED`). Meldet TikTok die Einschränkung beim Posten, wird der Kanal ebenfalls auf „eingeschränkt“ gesetzt und der Betreiber benachrichtigt; das Video wartet
- **Instagram Reels und Facebook Reels** (Graph API v25.0, Facebook Login for Business): eine Meta-App für beide. Der Kanal wird genau einer freigegebenen Seite bzw. einem Instagram-Profikonto zugeordnet; bei mehreren wird nicht geraten. Instagram: Kontingent prüfen, Container, Upload, Verarbeitung abwarten, veröffentlichen, Link speichern. Facebook: Start, Upload mit Fortsetzung, Abschluss, Status
- **Gemeinsame Fehlerbehandlung** für alle vier Plattformen (`services/platform.py`): abgelaufen → Kanal „abgelaufen“; eingeschränkt → „eingeschränkt“; Kontingent, Drosselung, Serverfehler → später erneut; sonst Auftrag fehlgeschlagen plus Benachrichtigung
- **Tagesgrenzen:** TikTok eigene Grenze (5 je Kanal), Instagram 50, Facebook 30 Reels je Seite (Meta-Vorgaben)
- **Dashboard:** Verbinden-Knopf für alle Plattformen (Admin), Rückmeldung nach der Anmeldung inkl. „eingeschränkt“

### 2. Geänderte Dateien

- Neu: `backend/services/{platform,tiktok,meta}.py`, `tests/integration/test_social_publishing.py`
- Geändert: `backend/services/{publishers,youtube}.py`, `agents/publishing.py`, `api/channels.py`, `core/config.py`, `app/main.py`, `tests/integration/test_publishing.py`, `frontend/dashboard/ChannelsTable.tsx`, `frontend/e2e/smoke.mjs`, `frontend/package.json`, `.env.example`, Dokumentation (`API_INTEGRATIONS.md`, `AGENTS.md`, `DEVELOPMENT_PLAN.md`)

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest), `alembic check`
- **Gegen nachgebaute TikTok- und Meta-Server (keine echten Aufrufe):** Anmelde-URLs, Token-Erneuerung mit neuem Refresh-Token, Stückelung, Direct Post privat und öffentlich, Fehler (Sichtbarkeit nicht erlaubt, Spam-Grenze mit HTTP 200, ungültiger Token, nicht geprüfte App, abgelehnter Beitrag), Seitenauswahl, Instagram-Reel mit Kontingent und Verarbeitung, Facebook-Reel mit Fortsetzung nach Abbruch und abgelehntem Video
- Publishing Agent: privater TikTok-Post, eingeschränkte App, Facebook-Reel, Tagesgrenze, fehlendes Veröffentlichungsrecht
- API: TikTok- und Meta-Anmeldung, Status „eingeschränkt“ bis zum Audit, Anmeldestatus nur für den richtigen Anbieter, Trennen mit Widerruf
- Frontend `typecheck` und `build`; E2E-Schritt „Plattform-Verbindungen“ (ohne App-Zugang wird nichts verbunden)
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 321 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund; `verify_phase1.sh`: 67 bestanden, 0 fehlgeschlagen
- 17 E2E-Schritte bestanden

### 5. Bestehende Fehler / Einschränkungen

- **Kein echter Post getestet.** Dafür braucht es eine TikTok-App, eine Meta-App sowie Testkonten bzw. eine Testseite. Hinweis: Reels auf Instagram und Facebook sind immer öffentlich; ein echter Test geht nur mit einem Testkonto und nach ausdrücklicher Freigabe
- TikTok-Posts bleiben privat, bis TikTok die App geprüft hat; Meta verlangt für fremde Konten ein App-Review
- Die Doku-Seite „Business Login for Instagram“ war nicht abrufbar; deshalb läuft Instagram über Facebook Login for Business (Instagram-Konto muss mit einer Facebook-Seite verknüpft sein)
- Meta-Verbindungen werden beim Trennen nur lokal gelöscht (kein dokumentierter Widerruf auf den geprüften Seiten)
- Kleinere Widersprüche in der Meta-Doku (Instagram-Limit 50 oder 100, Ablauf von Seiten-Tokens) sind in `API_INTEGRATIONS.md` markiert; wir verwenden jeweils den vorsichtigeren Wert
- Die Videodauer wird vor dem Facebook-Upload nicht selbst geprüft (Facebook: 3–90 s); ein zu langes Video wird von Facebook abgelehnt und als Fehler gemeldet

### 6. Nächster Schritt

Phase 14: Analytics, Learning Agent und Budgetkontrolle (Kennzahlen je Plattform, Lernen aus den Ergebnissen, Kostenübersicht).

## Phase 12 – Bericht

### 1. Was wurde erstellt?

- **YouTube-Anmeldung (OAuth 2.0):** Admins verbinden einen YouTube-Kanal im Dashboard (Einstellungen → Kanäle → „Mit YouTube verbinden“). Der Anmeldevorgang ist signiert und 10 Minuten gültig; nur ein aktiver Admin kann ihn abschließen. Wird die Upload-Berechtigung nicht erteilt, gilt der Kanal als „eingeschränkt“ und es wird nichts hochgeladen. „Trennen“ widerruft den Zugang bei Google und löscht ihn
- **Verschlüsselte Zugangsschlüssel:** Access- und Refresh-Token liegen verschlüsselt (Fernet) in der neuen Tabelle `channel_credentials`, nie im Dashboard, in Logs oder in Git. Abgelaufene Tokens werden automatisch erneuert; ist der Zugang widerrufen, wird der Kanal auf „abgelaufen“ gesetzt und der Betreiber benachrichtigt
- **Publishing Agent** (Agent 15): veröffentlicht fällige Planungen. Ein als Test geplanter Auftrag bleibt ein Test (nichts wird hochgeladen). Live nur bei `PUBLISHING_MODE=live`, `AUTO_PUBLISH_ENABLED=true`, Dashboard-Freigabe, kein Not-Aus und autorisiertem Kanal
- **Upload:** fortsetzbar nach dem offiziellen Protokoll (Abbruch → Stand abfragen → ab dem letzten Byte weiter), Prüfsumme der Datei vor dem Upload, Sichtbarkeit standardmäßig **privat**, Kategorie Gaming, Kennzeichnung synthetischer Inhalte (KI-Stimme)
- **Keine Doppelposts:** Der Auftrag wird vor dem Upload dauerhaft als „läuft“ gespeichert. Bricht der Server mitten im Upload ab, wird nicht blind erneut hochgeladen, sondern der Auftrag zur Prüfung markiert
- **Quoten und Fehler:** eigene Tagesgrenze für Uploads (Google: 100 pro Tag); Quote erschöpft, Serverfehler oder Netzprobleme → späterer neuer Versuch; dauerhafte Fehler → Auftrag fehlgeschlagen plus Benachrichtigung
- **Dashboard:** Spalte „Verbindung“ mit verbundenem Konto, Verbinden/Trennen (Admin), Rückmeldung nach der Anmeldung; auf „Publishing“ Link zum veröffentlichten Video (Screenshot: `screenshots/phase12-einstellungen.png`)
- TikTok, Instagram und Facebook warten bis Phase 13 (Auftrag bleibt geplant)

### 2. Geänderte Dateien

- Neu: `backend/core/crypto.py`, `backend/services/youtube.py`, `backend/services/publishers.py`, `backend/agents/publishing.py`, Migration `20261114_f2c67aa65750_channel_credentials.py`, `tests/integration/test_publishing.py`
- Geändert: `backend/models/{channels,__init__}.py`, `agents/registry.py`, `services/gates.py`, `api/{channels,publishing,schemas}.py`, `app/main.py`, `core/config.py`, `pyproject.toml` (cryptography), Tests (`test_agents.py`, `test_agents_api.py`), `frontend/dashboard/{ChannelsTable,PublishingView}.tsx`, `frontend/lib/{api,types}.ts`, `frontend/e2e/smoke.mjs`, `.env.example`, Dokumentation (`API_INTEGRATIONS.md`, `AGENTS.md`, `DEVELOPMENT_PLAN.md`)

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest), Migration und `alembic check`
- **Gegen einen nachgebauten Google-Server (keine echten Aufrufe):** Verschlüsselung, Anmelde-URL, Token-Erneuerung und widerrufener Zugang, Upload mit Abbruch und Fortsetzung, abgelaufene Upload-Sitzung, Quote erschöpft, dauerhafte Fehler
- Publishing Agent: Mock-Post genau einmal, pausierter Kanal, nur fällige Aufträge, bereits vorhandener Post, geänderte Datei, Live-Upload, nicht autorisierter Kanal, abgelaufene Verbindung, Quote, TikTok wartet, Test-Auftrag im Live-Modus bleibt Test
- API: Verbinden, Rückkehr von Google, Trennen, fehlender OAuth-Client, Rechteprüfung
- Frontend `typecheck` und `build`; E2E mit neuem Schritt „YouTube-Verbindung“
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 300 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund
- 17 E2E-Schritte bestanden
- `verify_phase1.sh`: 67 bestanden, 0 fehlgeschlagen

### 5. Bestehende Fehler / Einschränkungen

- **Noch kein echter Upload getestet:** Dafür braucht es einen Google-OAuth-Client und einen privaten Testkanal des Betreibers (Einrichtung: `API_INTEGRATIONS.md`, „Umsetzung in Phase 12 und Einrichtung“). Ein echter Upload erfolgt nur nach ausdrücklicher Freigabe
- Laut aktueller Google-Doku werden Uploads aus nicht geprüften API-Projekten nicht mehr auf „privat“ beschränkt; das wird vor dem ersten echten Upload noch einmal bestätigt. Unabhängig davon laden wir standardmäßig privat hoch
- Ein Auftrag, der während des Uploads abbricht, muss von Hand auf YouTube geprüft werden, bevor er neu geplant wird
- Der YouTube-API-Schlüssel für Trends ist weiterhin ungültig und muss neu erstellt werden; die Schlüssel aus der früher eingecheckten `.env` müssen rotiert werden
- Vorschaubilder (Thumbnails) und Playlists werden noch nicht gesetzt

### 6. Nächster Schritt

Phase 13: TikTok, Instagram und Facebook (Content Posting API, Instagram Graph API, Facebook Graph API), zunächst im Mock-Modus und ohne echte Posts.

## Phase 11 – Bericht

### 1. Was wurde erstellt?

- **Publishing Strategy Agent** (Agent 14): entscheidet für jeden Kanal getrennt, ob, wie viel, was und wann veröffentlicht wird. Es gibt keine feste Menge
  - **Menge** einmal pro Tag je Kanal: Jedes Video wird mit dem Kanalschnitt **zum selben Messzeitpunkt** verglichen (Median der früheren Videos nach 24 h, 48 h oder 7 Tagen; Reichweite 60 %, Interaktion und Zuschauerbindung 40 %). Videos unter 24 h werden noch nicht bewertet. Mehr nur, wenn der Median der letzten sechs Videos mindestens 1,2× über dem Schnitt liegt und mindestens 60 % von ihnen darüber sind; weniger bei höchstens 0,8× oder sinkender Qualität. Höchstens ±1 pro Tag, nach einer Änderung drei Tage messen, bevor weiter erhöht wird. Ohne genügend Daten bleibt die Menge
  - **Sicherheitsregeln:** Ein einzelnes virales Video erhöht nichts (Werte gedeckelt, Mehrheit nötig). Die Menge bleibt innerhalb der Kanalgrenzen und dessen, was mit dem Mindestabstand ins Tagesfenster passt. Erhöht wird nur, wenn genug Videos bereitstehen. Ein aktiver Kanal behält mindestens ein Video pro Tag; stoppen heißt pausieren. Nach einer Pause beginnt der Kanal wieder vorsichtig mit einem
  - **Auswahl:** zuerst die Qualität, dazu ein Bonus oder Abzug für Spiele, Formate und Hooks, die auf dem Kanal nachweislich gut oder schwach laufen (ab drei Videos). Nur eine Variante pro Clip und Tag; ab zwei Videos pro Tag ist eine Testvariante dabei
  - **Zeitpunkt:** im Tagesfenster des Kanals (Standard 11–21 Uhr Ortszeit, DE Europe/Berlin, EN America/New_York) mit Mindestabstand; mit genug Daten zuerst die Stunden, die auf dem Kanal am besten liefen
  - **Zurückhalten und zurücknehmen:** Bereits geplante Videos werden zurückgenommen, wenn die Qualität unter dem Minimum liegt, die Rechte nicht mehr gelten, der Kanal pausiert ist oder mehr geplant ist als die Tagesmenge. Im Live-Modus wird nur für autorisierte Kanäle mit freigegebener Veröffentlichung geplant
- **Strategie-Versionen** (`strategy_versions`): Jede Tagesentscheidung wird mit Begründung und Messwerten gespeichert. Ein Admin kann eine frühere Version wiederherstellen; sie gilt für den Rest des Tages
- **Master:** startet den Agenten einmal pro Kanal mit wartenden oder geplanten Videos, höchstens alle 60 Minuten (`STRATEGY_INTERVAL_MINUTES`)
- **Nichts wird veröffentlicht:** Der Agent legt nur Aufträge (`publishing_jobs`, Modus Mock) an und setzt die Variante auf `SCHEDULED`. Veröffentlichen ist Aufgabe von Phase 12/13
- **Dashboard „Publishing“:** je Kanal Entscheidung, Begründung, Messwerte, geplante und zurückgenommene Veröffentlichungen, frühere Versionen mit „Zurücksetzen“ (Screenshot: `screenshots/phase11-publishing.png`)
- **API:** `GET /api/publishing/plan`, `POST /api/publishing/channels/{id}/rollback` (Admin)

### 2. Geänderte Dateien

- Neu: `backend/services/strategy.py`, `backend/agents/publishing_strategy.py`, `backend/api/publishing.py`, Migration `20261114_ade2a3503d9a_strategy_versions.py`, `tests/unit/test_strategy_simulation.py`, `tests/integration/test_publishing_strategy.py`, `frontend/dashboard/PublishingView.tsx`
- Geändert: `backend/models/{publishing,__init__}.py`, `agents/{master,registry,quality_control}.py`, `services/{gates,orchestrator}.py`, `core/config.py`, `app/main.py`, Tests (`test_agents.py`, `test_agents_api.py`, `test_pipeline.py`), `frontend/app/(dashboard)/publishing/page.tsx`, `frontend/lib/{api,types}.ts`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, Dokumentation

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest), Migration und `alembic check`
- **Simulationen mit synthetischen Kanalverläufen:** Datenmangel, erster Start, einzelnes virales Video, breiter Erfolg, schwache Ergebnisse, Qualitätsabfall, fehlender Vorrat, Kanalgrenzen, 30-Tage-Verlauf (virales Video, dann Wachstum, dann Qualitätsabfall); dazu Auswahl, Zeitfenster, Mindestabstand und beste Stunden
- Mit Datenbank: erster Plan, Erhöhung am Folgetag, Rücknahme bei Qualität, Pause und Neustart, Live-Modus ohne Autorisierung, Kanal ohne Grenzen, Master-Verteilung je Kanal und Intervall, API mit Rücksetzen und Rechteprüfung
- Frontend `typecheck` und `build`; E2E mit neuem Schritt „Publishing“
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 282 Backend-Tests bestanden; ruff, mypy und `alembic check` ohne Befund
- **Abnahme Phase 11:** Simulationen mit Einzel-Viral, Qualitätsabfall und Datenmangel verhalten sich wie vorgesehen
- 16 E2E-Schritte bestanden

### 5. Bestehende Fehler / Einschränkungen

- Es gibt noch keine echten Kennzahlen (Analytics folgt in Phase 14). Bis dahin startet jeder Kanal mit einem Video pro Tag und ändert die Menge nicht
- Die Schwellwerte (1,2×, 0,8×, 60 %, drei Tage) sind begründete Startwerte und werden mit echten Daten überprüft
- Geplant wird für den laufenden Tag; ein Plan für mehrere Tage im Voraus fehlt noch
- Die eingerichteten Kanäle sind weiterhin pausiert und haben die Höchstgrenze 0. Erst wenn der Betreiber Grenzen setzt und einen Kanal fortsetzt, wird geplant

### 6. Nächster Schritt

Phase 12: YouTube-Integration (OAuth, verschlüsselte Tokens, Upload über die YouTube Data API, Quoten). Echte Uploads nur nach ausdrücklicher Freigabe; bis dahin Mock.

## Phase 10 – Bericht

### 1. Was wurde erstellt?

- **Quality Control Agent** (Agent 13): prüft jede fertige Variante, bevor sie für eine Veröffentlichung eingeplant werden kann. Blockierende Prüfungen lehnen unabhängig vom Wert ab, alle anderen senken den Qualitätswert (Start 1,0), der das Minimum aus den Einstellungen erreichen muss (Standard 0,70). Freigegebene Varianten gehen auf `READY_TO_PUBLISH`, abgelehnte auf `QUALITY_REJECTED` mit Gründen und einer Benachrichtigung
  - **Blockierend:** Datei fehlt oder wurde nach dem Rendern verändert (SHA-256), Datei nicht vollständig dekodierbar (fehlerhafter Export), nicht H.264/AAC/yuv420p, kein Hochformat 1080×1920 oder 720×1280, über 60 fps, Länge, Titel, Beschreibung oder Dateigröße über den Grenzen der Plattform des Kanals, Lizenz nicht mehr gültig, Stimme ohne kommerzielle Rechte, Untertitel fehlen, durchgehend schwarzes Bild, Duplikat
  - **Abzüge:** kein Ton (−0,15), Lautheit außerhalb −18 bis −10 LUFS (−0,10), Spitzenpegel über −1 dBTP (−0,05), mehr als 1 s Schwarzbild (−0,10), mehr als 40 % Standbild (−0,10), Sprechtext zu lang für seine Szene (−0,05), Lesbarkeit der Untertitel (−0,05)
- **Duplikaterkennung:** identische Datei (gleicher Hash) gegenüber allen bereits freigegebenen oder veröffentlichten Varianten; ähnliches Bild (Bild-Fingerabdruck je Sekunde, auch zeitlich verschoben, ab 60 % gleicher Sekunden) und gleiche Szene desselben Materials (mehr als 50 % Überschneidung) auf demselben Kanal. Varianten desselben Clips gelten als A/B-Test und sind erlaubt
- **Lautheit:** Die fertige Variante wird jetzt auf −14 LUFS normalisiert (Spitze −1,5 dBTP), dem üblichen Wert der Kurzvideo-Apps
- **Plattformgrenzen** (`services/quality.py`): YouTube Shorts bis 3 min, TikTok 10 min, Instagram Reels 3 min, Facebook Reels 90 s, Titel- und Beschreibungslängen. ⚠️ Vor Phase 12/13 gegen die offizielle API-Dokumentation prüfen
- **Dashboard:** neue Status „Bereit zur Veröffentlichung“ und „Von Qualitätsprüfung abgelehnt“; je Variante Ergebnis, Qualitätswert, Gründe, Messwerte (Lautheit, Spitze) und bestandene Prüfungen (Screenshot: `screenshots/phase10-qualitaet.png`)
- **API:** Die Clip-Liste enthält je Variante das letzte Prüfergebnis (`quality`)

### 2. Geänderte Dateien

- Neu: `backend/services/quality.py`, `backend/agents/quality_control.py`, `tests/integration/test_quality.py`
- Geändert: `backend/agents/registry.py`, `services/subtitles.py` (Lautheitsnormalisierung), `api/production.py`, `app/main.py`, Tests (`test_agents.py`, `test_agents_api.py`), `frontend/dashboard/ProductionView.tsx`, `frontend/lib/types.ts`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, Dokumentation

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest), `alembic check` (keine Schemaänderung nötig)
- Bewertung, Ähnlichkeit (auch verschoben), Überschneidung, Plattformregeln für alle Plattformen
- Durchlauf mit echtem Rendering bis zur Freigabe; Lautheit der fertigen Variante im Zielbereich
- Fehlerfälle: identische Datei, ähnliches Bild, gleiche Szene, abgeschnittene Datei (fehlerhafter Export), nachträglich veränderte Datei, fehlende Datei, zu langer Titel, Stimme ohne Rechte, Wert unter Minimum, abgelaufene Lizenz; Geschwistervariante als A/B-Test erlaubt
- Frontend `typecheck` und `build`; E2E vom Upload bis zum Prüfergebnis
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 251 Backend-Tests bestanden; ruff, mypy und `alembic check` ohne Befund
- **Abnahme Phase 10:** fehlerhafte Exporte und Duplikate werden zuverlässig blockiert
- 15 E2E-Schritte bestanden

### 5. Bestehende Fehler / Einschränkungen

- Plattformgrenzen stammen aus öffentlichen Hilfeseiten; vor dem Live-Betrieb gegen die API-Dokumentation prüfen
- Die Ähnlichkeit vergleicht das Gameplay-Bild. Material, das gespiegelt oder stark beschnitten wurde, wird nicht als Duplikat erkannt
- Abgelehnte Varianten werden nicht automatisch neu bearbeitet; der Betreiber entscheidet (Rückweg nach `EDITING` ist vorbereitet)
- Bildqualität (Unschärfe, Artefakte) wird nur über Dekodierbarkeit, Schwarz- und Standbild bewertet

### 6. Nächster Schritt

Phase 11: Publishing Strategy Agent (Menge, Auswahl und Zeitpunkt je Kanal dynamisch aus Leistung, Qualität, Kapazität und Plattformregeln; keine feste Menge).

## Phase 9 – Bericht

### 1. Was wurde erstellt?

- **Localization Agent** (Agent 10): prüft jede Sprachfassung für sich. Er erkennt Wörter der anderen Sprache (Spielnamen ausgenommen), behebt Formfehler (doppelte Leerzeichen und Wörter, Satzanfang, Satzzeichen), ergänzt den Zielgruppen-Hashtag (#GamingDeutsch, #GamingClips) und stellt sicher, dass Hook und Titel keine Kopie der anderen Sprachfassung sind. Jede Änderung ergibt eine neue Skriptversion. Text in falscher Sprache stoppt die Variante zur Prüfung
- **Voice Agent** (Agent 11) mit Stimm-Adapter: spricht jeden Abschnitt im Zeitfenster des Skripts, beschleunigt höchstens auf 1,15× und meldet, was trotzdem zu lang ist; daraus entsteht eine Sprachspur in Cliplänge. Nur Anbieter mit kommerziellen Nutzungsrechten werden akzeptiert, ein kostenpflichtiger nur nach Budgetfreigabe. Wie entschieden läuft eine stille Test-Stimme (`tts_provider = mock`); ein unbekannter Anbieter lässt die Variante warten statt zu scheitern
- **Subtitle Agent** (Agent 12): Untertitel aus den Sprachabschnitten, höchstens zwei Zeilen mit 32 Zeichen, mindestens 0,8 s sichtbar, Lesegeschwindigkeit geprüft (max. 17 Zeichen/s). Speichert SRT und WebVTT und rendert die fertige Variante: Untertitel eingebrannt (unten mittig, 22 % über dem Rand, frei von Plattform-Schaltflächen), Stimme über dem Gameplay, das beim Sprechen leiser wird. Ergebnis per ffprobe geprüft; danach `QUALITY_CHECK`
- **Bessere Zeitplanung der Skripte:** Beim Test mit echtem Rendering zeigte sich, dass lange Hooks (lange Spielnamen) nicht ins feste 2,5-s-Fenster passten. Jetzt bekommt jeder Abschnitt die Zeit, die er zum ruhigen Sprechen braucht, und die Restzeit wird als Pausen verteilt
- **Dashboard:** Status bis „Fertig, Qualitätsprüfung folgt“, je Variante Stimme, Tempo, Untertitel-Downloads (SRT/VTT), Hinweise und das fertige Video (Screenshots: `screenshots/phase9-produktion.png`, `screenshots/phase9-untertitel.png`)
- **API:** `/api/variants/{id}/file`, `/api/variants/{id}/subtitles.{srt|vtt}`; die Clip-Liste enthält Stimme und Untertitel je Variante

### 2. Geänderte Dateien

- Neu: `backend/services/{localization,voice,subtitles}.py`, `backend/agents/{localization,voice,subtitle}.py`, Migration `20261114_38edaa584e48_voice_subtitles.py`, `tests/integration/test_localization_voice.py`
- Geändert: `backend/agents/{base,registry}.py`, `services/{creative,media}.py`, `models/production.py`, `api/production.py`, `app/main.py`, `Dockerfile` (Schrift DejaVu), Tests (`test_agents.py`, `test_agents_api.py`, `test_creative.py`), `frontend/dashboard/ProductionView.tsx`, `frontend/lib/{api,types}.ts`, `frontend/e2e/smoke.mjs`, Dokumentation

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest), Migration und `alembic check`
- Sprachprüfung und Formkorrekturen, Tempo und Überlänge der Stimme, Untertitel-Aufteilung, Lesbarkeit, SRT/VTT/ASS-Format, Zeitplanung für Cliplängen 8 bis 60 s
- Durchlauf mit echtem Rendering: Testvideo → Clip → Konzept → Skript → Lokalisierung → Stimme → Untertitel → fertige Variante; geprüft werden Auflösung, Codecs, Länge und dass die Untertitel sichtbar im Bild sind (Bildvergleich im Untertitelbereich)
- Fehlerfälle: falsche Sprache, nicht angebundener Anbieter (wartet), Anbieter ohne kommerzielle Rechte (abgelehnt), kostenpflichtiger Anbieter ohne Budgetfreigabe (nicht aufgerufen)
- Frontend `typecheck` und `build`; E2E vom Upload bis zur fertigen Variante mit abspielbarem Video
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 236 Backend-Tests bestanden; ruff, mypy und `alembic check` ohne Befund
- **Abnahme Phase 9:** getrennte deutsche und englische Fassungen, Stimme nur von freigegebenen Anbietern, Untertitel als SRT/VTT und eingebrannt im Hochformat
- 15 E2E-Schritte bestanden

### 5. Bestehende Fehler / Einschränkungen

- Die Stimme ist bis zur Anbieterwahl still; Aussprache und Klang lassen sich erst mit echter Stimme prüfen
- Rechtschreibung wird regelbasiert geprüft, nicht mit einem Wörterbuch. Die Vorlagen sind geprüft, Spielnamen werden übernommen
- Eine lokale Stimme (z. B. Piper) wäre kostenlos, braucht aber eine Prüfung der Stimmlizenzen; noch nicht eingebaut
- Musik und Soundeffekte werden nicht hinzugefügt (nur mit Nutzungsrechten, Spezifikation Abschnitt 7)

### 6. Nächster Schritt

Phase 10: Quality Control und Duplikaterkennung (Bild, Ton, Untertitel, Rechte erneut, Duplikate über Hash und Bild-Fingerabdruck).

## Phase 8 – Bericht

### 1. Was wurde erstellt?

- **Creative Director Agent** (Agent 8): wählt für jeden gerenderten Clip Format und Hook-Struktur. Bewertet wird zu 60 % die Eignung der Szene laut Messwerten, zu 20 % das Spielprofil von Game Intelligence und zu 20 % die eigene Performance je Format (bis Phase 14 neutral). Automatisch gewählt werden nur Formate, deren Versprechen die Messwerte stützen (Epische Szene, Überraschung, Unerwartete Wendung, Storytelling). „Lustig“, „Knapp gescheitert“, Tipps, Challenge, Vergleich und Analyse bräuchten Bildverständnis und werden nicht behauptet
- **Varianten A–D mit echtem Unterschied:** Anzahl je Clip ist eine Betreiber-Einstellung (Standard 2, höchstens 4). Jede Variante hat eine eigene Hook-Struktur, wenn möglich auch ein anderes Format. A ist die beste Einschätzung, die weiteren sind als Test markiert, damit der Learning Agent sie später auswerten kann
- **Script & Hook Agent** (Agent 9): schreibt je Variante Hook, Sprechertext in Abschnitten mit Zeitmarken (Hook, Einstieg, Spannung, Auflösung, Aufruf), Titel und Beschreibung mit Quellenangabe. Deutsch und Englisch haben eigene Formulierungen, keine Übersetzung. Der Text wird gekürzt, bis er im ruhigen Sprechtempo in den Clip passt. Danach geht die Variante in `LOCALIZATION`
- **Sprachmodell-Adapter** (`services/llm.py`): Standard „mock“ nutzt die kostenlosen Vorlagen. Ein echter Anbieter lässt sich später über die Einstellung „KI-Anbieter“ zuschalten; jeder Aufruf wird vorher vom Budget-Dienst freigegeben und danach als Kosten gebucht. Ohne Freigabe oder unbekannten Anbieter wird die Vorlage verwendet (Entscheidung des Betreibers vom 14.11.2026)
- **Zwei Agenten in einem Status:** `EDITING` hat jetzt zwei Teilschritte (Konzept, Skript); Master und Gates verteilen danach
- **Dashboard:** Varianten mit Format und Hook in der Clip-Liste, aufklappbar Konzepte und Skripte mit Zeitmarken; Einstellung „Kreative Varianten je Clip“ (Screenshot: `screenshots/phase8-skripte.png`)

### 2. Geänderte Dateien

- Neu: `backend/services/{creative,llm}.py`, `backend/agents/{creative_director,script_hook}.py`, Migration `20261114_f0ba1b212370_creative_scripts.py`, `tests/integration/test_creative.py`, `frontend/lib/creative.ts`
- Geändert: `backend/agents/{base,registry,master}.py`, `services/{gates,controls}.py`, `models/production.py`, `api/production.py`, `app/main.py`, `tests/integration/test_agents.py`, `frontend/dashboard/{ProductionView,OperationsForm}.tsx`, `frontend/lib/types.ts`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, Dokumentation

### 3. Durchgeführte Tests

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest), Migration und `alembic check`
- Formatwahl nur aus Messwerten, Einfluss von Spielprofil und Performance, Varianten mit unterschiedlicher Hook-Struktur und Format, Skript je Sprache mit Wortbudget, Zeitmarken, Titellänge und Quellenangabe, Kürzung bei kurzen Clips, Ablauf über den Orchestrator (Konzept, dann Skript, falscher Teilschritt wird abgelehnt), Variantenzahl laut Einstellung, ruhige Szene ohne erfundenes Format, Sprachmodell-Adapter (Mock ohne Kosten, unbekannter Anbieter, Aufruf gesperrt ohne Freigabe, mit Freigabe gebucht), API
- Frontend `typecheck` und `build`; E2E: Upload bis fertiges Skript mit echtem Worker
- `scripts/verify_phase1.sh`

### 4. Erfolgreiche Tests

- 223 Backend-Tests bestanden; ruff, mypy und `alembic check` ohne Befund
- **Abnahme Phase 8:** Varianten A–D unterscheiden sich nachweisbar in Hook-Struktur und, wo die Szene es trägt, im Format; kein kostenpflichtiger Aufruf ohne Budgetfreigabe
- 15 E2E-Schritte bestanden

### 5. Bestehende Fehler / Einschränkungen

- Texte stammen aus Vorlagen. Sie sind kurz und sicher, aber weniger abwechslungsreich als ein Sprachmodell; ein Anbieter ist noch nicht gewählt
- Die Vorlagen kennen den Inhalt der Szene nicht (z. B. was genau passiert), nur Spiel, Format und Spannungsverlauf
- Die Performance je Format ist bis Phase 14 neutral; bis dahin entscheidet das Signal der Szene
- Der Sprechertext liegt vor, Stimme und Untertitel folgen in Phase 9

### 6. Nächster Schritt

Phase 9: Lokalisierung, Voiceover und Untertitel. Für Stimmen braucht es einen TTS-Dienst mit kommerziellen Nutzungsrechten; vor einem kostenpflichtigen Dienst frage ich nach. Bis dahin Mock und lokale Untertitel.

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
| 14.11.2026 | Hooks und Skripte zuerst aus Vorlagen, Sprachmodell später (Entscheidung des Betreibers) | Keine Kosten, voll testbar; Adapter ist austauschbar |
| 14.11.2026 | Nur Formate, die die Messwerte stützen, werden automatisch gewählt | Kein Versprechen („lustig“, „knapp gescheitert“), das niemand geprüft hat |
| 14.11.2026 | `EDITING` mit zwei Teilschritten (Konzept, Skript) statt neuem Status | Statusliste der Spezifikation bleibt unverändert |
| 14.11.2026 | Varianten je Clip als Betreiber-Einstellung (Standard 2) | Jede Variante kostet später Stimme und Rendering; Menge bleibt steuerbar |
| 14.11.2026 | Stimme zuerst als stille Test-Stimme, Anbieter später (Entscheidung des Betreibers) | Keine Kosten, Zeitplanung und Untertitel trotzdem echt getestet |
| 14.11.2026 | Nicht angebundener Stimm-Anbieter lässt Varianten warten, Anbieter ohne kommerzielle Rechte führt zum Fehler | Warten ist behebbar, fehlende Rechte nicht |
| 14.11.2026 | Untertitel eingebrannt plus SRT/VTT | Eingebrannt wirkt auf allen Plattformen gleich; Dateien für Plattformen mit eigener Untertitelfunktion |

| 14.11.2026 | Qualitätsprüfung: blockierende Prüfungen plus Qualitätswert mit Abzügen | Kaputte Exporte, Rechte und Duplikate dürfen nie durch einen guten Wert ausgeglichen werden |
| 14.11.2026 | Duplikate je Kanal; Varianten desselben Clips gelten als A/B-Test | Dieselbe Szene auf DE- und EN-Kanal ist gewollt, auf demselben Kanal nicht |
| 14.11.2026 | Fertige Varianten auf −14 LUFS normalisiert | Üblicher Wiedergabepegel der Kurzvideo-Apps, kein Lautstärkesprung |

| 14.11.2026 | Menge einmal pro Tag je Kanal, höchstens ±1, Erhöhung erst nach drei Tagen Messung | Gedämpft und nachvollziehbar; jede Änderung wird erst gemessen |
| 14.11.2026 | Vergleich mit dem Kanalschnitt zum selben Messzeitpunkt (Median), Videos unter 24 h werden nicht bewertet | Spezifikation Abschnitt 3: kein Urteil nach einer Stunde, robust gegen Ausreißer |
| 14.11.2026 | Aktiver Kanal mindestens ein Video pro Tag; stoppen nur per Pause | Bei null Videos entstehen keine Daten mehr, der Kanal käme nie zurück |
| 14.11.2026 | Rücksetzen erzeugt eine neue Version statt die alte zu löschen | Verlauf bleibt vollständig nachvollziehbar |

## Offene Punkte

- `docker compose up` des Gesamtsystems auf einem echten Docker-Host bestätigen (Image-Build ist in der CI grün)
- Entwickler-Apps bei Google, TikTok und Meta anlegen (Betreiber); Audits können Wochen dauern
- Live-Trends: Schlüssel sind angelegt; nach dem Hinterlegen Verbindungstest, dann `TREND_SOURCES_MODE=live`
- LLM- und TTS-Anbieter nach aktueller Preisprüfung auswählen – vor Phase 8/9
- Publisher-Richtlinien für die Spiele pflegen, für die Material beschafft werden soll (Betreiber)
- Lizenznachweise, Material und Clips nach R2 verschieben und ins Backup aufnehmen – sobald R2-Zugangsdaten vorliegen, spätestens Phase 15
- Neuen YouTube-API-Schlüssel erstellen und Twitch-Secret rotieren (Betreiber)
- Zwei-Faktor-Anmeldung für Admins – Phase 15
- Alle ⚠️-Angaben in API_INTEGRATIONS.md und die Plattformgrenzen in `services/quality.py` gegen aktuelle Anbieterdokumentation prüfen
- Image-Versionen (n8n `stable`, Uptime Kuma `1`) vor Produktivbetrieb fest pinnen – Phase 15
