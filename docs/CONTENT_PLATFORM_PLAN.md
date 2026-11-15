# KI-Content-Plattform – Architekturanalyse und Erweiterungsplan

Stand: 15.11.2026, 2. Fassung nach Alexanders Konzeptänderung („universelle, chatgesteuerte Multi-Channel-Content-Plattform statt nur Gaming“). Status: **Vorschlag, wartet auf Entscheidungen in Abschnitt 5.**

Grundlage: `main` (Phasen 1–15, Abnahmetest, ROADMAP A–D), offener PR #20, PLATFORM_PUBLISHING_REVIEW.md, PRIVATE_ACCESS.md, Design-Beispielbilder.

Es wird nichts deployt, nichts Kostenpflichtiges aufgerufen und keine Browser-Automatisierung verwendet. Alle bestehenden Seiten, Agenten und Tests bleiben erhalten.

---

## 1. Kurzfassung

Das System hat schon fast alles, was eine Content-Fabrik braucht: Agenten-Kette, Schnitt, Untertitel, Qualitätskontrolle, Strategie, Veröffentlichung mit Retry und Not-Aus, verschlüsselte Tokens, Kosten- und Budgetsteuerung. Es ist aber an drei Stellen auf Gaming und auf „ohne KI“ festgelegt:

1. **Nur ein Themenbereich.** Es gibt keine Themenbereiche, Kanäle sind nur Plattform × Sprache.
2. **Keine echte KI.** Texte kommen aus Vorlagen, die Stimme ist stumm (Mock). Ein Chat, Recherche und Ideenfindung brauchen ein Sprachmodell, und das kostet Geld.
3. **Inhalte nur aus Gameplay-Material.** Für Ernährung und andere Bereiche ohne fremde Videos fehlt eine eigene Produktionsart.

Der Plan baut darauf in 10 überschaubaren Phasen auf. Die Themenbereiche-Planung aus `docs/ROADMAP.md` (C1 Content-Projekte, C2 Kanalzuordnung, C3 Regeln und Modi, C6 Kontrollzentrum) wird übernommen.

## 2. Bestand und PR #20

| Bereich | Bestand | Bedeutung für die Erweiterung |
|---|---|---|
| Backend | FastAPI, PostgreSQL, Redis/RQ-Worker, Alembic, 372 Tests | trägt alles, kein neuer Dienst nötig |
| Agenten | 17 Fach-Agenten, Master-Orchestrator, Gates (Not-Aus, Budget, Rechte, Qualität) | Recherche- und Ideen-Agenten kommen dazu, Produktion bleibt getrennt |
| Kosten | `costs`, Budgetstufen bis „keine bezahlten Aufrufe“, `PAID_API_CALLS_ENABLED`, `ctx.authorize_cost` | jeder KI-Aufruf läuft da durch und wird einzeln erfasst |
| LLM | `services/llm.py` mit `get_model(provider)`, nur Mock | wird zum echten Adapter (Mock bleibt Standard) |
| Plattformen | YouTube (fortsetzbarer Upload), TikTok (Direct Post), Instagram/Facebook (Reels), Twitch (nur Trends) | wiederverwendet; Ergänzungen in Phase 8 |
| Tokens | verschlüsselt in `channel_credentials`, Schlüsselrotation | erfüllt „sichere Speicherung“ |
| Datenmodell Video | `variants` = fertiges Video je Kanal, Kette bis zur Lizenz `NOT NULL` | bleibt; neue Inhaltsarten bekommen eigene Rechte-Nachweise (siehe 3.4) |
| Dashboard | Next.js 16, TS strict, 9 Seiten, keine UI-Bibliothek | wird neu gestaltet, alte Seiten bleiben unter „Engine“ |
| **PR #20** | Cloudflare-Access-Prüfung (JWT) für jede API-Anfrage, Einzelbenutzer-Modus, Tunnel-Dienst, statische Rechtsseite ohne Dashboard-Zugang, **fortsetzbarer Upload** `/api/uploads` mit Verbraucher-Registry (`register_consumer`), Client `frontend/lib/upload.ts`, Migration `10196c7e684b` | Chat und alle neuen Endpunkte liegen automatisch hinter Access. Die Mediathek wird ein weiterer Upload-Verbraucher. Neue Migrationen hängen an `10196c7e684b` |

## 3. Zielarchitektur

```
Dashboard (nur hinter Cloudflare Access)
  Chat · Übersicht · Ideenlabor · Redaktionskalender · Produktion · Freigabecenter
  · Kanäle & Themenbereiche · Mediathek · Analytics · Engine (bisherige Seiten)
        │ /api (Session + Access-JWT, keine Secrets im Browser)
FastAPI
  api/assistant   Chat: Nachricht → Antwort + vorgeschlagene/ausgeführte Aktionen
  api/topics      Themenbereiche, Unterthemen, Regeln, Modus, Kanalzuordnung
  api/ideas       Ideen mit Quellen, Bewertung, Status (neu/übernommen/verworfen)
  api/plan        Redaktionsplan (Woche), Kalender
  api/library     Mediathek (eigene Uploads + produzierte Videos)
  api/approvals   Freigabecenter
        │
Worker-Queues getrennt:  research (Recherche, Ideen)  ·  production (Skript bis Video)  ·  publish
        │
KI-Schicht  services/ai/   ein Adapter, Mock | Claude; jeder Aufruf: Budgetprüfung → Aufruf → Kostenbuchung
Quellen     services/sources/  YouTube, Twitch, Steam (vorhanden) + RSS/News-Feeds + optional KI-Websuche
Plattformen services/platforms/  YouTube, Instagram, TikTok, Twitch (Fähigkeiten je Plattform)
```

### 3.1 Themenbereiche und Kanäle (aus ROADMAP C1/C2)

- Neue Tabelle `content_projects` (Themenbereich): Name, Beschreibung, Sprachen, Zielgruppe, Tonalität, Unterthemen (z. B. GTA, Gaming-News, Rezepte), erlaubte Quellen und Rechtearten, Formate, Status, Modus (siehe 3.6). Beliebig viele, im Dashboard anlegbar.
- Gaming wird per Migration der erste Themenbereich; alle bestehenden Daten werden ihm zugeordnet.
- Jeder Kanal gehört **genau einem** Themenbereich. Ideen, Videos, Pläne und Strategien tragen ebenfalls den Themenbereich.
- **Harte Sperre im Code:** Ein Inhalt kann nur auf einem Kanal desselben Themenbereichs veröffentlicht werden. Geprüft in den Gates, vor jedem Upload, mit Datenbank-Constraint, nicht nur in der Oberfläche. Ein Ernährungsvideo kann so nie auf dem Gaming-Kanal landen.

### 3.2 Chat-Assistent

- Der Chat ist ein Sprachmodell mit festen **Werkzeugen**, die nur bestehende Funktionen aufrufen: Fokus setzen („diese Woche GTA 6“), Plan ändern („Mittwoch zusätzlich Ernährung“), Recherche starten, Ideen erzeugen, Status abfragen, Video in Produktion geben.
- Jede Aktion erscheint im Chat als Karte („Plan für Mittwoch geändert: +1 Ernährung“) mit **Rückgängig**. Größere Aktionen (Produktion starten = Kosten) fragt der Chat vorher ab.
- Der Chat **kann nie veröffentlichen.** Veröffentlichen geht nur über das Freigabecenter (bzw. später den freigegebenen Automatik-Modus).
- Gesprächsverlauf in der Datenbank; das Modell bekommt nur den nötigen Ausschnitt (Plan, Themenbereiche, offene Aufgaben), damit die Kosten klein bleiben.
- Ohne freigegebenen KI-Anbieter läuft der Chat im Mock-Modus mit einfachen festen Befehlen, damit alles testbar bleibt.

### 3.3 Recherche und Ideenlabor (getrennt von der Produktion)

- **Quellen:** vorhandene Trendquellen (YouTube, Twitch, Steam), dazu RSS/News-Feeds je Themenbereich (kostenlos, z. B. Gaming-News, Ernährungsportale), optional die Websuche des KI-Anbieters (kostet je Suche, mit Obergrenze). Kein Scraping, nur offizielle APIs und Feeds.
- Ein Recherche-Agent sammelt je Themenbereich Signale, ein Ideen-Agent macht daraus **Ideen mit Quellenliste**, Format-Vorschlag, Kanalzuordnung, Bewertung (Trend, Passung, Aufwand, Rechte-Risiko).
- Das Ideenlabor zeigt neue Ideen auch ungefragt (z. B. täglich), du übernimmst oder verwirfst.
- Quellen jeder Idee bleiben gespeichert, bis zum veröffentlichten Video.

### 3.4 Produktion ohne fremdes Videomaterial

Drei Materialarten, je Themenbereich erlaubt oder nicht:

| Art | Rechte-Nachweis | Kosten |
|---|---|---|
| Lizenziertes Fremdmaterial (Gameplay, Clips) | bestehende Rechteprüfung (12 Kriterien) | – |
| Eigene Uploads (Mediathek) | Bestätigung „eigene Aufnahme“ beim Upload, gespeichert | – |
| Selbst erzeugt: Skript → Sprechertext → Stimme → Bild-/Textanimation, Grafiken → 9:16 → Untertitel | Nachweis „selbst erzeugt“ mit Anbieter und dessen Nutzungsbedingungen | Stimme und KI-Bilder/-Videos je nach Anbieter |

Fremdmaterial ohne Rechte wird weiterhin automatisch ausgeschlossen. Öffentlich sichtbare Videos gelten nie automatisch als frei verwendbar.

### 3.5 Redaktionsplanung

- Wochenplan als Tabelle `editorial_plan` (Tag → Themenbereich(e), Fokus-Thema, Notizen), änderbar per Chat und im Kalender.
- **Wichtig (Projektregel):** Der Plan legt fest, **welcher Themenbereich an welchem Tag** dran ist. Die **Menge je Kanal** bestimmt weiterhin der Publishing Strategy Agent dynamisch aus Leistung, Qualität, Kapazität und Plattformregeln; nichts davon wird fest einprogrammiert.
- Kalender zeigt geplante, freigegebene, veröffentlichte und fehlgeschlagene Beiträge über alle Kanäle.

### 3.6 Freigabe und Automatik (aus ROADMAP C3)

- Modus je Themenbereich, strenger je Kanal: **nur sammeln · mit Freigabe (Standard) · automatisch**.
- „Automatisch“ erst später und nur für Kategorien, die du ausdrücklich freigibst; zusätzlich gelten weiter `PUBLISHING_MODE=live`, `AUTO_PUBLISH_ENABLED` und Not-Aus (global, je Themenbereich, je Kanal).
- Freigabecenter: Video ansehen, Titel/Beschreibung/Hashtags je Plattform prüfen, Plattformen wählen, Termin prüfen, freigeben.

### 3.7 Plattformen (ehrlich)

| Plattform | Möglich per offizieller API |
|---|---|
| YouTube | Shorts und normale Videos, Sichtbarkeit wählbar, geplante Veröffentlichung |
| Instagram Reels | ja, eigene Profikonten; jeder Post sofort öffentlich; im Entwicklungsmodus der Meta-App evtl. nur für Rollen sichtbar ⚠️. Ergänzt wird „Instagram Login“ (ohne Facebook-Seite) |
| TikTok | ohne Audit nur privat; **Upload als Entwurf** als Standard, du veröffentlichst in der App. Direktveröffentlichung vorbereitet, aktiv erst nach Audit |
| Twitch | **kein Upload möglich** (keine API dafür). Twitch bleibt Datenquelle und Kachel; später optional Import eigener Clips |

Medienzugriff: YouTube, Instagram und TikTok bekommen die Datei vom Server **geschoben**. Die Plattformen müssen nichts bei uns abholen; Dashboard und API bleiben hinter Access. Zeitlich begrenzte signierte Links (R2, 15 min) nur als Rückfall. Gefundener Fehler: der Instagram-Upload liest die ganze Datei in den Arbeitsspeicher, wird in Phase 8 gestreamt.

### 3.8 Kosten nachvollziehbar

Jeder KI-Aufruf (Chat, Recherche, Texte, Stimme, Bilder) und jede Videoverarbeitung wird mit Themenbereich, Zweck, Modell, Tokens bzw. Sekunden und Betrag in `costs` gebucht. Kostenseite zeigt Verbrauch je Themenbereich und Zweck; Budgetstufen greifen wie bisher (ab 95 % keine bezahlten Aufrufe).

## 4. Phasenplan

Jede Phase ist ein eigener PR mit Migration, Tests und Doku, wird nach grüner CI gemergt. Code beginnt nach dem Merge von PR #20.

| Phase | Inhalt | Ergebnis / Tests |
|---|---|---|
| **1** | Themenbereiche + Kanalzuordnung + harte Sperre gegen falschen Kanal; Gaming als erster Bereich per Migration | Migration mit Bestandsdaten, Test „Ernährungsvideo auf Gaming-Kanal wird abgelehnt“, Abnahmetest weiter grün |
| **2** | Neues Dashboard-Design (Dark Mode, linke Navigation, Statistikkarten, Plattformkacheln, Statuschips, responsive), neue Startseite aus vorhandenen Daten, alte Seiten unter „Engine“ | typecheck, build, E2E (bestehende + neue Schritte), Screenshots in 3 Breiten |
| **3** | KI-Schicht: Adapter Mock/Claude, Budgetprüfung und Kostenbuchung je Aufruf, Einstellungsseite „KI“ (Anbieter, Modell, Monatsgrenze) | Tests nur gegen nachgebaute API, **kein echter Aufruf ohne Freigabe** |
| **4** | Chat-Assistent mit Werkzeugen, Aktionskarten mit Rückgängig, Verlauf | Tests je Werkzeug im Mock, E2E „Plan per Chat ändern“ |
| **5** | Recherche + Ideenlabor: RSS/News-Quellen je Themenbereich, Recherche-/Ideen-Agent, Quellen und Bewertung, eigene Queue | Tests mit festen Feeds |
| **6** | Redaktionsplan + Kalender (Woche/Monat, Verschieben), Anbindung an Strategy Agent | Tests: Plan ändert Themenbereich je Tag, Menge bleibt dynamisch |
| **7** | Mediathek (Chunk-Upload aus PR #20, Erkennung Länge/Auflösung/Format, 9:16-Renditionen, Original bleibt) + Produktion „selbst erzeugt“ (Skript → Stimme → Bild/Text-Video → Untertitel) | Tests mit Testvideos, Renderzeiten gemessen |
| **8** | Freigabecenter + Plattformen: Texte je Plattform, Vorschau, Termin, Freigabe; Instagram Login, TikTok-Entwurf, YouTube Shorts/Video, Twitch ehrlich gekennzeichnet; Status automatisch aktualisiert | Mock-HTTP-Tests, kein echter Post |
| **9** | Sicherheitsprüfung (Uploads, Werkzeuge des Chats, Prompt-Injection aus Recherche-Quellen, Token-Lecks), Doku, Abnahmetest erweitert (2 Themenbereiche × 2 Kanäle im Mock) | 6-Punkte-Bericht |
| **10** | Vorbereitung Hetzner: Speicherbedarf, Aufräumregeln, Checkliste je Plattform-App | nur Doku/Skripte |

Sicherheitsdetail zu Phase 5/9: Inhalte aus Recherche-Quellen sind fremder Text. Die KI darf daraus keine Anweisungen übernehmen; Werkzeuge mit Wirkung (Plan ändern, Produktion starten) sind im Recherche-Agenten gar nicht verfügbar.

## 5. Entscheidungen für Alexander

### 5.1 KI-Anbieter und Monatsbudget – ✅ entschieden 15.11.2026: Claude (Haiku 5.5 + Sonnet 5.5), harte Obergrenze 20 $/Monat

Ohne Sprachmodell gibt es keinen echten Chat, keine Recherche-Auswertung und keine Ideen. Grobe Schätzung bei Claude (Listenpreise 15.11.2026, Dollar):

| Modell | Preis je 1 Mio. Tokens (Eingabe / Ausgabe) | Einsatz |
|---|---|---|
| Claude Haiku 5.5 | 0,10 $ / 0,50 $ | Titel, Hashtags, Captions, Zusammenfassen von Quellen |
| Claude Sonnet 5.5 | 2 $ / 10 $ | Chat, Ideen, Wochenplan, Skripte |
| Websuche des Anbieters | 10 $ je 1.000 Suchen | Recherche über Feeds hinaus |

Annahme: 20 Chat-Nachrichten pro Tag, tägliche Recherche für 2 Themenbereiche mit je 10 Suchen, 2–4 Videos pro Tag mit Texten. Ergebnis grob **10–25 $ im Monat**, mit fester Obergrenze im Budget (bei Erreichen stoppt alles Bezahlte, der Rest läuft weiter). Nur Haiku: grob 2–5 $, aber spürbar schwächerer Chat und schwächere Ideen. Lokales Modell auf dem Server: auf einem 8-GB-Server nicht brauchbar.

### 5.2 Eigene Inhalte ohne Fremdvideo (Vorschlag, entscheidet sich später)

Start kostenlos: Text- und Bildanimation mit FFmpeg, eigene Uploads, und eine lokal laufende Open-Source-Stimme (z. B. Piper, Lizenz der Stimme vor Einbau prüfen). Bezahlte KI-Stimmen oder KI-Videos erst nach Kostenvergleich und eigener Freigabe; KI-Video ist pro Sekunde deutlich teurer als Text.

### 5.3 Eigene Uploads (Vorschlag A aus der 1. Fassung, bleibt)

Eigene Mediathek-Schicht, Veröffentlichung über die bestehende Maschine (Retry, Doppelpost-Schutz, Not-Aus, Analytics), Rechtebestätigung „eigene Aufnahme“ je Upload. Wenn du nichts dagegen hast, gehe ich so vor.

## 6. Offene Voraussetzungen (bei Alexander)

1. KI-Anbieter-Konto mit API-Schlüssel und Ausgabenlimit beim Anbieter (zusätzlich zur Grenze im System), nur nach Entscheidung 5.1.
2. Meta-App (Business) mit Instagram-Produkt, Instagram-Profikonto je Themenbereich.
3. TikTok-Entwickler-App mit `video.upload` (Entwurf); ob ohne Audit nutzbar, zeigt das Portal ⚠️.
4. Google-OAuth-Client, Zustimmungsbildschirm „In production“ (braucht die Datenschutzseite aus PR #20).
5. Je Themenbereich eigene Konten auf den Plattformen (z. B. eigener Ernährungskanal).
6. Domain + https (kommt mit der Server-Einrichtung). Speicher: Originale und Renditionen brauchen Platz; Entscheidung R2 oder Aufräumregel in Phase 10.
7. Erster echter Post je Plattform nur nach ausdrücklicher Freigabe.
