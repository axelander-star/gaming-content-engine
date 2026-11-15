# Entwicklungsplan nach Phase 15 (Phasen A–D)

**Stand:** 15.11.2026 · Grundlage: Gesamtauftrag des Betreibers vom 15.11.2026, [Abnahmetest](ACCEPTANCE_TEST.md), [Plattform- und Backup-Recherche](PLATFORM_PUBLISHING_REVIEW.md)

Die 15 Phasen der Spezifikation sind abgeschlossen. Dieser Plan beschreibt den Weg zum Livebetrieb und die Erweiterungen aus dem Gesamtauftrag. Er gilt in der Reihenfolge der Prioritäten: Erst wird das Bestehende abgesichert, dann angebunden, dann erweitert, dann live geschaltet.

**Regeln für alle Phasen**

- Bestehende Funktionen dürfen nicht beschädigt werden. Jede Erweiterung kommt mit Migration, Tests und Doku in einem eigenen PR; der Abnahmetest muss weiter grün sein.
- Mock-Modus bleibt Rückfalloption. `AUTO_PUBLISH_ENABLED=false` und `PUBLISHING_MODE=mock` bleiben Standard.
- Keine kostenpflichtigen Dienste, Server oder Speicher ohne ausdrückliche Freigabe. Alle Kostenpunkte stehen in Abschnitt 6.
- Zugangsdaten nur über Umgebungsvariablen bzw. verschlüsselt in der Datenbank (OAuth-Tokens), nie im Repository. Keine Social-Media-Passwörter speichern, nur offizielle OAuth-Verfahren.
- Öffentlich zugängliche Videos gelten nie automatisch als frei verwendbar.

## Übersicht und Priorität

| Prio | Phase | Inhalt | Kosten | Status |
|---|---|---|---|---|
| 1 | **A** | Abnahmetest, Befunde beheben, Plan | – | Abnahmetest ✅, Rest offen |
| 2 | **B** | Sicherheit und echte Anbindungen: 2FA, Zugangsdaten, Backup, Server-Vorbereitung, OAuth-Apps | Backup und Server nur nach Freigabe | offen |
| 3 | **C** | Erweiterung: Content-Projekte, mehrere Accounts, Regel-Steuerung, Gaming Clip Generator, KI-Produktion, Kontrollzentrum | KI-Anbieter nur nach Freigabe | offen |
| 4 | **D** | Inbetriebnahme: Server, echte Testveröffentlichungen, schrittweise Automatik | Server nach Freigabe | offen |

Phase C kann zum Teil parallel zu B laufen, weil sie im Mock-Modus entwickelt wird. Phase D setzt B voraus; C ist für einen ersten Livebetrieb mit einem Projekt (Gaming) nicht zwingend.

---

## Phase A – Abnahme und Befunde (Prio 1)

| Nr. | Aufgabe | Ergebnis |
|---|---|---|
| A1 | Abnahmetest nach Spezifikation Abschnitt 20 als automatischer Test | ✅ erledigt, läuft in jeder CI ([ACCEPTANCE_TEST.md](ACCEPTANCE_TEST.md)) |
| A2 | Standard für `max_daily_production_jobs` anheben (Vorschlag 50) und im Dashboard warnen, wenn das Limit die Pipeline anhält | offen |
| A3 | Zugangsdaten bereinigen: echte Werte aus `.env.example` entfernen (PR #17), betroffene Schlüssel beim Anbieter **rotieren** | PR offen; Rotation durch den Betreiber |
| A4 | Zugangsdaten prüfen: YouTube-Schlüssel neu, Twitch-Token **und** Helix-Abfrage, in einer neuen Sitzung mit den Umgebungsvariablen | offen (Schlüssel ungültig bzw. Variablen erst in neuer Sitzung) |
| A5 | Dieser Plan | ✅ |

**Abnahme:** Abnahmetest grün, keine Geheimnisse im Repository, Verbindungstest für YouTube und Twitch im Dashboard „verbunden“.

---

## Phase B – Sicherheit und echte Anbindungen (Prio 2)

### B1 Zwei-Faktor-Anmeldung für Admins

- TOTP nach RFC 6238 (Authenticator-App), keine SMS. Bibliothek `pyotp` (kostenlos).
- Pflicht für die Rolle Admin, optional für andere Rollen. Ohne eingerichtete 2FA kann ein Admin nach der Anmeldung nur die 2FA-Einrichtung öffnen.
- Geheimnis verschlüsselt speichern (bestehende `core/crypto.py`), 10 Wiederherstellungscodes (gehasht), Rate-Limit auf die Codeeingabe, Audit-Eintrag bei Einrichtung, Abschaltung und Nutzung eines Wiederherstellungscodes.
- Notfallweg per Kommandozeile auf dem Server (`python -m app.reset_2fa <email>`), damit ein verlorenes Telefon nicht aussperrt.
- Kritische Aktionen (Live-Modus einschalten, Not-Aus aufheben, Kanal verbinden) verlangen einen frischen Code.

### B2 Echte Trendquellen

YouTube-Schlüssel neu, Twitch prüfen, Steam auf dem Server prüfen, dann `TREND_SOURCES_MODE=live`. Quoten im Dashboard beobachten.

### B3 Externes Backup

Empfehlung aus der Recherche: **Cloudflare R2** (bei der Datenmenge voraussichtlich 0 € bis unter 1 €/Monat, Schreib-Token ohne Löschrecht). Alternative Hetzner Storage Box BX11 (3,20 € zzgl. MwSt./Monat). Die Sicherungen sind bereits verschlüsselt und werden nur kopiert. **Wird erst nach Freigabe eingerichtet.**

### B4 Server und Deployment vorbereiten

Alles ist gebaut (`deploy.sh`, `harden.sh`, Caddy, Uptime Kuma, [OPERATIONS.md](OPERATIONS.md)). Es fehlen: Server (nicht bestellen ohne Freigabe), Domain und DNS, `.env` auf dem Server, ACME-E-Mail, Uptime-Kuma-Alarmkanal.

### B5 OAuth-Apps je Plattform

Beim Anbieter anlegen (kostenlos): Google Cloud (YouTube Data API, OAuth-Client), TikTok for Developers (Login Kit, Content Posting API), Meta for Developers (Facebook Login for Business, Instagram). Ergänzen: **Instagram Login ohne Facebook-Seite** und **Twitch-Benutzer-OAuth** (nur lesend: eigene Clips, Statistiken).

**Abnahme Phase B:** 2FA für alle Admins aktiv, echte Trends im Dashboard, ein Backup außerhalb des Servers (nach Freigabe), OAuth-Verbindung je Plattform mit einem Testkonto hergestellt.

---

## Phase C – Erweiterung (Prio 3)

Reihenfolge innerhalb von C ist die empfohlene Umsetzungsreihenfolge: Jeder Baustein braucht den vorherigen.

### C1 Content-Projekte (Themenbereiche)

Heute ist alles auf Gaming ausgelegt. Neu ist eine Tabelle `content_projects` (z. B. Gaming, Tutorials, Wissen, Gesellschaft, KI, Ernährung, Sport, Gesundheit, KI-Videos; beliebig erweiterbar):

- Name, Beschreibung, Sprache(n), Zielgruppe, Tonalität
- eigene Strategie-Parameter, Formate und Längen, Designvorlagen (Schrift, Farben, Untertitelstil)
- erlaubte Quellen und Rechtearten
- Status (aktiv, pausiert, archiviert)

Gaming wird per Migration zum ersten Projekt; alle bestehenden Daten werden ihm zugeordnet, damit nichts kaputtgeht. Trends, Material, Clips, Varianten und Strategien bekommen eine Projekt-Zuordnung.

### C2 Mehrere Accounts je Plattform mit Projekt-Zuordnung

Mehrere Kanäle je Plattform gibt es schon. Es fehlen (Ergebnis der Recherche, Abschnitt 4):

- Zuordnung Kanal → Content-Projekt (ein Kanal gehört zu genau einem Projekt, ein Projekt hat beliebig viele Kanäle)
- Seitenauswahl nach einem Meta-Login (mehrere Facebook-Seiten bzw. Instagram-Konten aus einer Anmeldung)
- **gleichzeitig oder gestaffelt** veröffentlichen: Gruppenregel je Projekt (z. B. „YouTube sofort, TikTok +2 h, Instagram +4 h“)
- Freigabemodus je Account (siehe C3)
- Kontingente pro Google-Projekt beachten: das YouTube-Upload-Kontingent wird von **allen** YouTube-Kanälen geteilt

### C3 Regelbasierte Content-Steuerung (neues Kernmodul)

Je Content-Projekt ein bearbeitbares Regelwerk im Dashboard:

| Regelbereich | Inhalt |
|---|---|
| Themen und Suchbegriffe | Einschluss- und Ausschlussbegriffe, Spiele, Genres |
| Kriterien | Mindest-Trendscore, Mindest-Qualität, Altersfreigabe, Sprachen |
| Zielgruppen | Alters- und Interessenangaben je Kanal |
| Quellen und Rechte | erlaubte Quellen und Lizenzarten; alles andere wird **automatisch ausgeschlossen** |
| Formate und Längen | Hochkant/Quer, Mindest- und Höchstlänge |
| Accounts | welche Kanäle das Projekt bespielen |
| Zeiten und Häufigkeit | Zeitfenster und Grenzen; die **Menge bestimmt weiter der Publishing Strategy Agent** dynamisch, die Regeln setzen nur Grenzen |
| **Modus** | **automatisch** · **mit Freigabe** · **nur sammeln** |

- Der Modus gilt je Projekt und kann je Account strenger gesetzt werden (Account „mit Freigabe“ schlägt Projekt „automatisch“; nie umgekehrt).
- **Priorität und Zuordnung:** Passt ein Inhalt auf mehrere Projekte, entscheidet die Projektpriorität. Eine Duplikatsperre (bestehende Duplikaterkennung aus Phase 10, erweitert auf projektübergreifend) verhindert, dass derselbe Inhalt auf mehreren Accounts doppelt erscheint, außer die Gruppenregel erlaubt es ausdrücklich.
- **Automatischer Ausschluss** unsicherer oder nicht lizenzierter Inhalte vor der Produktion (Rechteprüfung, Inhaltsfilter, Personen-Erkennung aus C4).
- **Not-Aus auf drei Ebenen:** global (gibt es schon), je Projekt, je Account. Jede Ebene stoppt sofort alle geplanten Veröffentlichungen darunter. Not-Aus aufheben braucht einen frischen 2FA-Code.
- Jede Regeländerung wird versioniert und im Audit-Log festgehalten.

### C4 Gaming Clip Generator mit Ausschluss von Personen und Webcams

Baut auf Phasen 7–10 auf.

- **Nur Material mit Rechten:** Quellen sind ausschließlich registriertes Material mit gültiger Lizenz oder Publisher-Erlaubnis. Kein automatisches Herunterladen fremder Videos.
- **Personen, Gesichter, Webcams erkennen und ausschließen:**
  - Gesichtserkennung lokal und kostenlos (z. B. OpenCV-DNN oder MediaPipe; Modell und Lizenz vor Einbau prüfen) auf Stichproben-Frames.
  - Webcam-Overlay erkennen: rechteckige Bereiche mit Gesicht, die über viele Frames an derselben Stelle bleiben.
  - Reaktion je Fund: Bereich wegschneiden (Crop), wenn danach genug Spielbild bleibt; sonst Szene verwerfen. Im Zweifel verwerfen und im Dashboard zur Prüfung zeigen.
  - Qualitätskontrolle bekommt eine neue Prüfung „keine Personen im Bild“.
- **Automatischer Schnitt:** mehrere Szenen zu einem Clip, Tempo nach Formatvorlage, Hook in den ersten Sekunden.
- **Eigene Texte, Hooks und Stimmen:** aus C5 (Vorlagen jetzt, KI nach Freigabe).
- **Formate:** 9:16 (Shorts, Reels, TikTok), 1:1, 16:9.
- **Vorschau und Freigabe** im Dashboard vor jeder Veröffentlichung, wenn der Modus „mit Freigabe“ ist.

### C5 KI-Produktion „mit einem Klick“

Ein Knopf je Projekt startet die bestehende Kette (Trend → Material → Rechte → Analyse → Szenen → Schnitt → Texte → Stimme → Untertitel → QC → Vorschau → Planung → Freigabe → Veröffentlichung) und zeigt den Fortschritt. Was schon da ist: alle Schritte als Agenten. Was fehlt: der Start-Knopf je Projekt, eine Fortschrittsansicht und echte KI-Anbieter für Text und Stimme. **Anbieter (💶) erst nach Kostenvergleich und Freigabe**; bis dahin Vorlagen und Mock-Stimme.

Für Projekte ohne Gameplay (Wissen, Ernährung usw.) braucht es zusätzlich eine Materialquelle: eigene Aufnahmen, lizenzierte Stock-Videos oder KI-generierte Bilder/Videos (💶). Das wird je Projekt entschieden.

### C6 Privates Kontrollzentrum

Das Dashboard wird erweitert um:

- Projekt- und Account-Verwaltung (C1, C2)
- Redaktionskalender über alle Accounts (geplant, freigegeben, veröffentlicht)
- Medienbibliothek mit Lizenzstatus
- Freigabe-Warteschlange mit Vorschau
- Statistiken je Projekt und Account
- Regel-Editor und Not-Aus je Ebene (C3)
- KI-Verwaltung: Anbieter, Kosten, Budgetgrenzen

**Abnahme Phase C:** Zwei Projekte (Gaming und ein weiteres) mit je zwei Accounts laufen im Mock-Modus parallel, ohne doppelte Inhalte; jeder Modus (automatisch, mit Freigabe, nur sammeln) und jede Not-Aus-Ebene ist getestet; der Clip Generator verwirft ein Testvideo mit Webcam-Einblendung bzw. schneidet sie weg.

---

## Phase D – Inbetriebnahme (Prio 4)

1. Server bestellen und einrichten (💶, nach Freigabe), [OPERATIONS.md](OPERATIONS.md) Abschnitt 1.
2. Backup außerhalb des Servers aktiv (💶, nach Freigabe).
3. Ein Kanal je Plattform verbinden. Erste Veröffentlichung **privat** bzw. `SELF_ONLY`, Ergebnis prüfen.
4. Dann je Kanal einzeln öffentlich, zuerst im Modus „mit Freigabe“.
5. Nach zwei Wochen ohne Probleme: Modus „automatisch“ nur für Accounts, die der Betreiber ausdrücklich freigibt.
6. Learning Agent nach mindestens 8 echten Videos an 3 Tagen aktiv; Lernversionen zuerst als Test.

**Abnahme Phase D:** Echte, vom Betreiber freigegebene Veröffentlichung je verbundener Plattform; echte Kennzahlen im Dashboard; erste Lernversion auf echten Daten.

---

## 5. Integrationsstand je Plattform (fünf Ebenen)

Kurzfassung der Recherche des zweiten Threads; Details, Quellen und Grenzwerte in [PLATFORM_PUBLISHING_REVIEW.md](PLATFORM_PUBLISHING_REVIEW.md).

Legende: 🟢 echt geprüft · ✅ gebaut, nur gegen Mocks getestet · ❌ fehlt · ➖ von der Plattform nicht angeboten

| Ebene | YouTube | Twitch | TikTok | Instagram | Facebook |
|---|---|---|---|---|---|
| 1. API-Verbindung | ✅ (Schlüssel ungültig, neu erstellen) | 🟢 Token am 14.11.; Helix-Abfrage noch offen | ✅ | ✅ | ✅ |
| 2. Anmeldung / Account-Verknüpfung | ✅ OAuth | ❌ Benutzer-OAuth fehlt | ✅ OAuth | ✅ über Facebook-Seite; ❌ ohne Seite | ✅ Seiten-Token |
| 3. Informationen abrufen | ✅ | ✅ | ✅ | ✅ | ✅ |
| 4. Automatische Content-Erstellung | ✅ (Text Vorlagen, Stimme Mock) | ➖ | ✅ | ✅ | ✅ |
| 5. Echte Veröffentlichung | ✅ nie echt ausgeführt | ➖ keine Upload-API | ✅ nur privat ohne Audit | ✅ nie echt ausgeführt | ✅ nur Seiten, nie echt ausgeführt |

**Wichtigste Entscheidung für den Betreiber:** TikTok erlaubt ohne Audit nur private Posts, und das Audit schließt Werkzeuge für eigene Konten aus. Optionen: A) Upload als Entwurf, Veröffentlichung in der App von Hand, B) halbautomatisch (Datei fertig, Upload von Hand), C) geprüfter Drittanbieter (💶).

## 6. Kosten und Freigaben

Nichts davon wird ohne ausdrückliche Freigabe eingerichtet.

| Punkt | Phase | Grobe Kosten | Bemerkung |
|---|---|---|---|
| Server Hetzner CX33 | D | laut Hetzner-Preisliste prüfen | Budget gesamt ca. 50 €/Monat |
| Domain | D | wenige €/Jahr | |
| Cloudflare R2 (Backup) | B | voraussichtlich 0 € bis < 1 €/Monat | Empfehlung |
| Hetzner Storage Box BX11 (Alternative) | B | 3,20 € zzgl. MwSt./Monat | |
| Sprachmodell für Texte | C | nutzungsabhängig | erst Kostenvergleich |
| Text-zu-Sprache | C | nutzungsabhängig | erst Kostenvergleich |
| TikTok-Drittanbieter (Option C) | C/D | Abo | nur wenn gewählt |
| OAuth-Apps, 2FA, Gesichtserkennung lokal | B/C | 0 € | |
