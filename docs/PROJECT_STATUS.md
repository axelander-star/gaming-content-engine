# Projektstatus

**Stand:** 27.11.2026 · **Aktuelle Phase:** Inbetriebnahme mit Alexander; A11 Trend-Alarm und Ideenlabor mit Seiten fertig · **Nächster Schritt:** eigenen Themenbereich anlegen, ersten YouTube-Kanal über den Kanal-Assistenten anlegen und verbinden; für echte Trend-Alarme `YOUTUBE_API_KEY` und `TREND_SOURCES_MODE=live` setzen

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

## Themenbereiche löschen (27.11.2026)

- Auf jeder Themenbereich-Karte gibt es neben Bearbeiten/Pausieren/Archivieren jetzt **Löschen**. Vorher zeigt ein Feld, was alles mitgelöscht wird (Kanäle, Material, Videos, Beiträge, Ideen, Redaktionsplan usw. mit Anzahl), was erhalten bleibt (Sponsorenanfragen, KI-Protokoll, dann ohne Themenbereich) und wie viele Videos schon online sind (die bleiben auf den Plattformen). Gelöscht wird erst, wenn der Name des Bereichs eingetippt ist.
- API: `GET /api/projects/{id}/deletion` (Vorschau) und `POST /api/projects/{id}/delete` mit `{"confirm_name": …}`; nur Admin, im Audit-Log (`project.delete` mit Anzahlen).
- `services/project_delete.py` sucht die betroffenen Zeilen über die Fremdschlüssel aller Tabellen (CASCADE/RESTRICT = mitlöschen, SET NULL = bleibt). Neue Tabellen sind damit automatisch abgedeckt. Gelöscht wird von den Kind-Tabellen aufwärts in einer Transaktion.
- Sperren: Der Standardbereich (Gaming) lässt sich nur archivieren; während eine Veröffentlichung des Bereichs läuft, wird nicht gelöscht; würde das Löschen Zeilen eines anderen Themenbereichs erreichen, wird abgebrochen.
- Dateien auf der Platte werden nicht sofort entfernt; sie sind danach verwaist und werden von `python -m app.housekeeping cleanup --apply` aufgeräumt.

## Hilfe und Anleitungen im Studio (26.11.2026)

- Auf jeder Seite öffnet das Fragezeichen oben rechts ein Seitenpanel mit der Anleitung genau für diese Seite: was die Seite macht, „So gehst du vor“, „Das machst du selbst“ (z. B. Konto anlegen, SMS/Captcha, beim Verbinden anmelden, Link bei Content Rewards einreichen) und „Gut zu wissen“.
- Neue Seite **Hilfe** (Menü → System): „Erste Schritte“ (Themenbereich anlegen → Kanal-Assistent → Kanal verbinden → erstes Video → freigeben) mit Links, darunter alle Anleitungen zum Aufklappen und eine Suche.
- Texte stehen zentral in `frontend/lib/help.ts`. Neue Seite im Menü → dort eine Anleitung ergänzen; der E2E-Test prüft, dass jede Menüseite eine hat.
- Behoben: In `globals.css` fehlten drei schließende Klammern (seit #47/#49/#51). Dadurch wurden alle Regeln dahinter (Kampagnen-Hilfe, Fixkosten, Serien) als verschachtelte Regeln gelesen und griffen nicht. `.row-actions` mit `nowrap` gilt jetzt nur für Tabellenzellen.

## Kostenseite mit Live-Kosten (22.11.2026)

- Fixkosten sind jetzt eintragbare Posten im Dashboard (Kosten → Fixkosten): Betrag, Währung (€/$), monatlich/jährlich, „zählt zum Engine-Budget“ ja/nein, pausieren, löschen. Neue Tabelle `fixed_costs`, API `GET/POST /api/costs/fixed`, `PATCH/DELETE /api/costs/fixed/{id}` (Änderungen nur Admin, im Audit-Log).
- Startliste wird einmalig von `python -m app.seed` angelegt: Contabo Cloud VPS 8 (13,33 €/Monat), Domain kanalfabrik.de bei INWX (Betrag fehlt noch), Claude Pro 20 $/Monat (nur Summe, nicht im Engine-Budget, weil das Abo keinen API-Zugang enthält), Cloudflare Free und R2 (0 €). Gelöschte Posten kommen nicht zurück. `SERVER_MONTHLY_EUR`/`OTHER_FIXED_MONTHLY_EUR` gelten nur noch, solange nie Posten angelegt wurden.
- Kostenseite und Übersicht laden sich selbst neu (Kosten alle 15 s, Übersicht alle 30 s): Monatskosten gesamt, „bisher angefallen“ (Fixkosten sekundengenau anteilig + echter Verbrauch), Verbrauch heute, KI-Tokens heute/Monat (Eingabe, Ausgabe, Cache, $), API-Kontingente heute.
- 25.11.: Echte Beträge eingetragen (Domain 5,97 €/Jahr, Claude Pro 21,42 €/Monat inkl. MwSt.; Migration `b7f2c4d91e30` ändert nur noch unveränderte Startwerte). Contabo bleibt bei 13,33 €, bis der Bruttobetrag bestätigt ist. Echte KI-Kosten entstehen erst mit eigenem Anthropic-API-Schlüssel in der Server-`.env` und ausdrücklicher Freigabe kostenpflichtiger Aufrufe.

## Videoserien in der Eigenproduktion (22.–25.11.2026)

- Neuer Reiter **Serien** in der Eigenproduktion: großes Thema → KI-Gliederung in 2–30 Teile (je 1–2 Minuten) → Skripte je Teil → alle Videos vorab erzeugen → „Alle fertigen Teile freigeben“ (Beiträge für alle echten Kanäle in der Sprache der Serie, menschliche Freigabe in einem Klick).
- Veröffentlichungsplan je Kanal als Vorschau; der Publishing Strategy Agent hält die Reihenfolge ein und verteilt die Teile über die Tage (Regeln in docs/AGENTS.md). Serie pausierbar.
- Ideen für Serien aus Ideenlabor, Redaktionsplan-Schwerpunkten und Serienformaten (ohne KI-Kosten); „Neue Ideen von der KI“ optional (Mock, solange Claude nicht freigegeben).
- Behoben: Bei jedem erneuten Planungslauf wurden schon geplante Mediathek-Beiträge mit „Quellmaterial fehlt“ zurückgenommen und neu geplant. Ein Test hing vom heutigen Datum ab.
- Offen: Gliederung und Skripte sind im Testmodus Platzhaltertexte; echte Texte brauchen die Claude-Freigabe. Englische Fassung gibt es je Teil (Einzelvideos), noch nicht für die ganze Serie.

## Ausbau ab 16.11.2026 abends (Kanal-Assistent und mehr)

Alexander hat am 16.11. einen größeren Ausbau freigegeben. Plan und Reihenfolge: [AUSBAU_PLAN.md](AUSBAU_PLAN.md). Testmodus bleibt, es wird nichts echt gepostet.

| Schritt | Inhalt | Status |
|---|---|---|
| A1 | Kanal-Assistent: fehlende Kanäle je Themenbereich erkennen, Name, Benutzername, Bio, Profilbild, Banner, E-Mail-Weiterleitung, Aufgabe „Kanal erstellen“ | ✅ abgeschlossen (PR #35) |
| A2 | Konten-Übersicht für viele Konten: Reichweite, Einnahmen je Konto, Empfehlung, Vorschlag „Pausieren erwägen“ nach 90 Tagen | ✅ abgeschlossen (PR #36) |
| A3 | Kommentare: harmlose selbst beantworten (menschlicher Ton), Kritik, heikle Themen und TikTok zur Freigabe | ✅ abgeschlossen (PR #37) |
| A4 | Chat mit Bildern/PDFs, Spracheingabe, vorgelesenen Antworten, Fertig-Meldungen; Warnsystem mit Glocke und Push aufs Handy | ✅ abgeschlossen (PR #38) |
| A5 | Feste Regeln im Redaktionsplan („jeden Donnerstag Uhren“), Feiertage und eigene Termine, Konkurrenz-Radar (YouTube) | ✅ abgeschlossen (PR #39) |
| A6 | Ein Video auf alle Plattformen inkl. Englisch, Texte je Plattform; lange Videos in Shorts zerlegen | ✅ abgeschlossen (PR #40) |
| A7 | Natürlichere Hooks ohne Floskeln, Hook-A/B-Tests auswerten, Gewinner mit neuem Hook erneut einplanen, Idee „Teil 2“ | ✅ abgeschlossen (PR #41) |
| A8 | Kampagnen je Themenbereich vorschlagen, Affiliate-Links mit „Anzeige“, Linkseite je Kanal mit Newsletter (Double-Opt-in) | ✅ abgeschlossen (PR #42) |
| A9 | Sponsoren-Postfach: Anfragen einordnen, Warnungen, Preisvorschlag, Antwortentwurf (nichts wird gesendet) | ✅ abgeschlossen (PR #43) |
| A10 | Wochenbericht per E-Mail (montags 8 Uhr, Vorschau und „Jetzt senden“ in Analytics) | ✅ abgeschlossen (PR #44) |
| N1 | Platzhalter-Kanäle aus dem Seed: im Kanal-Assistenten vorbereiten und zum echten Kanal machen, in der Übersicht nicht mitzählen | ✅ abgeschlossen (PR #46) |
| N2 | Kanalnamen aus Marktdaten: häufige Begriffe, Konkurrenz, bestehende YouTube-Kanäle; weitere Namensideen mit Begründung, „Neu recherchieren“ | ✅ abgeschlossen |
| A11 | Ideenlabor: 12 Ideen je Lauf, 5 je Seite mit Weiter/Zurück, Sortierung; Trend-Alarm-Agent mit Entwürfen, Push und Ein-Tipp-Freigabe, Automatik je Kanal (Standard aus) | ✅ abgeschlossen |
| K1 | Kampagnen-Hilfe (22.11.): Kampagnenseite als Text einfügen und Formular füllen lassen, fertige Videovorschläge aus Brief, Trends und Fakten, Überwachung von Fristen, Enddatum und Material | ✅ abgeschlossen |
| K2 | Lesezeichen „Ins Studio“ (26.11.): Kampagne auf Content Rewards öffnen, Lesezeichen klicken, Studio füllt das Formular. Prüfung automatischer Wege in CONTENT_REWARDS.md | ✅ abgeschlossen |
| N3 | Keine vorgefertigten Daten mehr: Seed ohne Kanäle, unbenutzte Platzhalter-Kanäle und erfundene Testdaten werden gelöscht, leerer Gaming-Bereich archiviert, im Betrieb keine erfundenen Testdaten | ✅ abgeschlossen |
| N4 | „Themen vorschlagen“: 5 Themenbereiche aus YouTube-Trends und Wikipedia mit Zahlen, Übernehmen füllt das Formular; nach dem Verbinden überträgt die Engine Beschreibung, Stichwörter und Banner zu YouTube | ✅ abgeschlossen |
| N5 | Ideenlabor zeigt den Fortschritt der Recherche (auch nach Verlassen der Seite), Anleitung wieder als Seitenleiste rechts, automatisches Update auf dem Server (`scripts/install_auto_update.sh`); Themenvorschläge mit Deutschland als Heimatmarkt, Gaming und Unterhaltung immer dabei (Gesamt-Chart als Ersatz für fehlende Kategorie-Charts), 8 statt 5 Vorschläge | ✅ abgeschlossen |
| N6 | Themenbereich-Formular: „Von der KI ausfüllen“ füllt Unterthemen, Zielgruppe, Tonalität und Beschreibung aus aktuellen YouTube-Trends; erneuter Klick gibt einen neuen Vorschlag | ✅ abgeschlossen |
| N7 | Kanal-Assistent: Knopf „Von der KI neu erstellen“ (Name, Benutzername, Bio, Profilbild, Banner auf einen Klick, jeder Klick ein neuer Vorschlag mit neuen Farben und Muster); Vorlagentexte nutzen Unterthemen des Themenbereichs | ✅ abgeschlossen |
| N8 | Anmeldung im Studio bleibt bestehen: im Privatbetrieb (ein Benutzer hinter Cloudflare Access) ein Jahr, sonst gleitend verlängert; abgelaufene Anmeldung führt zur Login-Seite statt „CSRF check failed“ | ✅ abgeschlossen |

**N2 Kanalnamen aus Marktdaten (25.11.2026)** (`services/name_research.py`, `services/channel_setup.py`, `api/channel_setup.py`, Spalten `channel_setup_tasks.name_options` und `.research`, Migration `5a8fd8799082`):
- Wunsch von Alexander: Die KI soll Kontonamen aus echten Daten, Fakten und Zahlen ableiten und mit den Trends gehen.
- Vor jedem Vorschlag sammelt die Engine je Themenbereich und Sprache: häufige Begriffe der letzten 30 Tage (Recherche-Meldungen, Ideen, Videotitel aus dem Konkurrenz-Radar), die stärksten Konkurrenten mit Median-Aufrufen und, mit Live-Zugang, bestehende YouTube-Kanäle zum Thema mit Abonnentenzahlen (offizielle API, eigenes Tageskontingent).
- Die Daten gehen in den KI-Auftrag (Begriffe nutzen, sich von bestehenden Kanälen abheben, nichts kopieren). Ohne KI entstehen Namensideen aus den häufigsten Begriffen. Namen, die es als Kanal schon gibt, werden aussortiert.
- Im Kanal-Assistenten stehen bis zu 5 weitere Namensideen mit Begründung (Knopf „Übernehmen“) und die „Datengrundlage“. „Neu recherchieren“ wertet die aktuellen Daten neu aus.
- Die laufende Trendbeobachtung (Agent, der Themen und Kanäle vorschlägt) liegt im Thread „Ideenlabor und Trend-Alarm ausbauen“. Die Namensvorschläge nutzen dessen Daten automatisch mit.
- Für Live-Daten auf dem Server: `YOUTUBE_API_KEY` und `TREND_SOURCES_MODE=live` in `.env`.

**N3 Keine vorgefertigten Daten (25.11.2026)** (`services/seed.py`, `core/config.py` `SAMPLE_DATA`, Migrationen `b7d2e4c91f05` und `c4a8f1e2d6b3`):
- Wunsch von Alexander: Er wählt Themen und Kanäle selbst. Auf dem Server standen 8 vorgefertigte Gaming-Kanäle und erfundene Testdaten (Fantasie-Spiele, Beispiel-Artikel, Ideen daraus).
- Der Seed legt nur noch Plattformen, Fixkosten und die GTA-VI-Rechteregel an. Die 8 Demo-Kanäle gibt es nur noch für Tests und den Dashboard-Smoke-Test (`python -m app.seed --demo-channels`).
- Migration `b7d2e4c91f05` löscht Platzhalter-Kanäle, die nicht verbunden sind, keine Plattform-ID und keinen Assistenten-Auftrag haben und auf die keine Zeile irgendeiner Tabelle verweist (Tabellen werden aus dem Datenbankkatalog gelesen). Alles andere bleibt.
- Neue Einstellung `SAMPLE_DATA` (leer = an außer bei `APP_ENV=production`): Im Betrieb erfinden die Mock-Quellen (Trends, Recherche, Konkurrenz-Radar, Trend-Alarm) nichts mehr. Echte Daten kommen mit `TREND_SOURCES_MODE=live` bzw. `RESEARCH_SOURCES_MODE=live`.
- Migration `c4a8f1e2d6b3` löscht vorhandene Testdaten (Mock-Meldungen, nur daraus entstandene neue Ideen, Mock-Trends und -Berichte, Test-Spiele ohne Verweise, unentschiedene Test-Alarme, Mock-Konkurrenzvideos). Nur mit `APP_ENV=production`: Der Bereich „Gaming“ wird archiviert, wenn nichts außer der Kostenhistorie auf ihn verweist; „Aktivieren“ holt ihn zurück.
- Der Standardbereich lässt sich jetzt archivieren, solange er keine Kanäle hat.

**K1 Kampagnen-Hilfe** (`services/campaign_assist.py`, Endpunkte `POST /campaigns/parse` und `POST /campaigns/{id}/proposals`, Spalten `campaigns.proposals*`, Migration `89fc8399876b`):
- Anlass: Alexander wollte Kampagnen auf Content Rewards „automatisch laufen lassen“. Klargestellt: Kampagnen legen Marken an, Alexander tritt bei. Beitreten, Konten verbinden und den Link einreichen bleiben Handarbeit (keine Clipper-Schnittstelle).
- Entscheidung Alexander 22.11.: Die Engine liest die Discover-Seite nicht selbst, er kopiert den Text der Kampagnenseite.
- Eingefügter Text → Formular: Vergütung je 1.000 Aufrufe, Budget, Höchstbetrag je Clip, Mindestaufrufe, Plattformen, Sprache, Hashtags, Werbehinweis, @Erwähnungen, Länge, Enddatum, Materiallinks, Spiel. Feste Regeln lesen, was eindeutig dasteht; die KI füllt nur Lücken, ihre Werte werden geprüft (Bereiche, erlaubte Plattformen, Datum in der Zukunft). Gespeichert wird erst mit „Kampagne anlegen“.
- Videovorschläge (3 je Kampagne): Titel, Einstieg, Szenenfolge, Text im Bild, fertige Beschreibung mit Werbehinweis, Pflichttext und Pflicht-Hashtags, Länge innerhalb der Kampagnenregel, Begründung und genutzte Fakten. Quelle: Brief, Trends des Spiels (14 Tage) und Recherche-Meldungen des Themenbereichs. Ohne KI oder im Testmodus kommen Vorlagen.
- Überwachung im Watchdog (alle 15 Min.): Erinnerung bei 20 Min. Restzeit und bei abgelaufener Einreichfrist, Kampagne endet in ≤ 3 Tagen, Enddatum vorbei, nach 24 h noch kein Material. Neue Vorschläge, wenn sich Trends oder Fakten ändern, höchstens einmal am Tag. Jede Kampagnenkarte zeigt den nächsten Schritt.

**Tests:** 18 Backend-Tests (`tests/integration/test_campaign_assist.py`), E2E-Schritt „Kampagnen“ füllt das Formular aus eingefügtem Text.

**N1 Platzhalter-Kanäle (22.11.2026)** (`services/channel_setup.py`, `services/seed.py`, `api/channel_setup.py`, `api/overview.py`, Datenmigration `3c9e1f2a7b44`):
- Befund im Betrieb: Die 8 Seed-Kanäle („YouTube Shorts DE“ …) im Standardbereich Gaming galten als „angelegt“. Der Kanal-Assistent bot deshalb nichts zum Vorbereiten an, und die Übersicht zählte sie als Kanäle („0 / 8“), obwohl Alexander noch kein Konto hat.
- Seed-Kanäle tragen jetzt `strategy.placeholder = true` (Migration markiert bestehende, solange sie nicht verbunden sind, keine Plattform-ID haben und nicht vom Assistenten stammen). Im Kanal-Assistenten heißen sie „Platzhalter, noch kein Konto“ und zählen als fehlend; „… fehlende vorbereiten“ und der Knopf „Vorbereiten“ je Kanal erzeugen die Aufgabe. „Kanal ist angelegt“ macht aus dem Platzhalter den echten Kanal (Name, Beschreibung, Handle; kein zweiter Kanal). Ein inzwischen verbundener Kanal wird nie umbenannt.
- Auch von Hand angelegte, nicht verbundene Kanäle lassen sich einzeln vorbereiten (`POST /api/channel-setup/channels/{id}/prepare`).
- Übersicht und Plattformkacheln zählen Platzhalter nicht mit.
- Nebenbei: `test_api_shows_plan_and_admin_can_roll_back` hing vom echten Datum ab (Jobs ab „jetzt − 1 Tag“) und schlug seit 18.11. fehl; die Uhr der API ist im Test jetzt auf den Testzeitpunkt gesetzt.

**A11 Ideenlabor und Trend-Alarm** (22.11.2026, Wunsch Alexander):
- Ideenlabor: `IDEAS_PER_RUN` von 5 auf 12, mehr Beispiel-Schlagzeilen im Testmodus. Neuer Endpunkt `GET /api/ideas/page` (Sortierung `score`, `trend`, `fit`, `title`, `newest`, `oldest`; Standard Ranking). Dashboard zeigt 5 Ideen je Seite mit „← Zurück“/„Weiter →“, Platz (#1, #2 …) und Auswahl „Sortieren nach“.
- Trend-Alarm (Agent 26, `services/trend_alarm.py`, `api/trend_alarms.py`, Seite `/trend-alarm`, Tabelle `trend_alarms`, Spalte `channels.trend_autopilot`, Migration `7433e2700ebb`): Signale aus YouTube-Trendliste und Konkurrenz-Radar, Wert 0–100 mit Fakten („2,4 Mio. Aufrufe in 8 Stunden …“), 3 eigene Video-Entwürfe je Alarm, Beiträge für alle passenden Kanäle vorbereitet, Push mit Link; ein Tipp gibt einen Entwurf frei. Details: [AGENTS.md](AGENTS.md), Schnittstelle: [API_INTEGRATIONS.md](API_INTEGRATIONS.md).
- Vollautomatik je Kanal: Entscheidung Alexander 22.11.: als Schalter, Standard aus. Wirkt nur mit `TREND_AUTOPILOT_ENABLED=true` auf dem Server und ab 85 Punkten.
- Grenzen: Fremde Videos werden nicht heruntergeladen oder „angeschaut“, nur Titel und Zahlen gelesen (Nutzungsbedingungen); TikTok/Instagram/X liefern keine offiziellen Trenddaten. Ohne `YOUTUBE_API_KEY` und `TREND_SOURCES_MODE=live` nur Test-Alarme per „Jetzt prüfen“.
- **Offen:** YouTube-API-Schlüssel und `TREND_SOURCES_MODE=live` auf dem Server setzen, dann echte Alarme; `PUSH_CLICK_BASE_URL=https://studio.kanalfabrik.de` muss gesetzt sein, damit der Push direkt die Freigabeseite öffnet.

**A1 Kanal-Assistent** (`services/channel_setup.py`, `services/branding.py`, `services/mail_alias.py`, `api/channel_setup.py`, Seite `/kanal-assistent`, Tabelle `channel_setup_tasks`, Migration `39d0ca70a01b`):
- Je Themenbereich und Sprache wird geprüft, ob es einen Kanal auf YouTube, TikTok und Instagram gibt (verbunden, angelegt, vorbereitet, fehlt).
- „Fehlende vorbereiten“ erzeugt je Lücke eine Aufgabe: Name, Benutzername plus Ausweichnamen (nach den Zeichenregeln der Plattform), Bio in der Kanalsprache innerhalb der Längengrenze (TikTok 80, Instagram 150, YouTube 1000 Zeichen), Profilbild 800 × 800 und YouTube-Banner 2560 × 1440 (Text im sicheren Bereich 1546 × 423), lokal mit Pillow gezeichnet, Farben je Themenbereich.
- Texte schreibt die KI (Claude Haiku, im Testmodus Mock); ist die KI gesperrt oder fehlt das Budget, kommen Vorlagentexte. Alles ist im Dashboard änderbar.
- E-Mail: TikTok und Instagram bekommen eine Weiterleitungsadresse wie `uhren-de-tiktok@kanalfabrik.de` (Cloudflare Email Routing, Entscheidung Alexander 16.11.). YouTube braucht keine, weil der Kanal ein Brand-Kanal unter dem Geschäftskonto ist.
- Benutzername-Prüfung nur, wo es eine offizielle Schnittstelle gibt (YouTube `channels.list forHandle`, 1 Kontingent-Einheit, nur mit `YOUTUBE_API_KEY` und `TREND_SOURCES_MODE=live`). TikTok und Instagram haben dafür keine, dort zeigt die Aufgabe Ausweichnamen.
- „Kanal ist angelegt“ legt den Kanal in der Engine an (pausiert, nicht verbunden, `max_posts_per_day = 0` wie jeder neue Kanal) und startet direkt das Verbinden per OAuth.
- Die Engine legt nie selbst Plattform-Konten an (Nutzungsbedingungen, Telefon/Captcha).

**Tests:** 17 Backend-Tests (`tests/integration/test_channel_setup.py`: Zeichenregeln, Bildgrößen, Abdeckung, Vorbereiten idempotent, KI-Antwort bereinigt, Rückfall auf Vorlage, YouTube-Prüfung über die offizielle Schnittstelle, Cloudflare-Regel anlegen und Fehler, kompletter API-Ablauf, Rechte), E2E-Schritt „Kanal-Assistent“. **Offen:** Cloudflare-Token anlegen und `MAIL_ROUTING_MODE=live` setzen (Anleitung in AUSBAU_PLAN.md); der echte Cloudflare-Aufruf ist nur gegen die Dokumentation geprüft, nicht live.

**A2 Konten-Übersicht** (`services/accounts.py`, `api/accounts.py`, Seite `/konten`, Tabelle `revenue_entries`, Migration `69b23e4d1abd`):
- Eine Zeile je Kanal: Beiträge, Aufrufe, Trend zu den 30 Tagen davor, Interaktionsrate, neue Follower, Einnahmen. Filter nach Themenbereich, Plattform, Status und Suche, sortierbare Spalten, 50 Zeilen je Seite. Alle Zahlen kommen aus wenigen gruppierten Abfragen (letzte Messung je Beitrag per Fensterfunktion), also auch bei 100+ Konten schnell.
- Einnahmen: Alexander trägt Auszahlungen je Kanal ein (YouTube, Content Rewards, Affiliate, Sponsor, Sonstiges). Für eingereichte Content-Rewards-Clips zeigt die Übersicht zusätzlich eine Schätzung (Aufrufe × CPM, gedeckelt je Clip, grob in Euro umgerechnet), getrennt von echten Einnahmen.
- Status je Kanal: Noch verbinden, Pausiert, Anlaufphase, Wächst (+20 %), Stabil, Lässt nach (−30 %), Keine Beiträge, **Pausieren erwägen**. Letzteres erst 90 Tage nach dem ersten Beitrag (Entscheidung Alexander 16.11.: 90 statt 60), bei mindestens drei Beiträgen, ohne Einnahmen und mit weniger als 25 % der üblichen Aufrufe je Beitrag im Themenbereich (ohne Vergleichskanäle: unter 200). Nur ein Vorschlag mit Begründung, pausiert wird nichts automatisch.
- „Lohnt sich am meisten“: die fünf Kanäle mit den höchsten Einnahmen plus Schätzung.

**Tests:** 6 Backend-Tests (`tests/integration/test_accounts.py`: Zusammenfassung mit nur letzter Messung, Pausieren-Vorschlag, Anlaufphase/keine Beiträge/Untergrenze, Einnahmen verhindern den Vorschlag, Content-Rewards-Schätzung mit Deckel, API und Rechte), E2E-Schritt „Konten“. **Offen:** Einnahmen automatisch aus der YouTube-Analytics-API holen (braucht den zusätzlichen Zugriff `yt-analytics-monetary.readonly` und ein Partnerprogramm-Konto); bis dahin Eintrag von Hand.

**A3 Kommentare** (Agent 23 „Community“, `services/comments.py`, `api/comments.py`, Seite `/kommentare`, Tabelle `comments`, Migration `9ac20b0b4565`):
- Alle 30 Minuten (und per „Jetzt abrufen“) holt der Agent neue Kommentare zu den Beiträgen der letzten 14 Tage: YouTube über `commentThreads.list`, Instagram über `/{media-id}/comments`. Eigene Kommentare werden übersprungen.
- Jeder Kommentar wird eingeordnet: Frage, Lob, Kritik, heikel (Politik, Gesundheit, Beleidigung, Rechtliches …), Spam, Sonstiges. Spam wird ignoriert.
- Die Antwort schreibt die KI im Ton eines echten Kanalbetreibers: kurz (höchstens 200 Zeichen), in der Sprache des Kommentars, ohne Floskeln wie „Danke für deinen Kommentar!“, ohne Hashtags. Typische KI-Sätze werden erkannt und verworfen, dann wird neu formuliert.
- Fragen, Lob und Sonstiges beantwortet die Engine selbst (abschaltbar mit `COMMENT_AUTO_REPLY=false`). Kritik und heikle Themen landen mit Entwurf unter „Zu prüfen“.
- TikTok bietet keine Kommentar-Schnittstelle für normale Apps. Alexander kopiert einen TikTok-Kommentar ins Dashboard, die Engine schlägt eine Antwort vor, „Antwort kopieren“ und in der App einfügen.
- Gesendet wird nur echt, wenn Veröffentlichen freigegeben ist und der Kanal verbunden ist; sonst wird simuliert und im Dashboard als Test markiert. Pro Lauf höchstens 10 Antworten, damit es nicht nach Bot aussieht.
- Nach dem Update müssen YouTube- und Instagram-Kanäle einmal neu verbunden werden, weil zwei Rechte dazukommen (`youtube.force-ssl`, `instagram_business_manage_comments` bzw. `instagram_manage_comments`).

**Tests:** 19 Backend-Tests (`tests/integration/test_comments.py`: Einordnung, KI-Floskeln verworfen, Entscheidungsregeln, Abruf YouTube/Instagram mit eigenem Konto übersprungen, Senden simuliert/echt, TikTok nur Kopieren, Neu formulieren, Ignorieren, API und Rechte), E2E-Schritt „Kommentare“.

**A4 Chat und Warnsystem** (`services/chat_media.py`, `services/notify.py`, `services/watchdog.py`, `api/notifications.py`, Glocke oben rechts, Tabelle `chat_attachments`, neue Spalten in `notifications`, Migration `89ce45412773`):
- **Dateien im Chat:** Büroklammer im Assistenten, Bilder (PNG, JPEG) und PDFs bis 10 MB, bis 5 je Nachricht. PDFs liest der Server selbst (pypdf, kostenlos); an Claude geht nur der Text (zusammen höchstens 30.000 Zeichen). Bilder gehen verkleinert (längste Seite 1568 px, höchstens ca. 1.600 Token) an Claude. Gescannte PDFs ohne Text werden nicht teuer verschickt; der Assistent bittet um Fotos der Seiten. Im Testmodus bestätigt der Assistent, was er gelesen hat.
- **Spracheingabe:** Mikrofon-Knopf, nutzt die Spracherkennung des Browsers (Chrome, Edge, Safari; kostenlos, ohne Server).
- **Vorlesen:** Lautsprecher an jeder Antwort und Schalter „Antworten vorlesen“. Mit Piper (Einstellungen → Betrieb) spricht der Server lokal und kostenlos, sonst liest die Stimme des Browsers vor.
- **Fertig-Meldungen:** Startet der Chat eine Recherche, kommt ein Hinweis in die Glocke, sobald sie fertig ist.
- **Warnsystem** (alle 15 Minuten): Rechte- oder Sperrhinweis einer Plattform beim Veröffentlichen (kritisch), Veröffentlichen fehlgeschlagen, Verbindung abgelaufen, Reichweite bricht ein (−30 %), dazu leise Hinweise „Pausieren erwägen“ und „Kommentare warten“. Jede Warnung höchstens einmal je 24 Stunden (Einbrüche einmal je Woche).
- **Push aufs Handy** über ntfy (kostenlose Open-Source-App): nur ab „Warnung“, nachts 22–7 Uhr nur Notfälle, was nachts anfällt kommt morgens gesammelt, ab vier Meldungen eine Sammelmeldung, gleiche Meldung nicht doppelt. Standard `PUSH_MODE=mock`: nichts verlässt den Server. Einrichtung in [AUSBAU_PLAN.md](AUSBAU_PLAN.md).
- Alte Hinweise vor dem Update werden nicht nachträglich gepusht.

**Tests:** 15 Backend-Tests (`tests/integration/test_chat_media_notify.py`: Bilder/PDFs speichern und prüfen, Verkleinern und Textgrenze, Chat mit Dateien im Test- und Live-Modus (Fake-Client), Vorlesen mit Browser-Rückfall und Server-Stimme samt Cache, Push nur Wichtiges und nicht doppelt, Umlaute, Ruhezeit mit Sammelmeldung, Testmodus/Fehler/alte Meldungen, Warnsystem einmalig, Fertig-Meldung, API und fremde Dateien), E2E-Schritt „Assistent: PDF anhängen …; Hinweise und Test-Push“. **Offen:** ntfy-Thema anlegen und `PUSH_MODE=live` setzen (Anleitung in AUSBAU_PLAN.md).

**A5 Wochenplan-Regel, Feiertage, Konkurrenz-Radar** (`services/plan_rules.py`, `services/events.py`, `services/competitors.py`, Agent 24 „Konkurrenz-Radar“, `api/competitors.py`, neue Endpunkte unter `/planning/rules` und `/planning/events`, Seite `/konkurrenz`, Tabellen `plan_rules`, `calendar_events`, `competitors`, `competitor_videos`, Spalte `editorial_days.rule_id`, Migration `785cb8bfb6eb`):
- **Feste Regeln:** Im Chat „jeden Donnerstag Uhren“ (auch „donnerstags Uhren“, „jede 2. Woche“ im Redaktionsplan) oder im Redaktionsplan unter „Feste Regeln“. Die Regel trägt den Themenbereich für die nächsten 28 Tage ein und füllt alle 15 Minuten nach. Einträge aus Regeln sind mit ↻ markiert. Löscht Alexander einen solchen Tag von Hand, wird er nicht wieder eingetragen. Regel-Tage sind nicht exklusiv: andere Themenbereiche dürfen an dem Tag weiter posten. Wie viele Videos es werden, entscheidet weiter der Publishing Strategy Agent. Fehlen dem Themenbereich Kanäle auf YouTube, TikTok oder Instagram, sagt der Assistent das direkt dazu (Kanal-Assistent).
- **Feiertage und Anlässe:** eingebaut und für jedes Jahr berechnet (ohne externen Dienst): bundesweite Feiertage, Heiligabend, Silvester, Valentinstag, Muttertag, Vatertag, Halloween, Singles' Day, Black Friday, Cyber Monday, Nikolaus, 1. Advent, für die englischen Kanäle Mother's/Father's Day, Independence Day, Thanksgiving. Jeder Anlass hat eine Vorlaufzeit (z. B. Black Friday 21 Tage); in diesem Zeitraum bekommt das Ideen-Labor ihn als Hinweis („nur nutzen, wenn es zum Thema passt“). Eigene Termine (gamescom, Spielstart …) mit Zeitraum, Sprache und Themenbereich trägt Alexander im Redaktionsplan ein.
- **Konkurrenz-Radar:** Je Themenbereich bis zu 30 YouTube-Kanäle (@name oder Link). Alle 12 Stunden holt der Agent die 20 neuesten Videos (offizielle Data API, 2–3 Einheiten je Kanal). Ein Video „läuft“, wenn es mindestens dreimal so viele Aufrufe hat wie sonst auf dem Kanal (Median) und höchstens 21 Tage alt ist. Solche Videos landen als Recherche-Eintrag im Ideen-Labor, mit dem Hinweis, das Thema mit eigenem Blickwinkel aufzugreifen statt es nachzumachen. TikTok und Instagram bieten keine offizielle Schnittstelle für fremde Konten und werden nicht beobachtet. Ohne `YOUTUBE_API_KEY` und `TREND_SOURCES_MODE=live` zeigt das Radar markierte Testvideos.

**Tests:** 12 Backend-Tests (`tests/integration/test_plan_events_radar.py`: Feiertage 2026 inkl. Ostern und Advent, Sprache und Vorlaufzeit, Anlässe im Ideen-Prompt, Regel füllt die Wochen und gelöschter Tag bleibt weg, jede 2. Woche, Regel-Tage sperren andere Themenbereiche nicht, Chat „jeden Donnerstag Uhren“ mit Hinweis auf fehlende Kanäle und Rückgängig, Kanalnamen erkennen, Testmodus mit Ausreißer und Recherche-Eintrag, Live-Abruf über die offiziellen Endpunkte (Fake-YouTube), Fehlermeldung ohne Schlüssel, API und Rechte), E2E-Schritt „Redaktionsplan: feste Regel, eigener Termin; Konkurrenz-Radar prüfen“. **Offen:** für echte Konkurrenzdaten `YOUTUBE_API_KEY` und `TREND_SOURCES_MODE=live` setzen.

**A6 Ein Video überall, lange Videos zerlegen** (`services/crosspost.py`, `services/splitter.py`, `approval.open_channels`, `own_production.translate`, neue Endpunkte `POST /library/{id}/split`, `POST /productions/{id}/translate`, `everywhere` bei `POST /approval/prepare`, neue Spalten `library_items.parent_item_id`, `split_state`, `split_info`, Migration `89f031ccb48d`):
- **Clips auf alle Plattformen:** Die Clip-Pipeline macht je Sprache eine Variante für den ersten Kanal des Themenbereichs (Deutsch und Englisch). Sobald sie die Qualitätsprüfung bestanden hat, kopiert die Engine sie alle 15 Minuten auf die anderen Kanäle derselben Sprache (z. B. YouTube DE → TikTok DE, Instagram DE). Gleiche, schon geprüfte Datei, kein neues Rendern. Titel, Beschreibung und Hashtags werden je Plattform zugeschnitten: Längengrenzen, wenige Hashtags (TikTok 5, Instagram 8), auf YouTube `#Shorts`. Wann und ob die Kopie erscheint, entscheidet weiter der Publishing Strategy Agent je Kanal. Ausgenommen: pausierte Kanäle, Kampagnen-Clips (das Briefing nennt die Kanäle), zu lange Videos für die Plattform (Facebook 90 s), Videos älter als 7 Tage. Die KI-Stimmen-Kennzeichnung geht mit (TikTok/YouTube), und die Duplikatprüfung zählt die eigene Kopie nicht als Duplikat. Abschaltbar mit `CROSSPOST_ENABLED=false`.
- **Mediathek-Videos überall:** Im Freigabecenter „Überall vorbereiten“: ein Beitrag je Kanal des Themenbereichs (alle Plattformen, Deutsch und Englisch), der das Video noch nicht hat. Texte schreibt die KI je Plattform und Sprache. Kanäle, deren Plattform die Datei nicht nimmt (Querformat für TikTok), werden ausgelassen statt alles abzubrechen.
- **Englische Fassung:** In der Eigenproduktion „Englische Fassung erstellen“ (bzw. „Deutsche Fassung“): neuer Entwurf mit denselben Bildern, Text von der KI natürlich übertragen (nicht Wort für Wort), Stimme und Untertitel beim Erzeugen in der neuen Sprache. Für hochgeladene Videos bleibt der Ton, englische Kanäle bekommen englische Texte; das Freigabecenter weist darauf hin.
- **Lange Videos zerlegen:** In der Mediathek „In Shorts zerlegen“ bei eigenen Videos ab 60 Sekunden: Anzahl (1–10, Vorschlag etwa eine je zwei Minuten) und Länge (10–90 s). Der Media-Library-Agent sucht im Hintergrund die stärksten Stellen (gleiche Signale wie die Clip-Analyse, an Schnitten ausgerichtet), schneidet sie ins Hochformat (Ausschnitt um die Bewegung oder unscharfer Hintergrund) und legt sie als „Titel – Teil 1“ usw. in die Mediathek, mit Zeitangabe und der Rechtebestätigung des langen Videos. Kostenlos, alles lokal. Danach Hinweis in der Glocke. Veröffentlicht wird nichts, die Shorts gehen wie jedes Video durchs Freigabecenter.

**Tests:** 10 Backend-Tests (`tests/integration/test_crosspost_split.py`: Kopie auf alle Plattformen derselben Sprache, nicht doppelt, keine Kopie der Kopie; pausiert, zu lang und abgeschaltet; KI-Stimmen-Kennzeichnung und keine Selbst-Duplikate; Texte an Wortgrenzen gekürzt; „Überall“ mit Englisch und Auslassen unpassender Plattformen; englische Fassung mit gleichen Bildern; Zerlegen eines 65-Sekunden-Videos in zwei Shorts mit Rechte-Prüfung; Ausschnitt ohne Bestätigung gesperrt; API Zerlegen/Übersetzen; „Überall“ ohne offene Kanäle), E2E-Schritt „Langes Video in Shorts zerlegen, englische Fassung, überall vorbereiten“.

**A7 Hooks, Hook-Tests, Gewinner-Recycling** (`services/hooks.py`, `services/winners.py`, Agent 25 „Winner Recycling“, `GET /analytics/hooks`, Abschnitt „Hook-Tests und Gewinner“ in Analytics; keine neue Tabelle):
- **Natürlichere Hooks:** Je Hook-Art und Sprache drei bis vier Formulierungen, wie ein Mensch sie sagt („Ehrlich, das klappt in Valorant fast nie.“ statt „Der krasseste Moment ever!“). Eine Prüfung erkennt typische KI- und Clickbait-Floskeln („Du wirst nicht glauben …“, „unglaublich“, „insane“, „in diesem Video“), mehrere Ausrufezeichen, Großbuchstaben-Wörter, Emojis im Sprechtext und Hooks über 14 Wörter. Schreibt ein Sprachmodell einen solchen Hook, nimmt die Engine die Vorlage. Die letzten zehn Hooks eines Kanals werden nicht wiederholt. Auch „episch“-Titel und -Sätze sind ersetzt.
- **Hook-A/B-Tests:** Der Creative Director plant schon Varianten mit verschiedenen Hooks (A, B …). Laufen zwei davon auf demselben Kanal, vergleicht die Engine ihre Bewertung (relativ zum Kanal, gleiches Alter). Ein Hook gewinnt ab 15 % Vorsprung, sonst unentschieden. Die Bilanz je Hook-Art steht in Analytics.
- **Gewinner-Recycling:** Ein Beitrag, der mindestens doppelt so gut lief wie üblich, kommt nach 7 Tagen (bis 60 Tage) noch einmal: gleicher Clip, anderer Hook (der mit der besten Bilanz, nie der alte), als neue Variante „R1“ durch Skript, Stimme, Untertitel und Qualitätsprüfung. Wann sie erscheint, entscheidet der Publishing Strategy Agent. Zusätzlich landet eine Idee „Teil 2: …“ im Ideenlabor (auch für Mediathek-Videos). Jeder Gewinner nur einmal, höchstens fünf je Lauf, Hinweis in der Glocke. Im Live-Betrieb zählen Testbeiträge nicht mit.

**Tests:** 8 Backend-Tests (`tests/integration/test_hooks_winners.py`: Floskeln/Großbuchstaben/Emoji/Ausrufezeichen, alle Vorlagen-Hooks natürlich, keine Wiederholung auf dem Kanal, Hook-Test mit Gewinner und Unentschieden, Recycling mit neuem Hook und Idee nur einmal und nicht zu früh, Agent überspringt ohne Beiträge, API), E2E prüft den neuen Abschnitt in Analytics.

**A8 Kampagnen je Thema, Affiliate, Linkseiten mit Newsletter** (`services/campaign_fit.py`, `services/affiliate.py`, `services/biolinks.py`, `services/newsletter.py`, `services/mailer.py`, `api/marketing.py`, `api/public.py`, `POST /campaigns/match`, Seite `/linkseiten`, Caddy-Eingang `:8082`, Tabellen `bio_pages`, `affiliate_links`, `newsletter_subscribers`, `outgoing_mails`, Migration `8a2b3df638e4`):
- **Kampagnen je Thema:** Content Rewards hat keine Schnittstelle für Clipper und verbietet Scraping, also holt die Engine keine Kampagnen selbst. Beim Anlegen einer Kampagne schlägt „Passenden Themenbereich vorschlagen“ den besten Bereich vor (0–100 Punkte: Thema/Spiel aus Name und Regeln, vorhandene Kanäle für die verlangten Plattformen und Sprachen) und schätzt den Verdienst je Clip (Median der Aufrufe dieser Kanäle × CPM, abzüglich 10 % Gebühr, gedeckelt). „Übernehmen“ setzt den Bereich.
- **Linkseite je Kanal** (für den „Link in der Bio“): andere Profile des Themenbereichs in derselben Sprache (aus dem Kanal-Assistenten), die drei neuesten echten Videos, eigene Links, Affiliate-Links, Newsletter-Anmeldung, Link zu Impressum und Datenschutz (`LEGAL_PAGE_URL`). Server-HTML ohne Skripte, Cookies oder fremde Inhalte, hell und dunkel, also kein Cookie-Banner nötig. Für jeden Kanal angelegt, aber aus, bis Alexander sie einschaltet. Öffentlich über einen eigenen Tunnel-Hostnamen ohne Access-Schutz (z. B. `links.kanalfabrik.de` → `http://caddy:8082`); dort ist nur die Seite, die Anmeldung und die Weiterleitung `/go/<id>` erreichbar, nichts vom Dashboard. Vorschau im Dashboard geht schon jetzt.
- **Affiliate-Links:** je Themenbereich, nur `https://`. Auf der Linkseite steht jeder mit „Anzeige“ (englisch „Ad“), `rel="sponsored nofollow"` und einem Satz, was ein Affiliate-Link ist (§ 5a UWG, § 6 DDG). Klicks werden über `/go/<id>` gezählt, ohne Cookie und ohne IP. In Beiträgen nur, wenn „In Beiträgen erwähnen“ an ist, ein Stichwort im Titel passt und die Linkseite des Kanals online ist: dann beginnt der Text mit „Anzeige: … – Link in meiner Bio“, die Qualitätsprüfung sperrt den Beitrag, falls der Hinweis später entfernt wird, und der Beitrag ist als Werbung markiert (Erinnerung, in der App das Werbe-Label der Plattform einzuschalten). Kopien auf Kanäle ohne Linkseite verlieren den Hinweis.
- **Newsletter:** Double-Opt-in. Anmeldung mit Einwilligungs-Häkchen; die Bestätigungsmail hat einen Link zu einer Seite mit Knopf (erst der Knopf bestätigt, damit Mail-Scanner niemanden eintragen). Abmeldelink in jeder Mail (auch `List-Unsubscribe`). Gespeichert werden nur Adresse, Sprache, Einwilligungstext und Zeitpunkte, Token nur als Hash. Unbestätigte Adressen nach 7 Tagen gelöscht, abgemeldete nach 30 Tagen. Spam-Bremse (Honigtopf-Feld, höchstens 20 Anmeldungen je Stunde und Seite). Adressen sehen nur Bediener und Admins; „Löschen“ entfernt eine Adresse ganz.
- **Mailversand:** `MAIL_MODE=mock` (Standard): Mails liegen nur im Postausgang auf der Seite „Linkseiten“, nichts verlässt den Server. `MAIL_MODE=smtp` mit `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` verschickt echt (STARTTLS). Mails werden nach 30 Tagen gelöscht. Wird auch für den Wochenbericht (A10) genutzt.
- Keine eigenen digitalen Produkte (Vorgabe).

**Tests:** 11 Backend-Tests (`tests/integration/test_marketing.py`: Affiliate-Hinweis nur mit Einwilligung, Linkseite und Stichwort, Hinweis am Anfang und Sperre ohne Hinweis, Kopie ohne Linkseite ohne Hinweis, nur https; Linkseiten für alle Kanäle, aus und Adressen eindeutig; öffentliche Seite mit Profilen, nur echten Videos, „Anzeige“, ohne Skripte, mit CSP, Klickzähler; Double-Opt-in mit Honigtopf, ohne Einwilligung, gleiche Adresse kein zweites Mal, Öffnen bestätigt nicht, Knopf bestätigt, Abmelden; Löschfristen und Spam-Bremse; SMTP ohne Server bleibt im Postausgang; Kampagnen-Vorschlag mit Schätzung; API und Rechte; öffentliche Pfade ohne Access-Prüfung), E2E-Schritt „Linkseite einschalten, Affiliate-Link mit Anzeige, Newsletter-Anmeldung“. **Offen:** Tunnel-Hostname `links.kanalfabrik.de` → `http://caddy:8082` (ohne Access) anlegen, `PUBLIC_LINKS_BASE_URL` und `LEGAL_PAGE_URL` setzen, Datenschutzerklärung um den Newsletter ergänzen; für echten Versand ein SMTP-Postfach (z. B. vom Mail-Anbieter der Domain) und `MAIL_MODE=smtp`.

**A9 Sponsoren-Postfach** (`services/sponsors.py`, `api/sponsors.py`, Seite `/sponsoren`, Tabelle `sponsor_inquiries`, Migration `6f1f7f4b3930`):
- Alexander fügt eine Markenanfrage ein (Absender, Betreff, Text). Ein Postfach-Zugang ist nicht nötig und nicht eingebaut.
- **Einordnung:** bezahlte Kooperation, Produkt zum Testen, nur Provision, Sonstiges oder Spam (SEO/Backlinks, Follower kaufen, Vorabzahlung). Spam landet direkt im Archiv, ohne Entwurf.
- **Warnungen** vor dem Antworten: Vorabzahlung verlangt, Glücksspiel/Wetten (auch Case-Opening), Krypto/Trading, Inhalte für Erwachsene, kein Geld (nur Produkt oder „Reichweite“), sehr kurze Frist.
- **Marke** aus der Absender-Domain (bei Gmail, GMX usw. aus dem Namen), **Themenbereich** nach passenden Wörtern, änderbar.
- **Preisvorschlag** aus der eigenen Reichweite: Median-Aufrufe je Beitrag der Kanäle des Bereichs × 15 € je 1.000 (Spanne 10–25 €), mindestens 50 €, Paket aus drei Shorts mit 10 % Nachlass, auf runde Beträge. Ausdrücklich als Startpunkt für die Verhandlung.
- **Antwortentwurf** in der Sprache der Anfrage (KI, Claude Haiku; ohne KI oder wenn die KI den Preis weglässt: Vorlage): kurz, freundlich, Preis und Leistung, Hinweis „wird als Anzeige gekennzeichnet“, Rückfragen zu Produkt, Zeitplan und Nutzungsrechten, keine Zusagen zu Ergebnissen. Bei „nur Provision“ und „nur Produkt“ höflich mit Preis für ein bezahltes Video.
- **Nichts wird gesendet:** „Antwort kopieren“ oder „Im Mailprogramm öffnen“ (mailto), danach Status Beantwortet, Zusage, Abgelehnt oder Archiv. Bei Zusage Hinweis, die Zahlung unter „Konten“ als Einnahme „Sponsor“ einzutragen. Nur Bediener und Admins sehen die Anfragen.

**Tests:** 6 Backend-Tests (`tests/integration/test_sponsors.py`: Einordnung und Warnungen, Marke aus Absender, Preis aus Median mit Mindestpreis und Paket, Entwurf auf Deutsch/Englisch mit Preis und „Anzeige“ und kein Mailversand, KI-Antwort ohne Preis fällt auf Vorlage zurück, API und Rechte), E2E-Schritt „Sponsoren-Postfach“.

**A10 Wochenbericht per E-Mail** (`services/weekly_report.py`, `GET /reports/weekly`, `POST /reports/weekly/send`, Abschnitt „Wochenbericht per E-Mail“ in Analytics; keine neue Tabelle, Versand über `services/mailer.py` aus A8):
- Montags um 8 Uhr (Ortszeit, `REPORT_WEEKDAY`/`REPORT_HOUR`) eine kurze Text-Mail über die letzte volle Woche (Montag bis Sonntag): Beiträge und Aufrufe mit Vergleich zur Vorwoche, je Themenbereich, die drei besten Beiträge mit Link, Kanäle mit deutlichem Plus oder Minus (±30 %) und „Pausieren erwägen“, eingetragene Einnahmen, Content-Rewards-Schätzung, Kosten im Monat, was wartet (Kommentare, Kampagnen-Links, Sponsorenanfragen, vorbereitete Konten), Warnungen der Woche, Newsletter-Leser, Plan der nächsten Woche, Link zum Dashboard.
- Genau ein Bericht je Woche (auch nach Neustarts), abschaltbar mit `REPORT_ENABLED=false`. Im Testbetrieb steht oben „Testdaten“.
- Empfänger `REPORT_EMAIL`. Ohne Empfänger oder mit `MAIL_MODE=mock` (Standard) liegt der Bericht nur im Postausgang (Seite „Linkseiten“).

**Tests:** 4 Backend-Tests (`tests/integration/test_weekly_report.py`: Summen, Vorwochen-Vergleich, Reihenfolge der besten Beiträge, Aufgaben; einmal je Woche zur eingestellten Zeit und abschaltbar; ohne Empfänger nur Postausgang; API mit Rechten), E2E-Schritt „Wochenbericht“. **Offen:** `REPORT_EMAIL` setzen und für echten Versand SMTP wie bei A8.

## Einschub: Entscheidungen des Betreibers (16.11.2026)

Alexander hat am 16.11. entschieden; umgesetzt im selben Pull Request:

| Entscheidung | Umsetzung |
|---|---|
| **Stimme: Piper** | neuer Stimm-Anbieter `piper` (`services/voice.py`): läuft lokal als eigenes Programm (Paket `piper-tts`, GPL-3.0), kostenlos. Nur Stimmen mit Lizenz für kommerzielle Nutzung: Deutsch `de_DE-thorsten-medium` (Thorsten-Voice, CC0, aus dem CC0-Basismodell „rdh“ trainiert), Englisch `en_US-ljspeech-high` (LJ Speech, Public Domain, von Grund auf trainiert). `de_DE-thorsten-high` wurde bewusst nicht genommen, weil es auf der Stimme „lessac“ aufbaut, deren Lizenz nicht eindeutig ist. Stimmen laden mit `python -m app.piper_voices fetch` (SHA256 je Modell festgelegt, eigenes Volume). Auswahl in Einstellungen → Betrieb. |
| **TikTok als Entwurf ins Postfach** | war seit E8 Standard (`TIKTOK_POST_MODE=inbox`); je Beitrag bleibt im Freigabecenter „Direkt posten“ wählbar (ohne Audit nur privat). Keine Codeänderung nötig. |
| **Originale eigener Aufnahmen nach 30 Tagen löschen** | `library.expire_originals` im Durchlauf des Mediathek-Agenten, `LIBRARY_ORIGINAL_RETENTION_DAYS=30` (0 = behalten), neue Spalte `library_items.original_deleted_at` (Migration `66d12af8800d`). Die 9:16-Fassung bleibt; ohne zweite Fassung wird das Video archiviert, aber erst wenn kein offener Beitrag es braucht. Mediathek zeigt „Original gelöscht“. |
| **Mehrere YouTube-Kanäle** (Frage) | ging schon: jeder Kanal hat seine eigene Verbindung. Neu: Google fragt beim Verbinden nach dem Konto bzw. Brand-Kanal (`select_account`), und dasselbe Konto kann nicht an zwei Kanälen hängen (sonst würden zwei Themenbereiche auf denselben echten Kanal posten). |

**Tests:** 4 Tests Aufbewahrungsfrist (Frist, Hochformat mit offenem Beitrag, gemeinsame Datei, Agent und API), 5 Tests Piper (Aufruf mit Text nur über stdin, nur freigegebene und geladene Stimmen, Prüfsumme beim Laden, Liste, Agent wartet ohne Stimmen), 1 Test „ein Konto je Kanal“. **Nicht geprüft:** die echte Piper-Sprachausgabe, weil die Stimmen in der Entwicklungsumgebung nicht herunterladbar sind (Hugging Face gesperrt); das passiert beim ersten `fetch` auf dem Server.

## Einschub: private Nutzung (15.11.2026)

Entscheidung des Betreibers: Die Anwendung ist ausschließlich für ihn bestimmt, kein öffentliches Produkt. Umgesetzt (ohne Deployment): Prüfung des Cloudflare-Access-Tokens im Backend (`ACCESS_GUARD=cloudflare`), Einzelbenutzer-Modus (`SINGLE_USER_MODE`), Dienst `cloudflared` (Profil `tunnel`), interner Caddy-Eingang für den Tunnel, `harden.sh --tunnel`, Warnungen in `deploy.sh`. 13 neue Tests, alle 372 Backend-Tests grün. Checkliste ohne öffentliche Website überarbeitet. Nachgezogen (15.11.): Prüfung des Zugangsschutzes ohne Blockieren der Ereignisschleife und mit 30 s Uhrentoleranz; statische Rechtstext-Seite für Google/Meta auf eigenem Caddy-Eingang `:8081` ohne Route zur Anwendung; fortsetzbarer Upload in Teilstücken (`/api/uploads`, Tabelle `upload_sessions`, Dashboard mit Fortschritt und Anhalten, 9 neue Tests, [UPLOADS.md](UPLOADS.md)). Offen: Einrichtung von Cloudflare und Server (gemeinsam, nach Prüfung durch den Betreiber), Rechtstexte lesen und `LEGAL_*` setzen. Details: [PRIVATE_ACCESS.md](PRIVATE_ACCESS.md), [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md).

## Einschub: Clipping-Kampagnen (Content Rewards, 16.11.2026)

Auf Wunsch des Betreibers: Kampagnen von Content Rewards als lizenzierte Materialquelle. Die Engine schneidet das Kampagnenmaterial, setzt Werbehinweis und Pflicht-Hashtags, prüft die Kampagnenregeln und veröffentlicht nach Freigabe; der Betreiber reicht den Link von Hand ein (keine offizielle Clipper-API) und hakt ihn im Dashboard ab. Beschreibung: [CONTENT_REWARDS.md](CONTENT_REWARDS.md).

1. **Erstellt:** Tabellen `campaigns` und `campaign_submissions` (Migration `b8643b7e945f`, Quelltyp `campaign`), `services/campaigns.py` (Kampagne als Quelle + Lizenz, Zielkanäle, Texte, Regelprüfung, Freigabe, Einreichungen mit Frist, Ertragsschätzung), `api/campaigns.py`, Dashboard-Seite **Kampagnen** mit Countdown, „Link kopieren“ und „Eingereicht ✓“.
2. **Geändert:** Rechteprüfung (Kampagnenlizenz deckt nur ihre Plattformen/Sprachen; pausierte oder beendete Kampagne sperrt), Gameplay-Analyse (Varianten nur für Kampagnenkanäle), Qualitätskontrolle (Texte + Regelprüfung, Kampagnen-Clips warten auf Freigabe), Publishing-Agent (legt die Einreichung an), Navigation, API-Client, E2E-Test.
3. **Tests:** 15 neue Backend-Tests (ganzer Weg vom Material bis zur Einreichung, API, ungültige Kampagnen, pausierte Kampagne); neuer E2E-Schritt.
4. **Ergebnis:** 541 Backend-Tests bestanden (inklusive Stand von main, 95 % Abdeckung), ruff, mypy und `alembic check` ohne Befund; Frontend `typecheck` und `build` grün; E2E 27 Schritte bestanden; `verify_phase1.sh` 70/0.
5. **Einschränkungen:** Einreichung bei Content Rewards bleibt Handarbeit; Aufrufzahlen und Ertrag je Kampagne erscheinen erst mit echten Analytics-Daten; der Strategie-Agent berücksichtigt Kampagnen noch nicht gesondert.
6. **Nächster Schritt:** Mit der ersten echten Kampagne testen, sobald Kanäle verbunden sind; danach Ertragsanzeige und Kampagnen-Priorität im Strategie-Agenten.

## Erweiterung: KI-Content-Plattform (ab 15.11.2026)

Der Betreiber hat das Ziel am 15.11.2026 erweitert: kein reines Gaming-System mehr, sondern ein persönlicher, per Chat gesteuerter KI-Content-Manager für beliebig viele Themenbereiche (z. B. Gaming, Ernährung) mit eigenen Kanälen. Plan mit 10 Phasen und Entscheidungen: [CONTENT_PLATFORM_PLAN.md](CONTENT_PLATFORM_PLAN.md). Entscheidung des Betreibers: KI-Anbieter Claude (Haiku 5.5 für Texte, Sonnet 5.5 für Chat, Ideen und Planung) mit harter Obergrenze 20 $/Monat; bis ein API-Schlüssel hinterlegt und freigegeben ist, läuft alles im Mock-Modus.

| Phase | Inhalt | Status |
|---|---|---|
| E1 | Themenbereiche, Kanalzuordnung, harte Sperre gegen falschen Kanal | ✅ abgeschlossen |
| E2 | Dashboard-Neugestaltung (Dark Mode, Navigation, Startseite) | ✅ abgeschlossen |
| E3 | KI-Schicht (Mock/Claude, Budget, Kostenbuchung) | ✅ abgeschlossen |
| E4 | Chat-Assistent mit Aktionen | ✅ abgeschlossen |
| E5 | Recherche und Ideenlabor | ✅ abgeschlossen |
| E6 | Redaktionsplan und Kalender | ✅ abgeschlossen |
| E7 | Mediathek und Eigenproduktion | ✅ abgeschlossen |
| E8 | Freigabecenter und Plattformen (Instagram Login, TikTok-Entwurf, YouTube Shorts/Video) | ✅ abgeschlossen |
| E9 | Tests, Sicherheitsprüfung, Doku | ✅ abgeschlossen |
| E10 | Vorbereitung Hetzner | ✅ abgeschlossen |

### Phase E10 – Bericht

**1. Was wurde erstellt?**

Nur Unterlagen und Skripte. **Nichts wurde bestellt oder deployt, es entstehen keine Kosten.**

- **[HETZNER_VORBEREITUNG.md](HETZNER_VORBEREITUNG.md):** Speicherbedarf mit Richtwerten je Videominute und Hochrechnung für ein Jahr, Aufräumregeln, offene Speicher-Entscheidungen, Checkliste je Plattform-App (YouTube, Instagram, TikTok, Facebook, Twitch, Claude, Cloudflare) mit Bereichen, Rückleitungen und `.env`-Werten, Ablauf am Tag der Bestellung.
- **Ergebnis Speicher:** Die Eigenproduktion braucht kaum Platz (einige GB im Jahr); der CX33 reicht dafür lange. Eigene Videoaufnahmen sind der einzige große Posten: 30 Minuten 1080p je Woche füllen den Server in etwa zwei Monaten. Vorher ist eine Entscheidung nötig (Originale nach Frist löschen oder nach R2 auslagern).
- **`python -m app.housekeeping report`:** zeigt die Belegung je Ordner, Sicherungen, Datenbank und archivierte Dateien und rechnet mit dem gemessenen Durchschnitt je Videominute hoch.
- **`python -m app.housekeeping cleanup`:** findet Arbeitsdateien älter als 6 h und Dateien, auf die keine Datenbankzeile mehr verweist (älter als 7 Tage; JSON-Felder werden mitgelesen). **Probelauf ist Standard**, gelöscht wird nur mit `--apply`. Verweist die Datenbank auf gar keine Datei, rührt das Skript keine verwaiste Datei an (Schutz gegen eine falsch angeschlossene Datenbank).
- **`infrastructure/server/preflight.sh`:** prüft einen neuen Server, ohne etwas zu ändern: Ubuntu, CPU, RAM, freier Speicher, Swap, Docker, Uhrzeit, von außen offene Datenbank-/App-Ports, `.env` (Pflichtwerte, Rechte 600, sichere Standardwerte, Cloudflare Access).
- **`scripts/deploy.sh`** räumt nach einem erfolgreichen Update alte Docker-Bauschichten weg.
- Produktionscheckliste: neue Punkte C7a (Vorabprüfung) und C18 (Aufräumen einplanen), B16 teilweise erledigt, TikTok-Bereiche präzisiert (die Verbindung fragt `video.upload`, `video.publish` und `video.list` an).

**2. Geänderte Dateien**

- Neu: `backend/services/housekeeping.py`, `backend/app/housekeeping.py`, `backend/tests/integration/test_housekeeping.py`, `infrastructure/server/preflight.sh`, `docs/HETZNER_VORBEREITUNG.md`
- Geändert: `scripts/deploy.sh`, `README.md`, `docs/{PROJECT_STATUS,OPERATIONS,PRODUCTION_CHECKLIST,BEDIENUNGSANLEITUNG}.md`

**3. Durchgeführte Tests**

- 4 neue Tests: Probelauf löscht nichts; mit `--apply` nur alte Arbeitsdateien und alte verwaiste Dateien; Dateien mit Verweis (Spalte oder JSON), junge Dateien und Upload-Teilstücke bleiben; Schutz bei leerer Datenbank; Bericht je Ordner mit Hochrechnung; Kommandozeile für beide Befehle
- `preflight.sh` in der Entwicklungsumgebung mit absichtlich unvollständiger `.env` (erkennt Rechte 644, leere Pflichtwerte, fehlende Cloudflare-Werte, nicht synchronisierte Uhr); `bash -n` für `deploy.sh`
- `scripts/test_backend.sh`, `alembic check`, Frontend `typecheck` und `build`, E2E, `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 516 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund
- E2E: 26 Schritte bestanden
- `verify_phase1.sh`: 70 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- Die Videogrößen je Minute für Handy- und Gameplay-Aufnahmen sind Richtwerte, keine Messung an echten Dateien; `housekeeping report` ersetzt sie nach den ersten Uploads.
- Noch nicht gebaut: Auslagerung nach R2 (B14), Löschfristen für Originale und Annahmestopp ab 85 % Speicher (Rest von B16). Beides hängt an deiner Entscheidung S1/S2.
- Die Aufräumregel läuft nicht von selbst; sie wird auf dem Server per Cron eingeplant (C18), nachdem einige Probeläufe angesehen wurden.
- `preflight.sh` ist nur in der Entwicklungsumgebung gelaufen, nicht auf einem Hetzner-Server.

**6. Nächster Schritt**

Alle zehn Erweiterungsphasen sind fertig. Weiter geht es mit deinen Entscheidungen (Stimme, TikTok-Weg, Speicher S1/S2) und den Freigaben für Server, R2 und Claude-Schlüssel. Danach Einrichtung nach [HETZNER_VORBEREITUNG.md](HETZNER_VORBEREITUNG.md), Abschnitt 6.

### Phase E9 – Bericht

**1. Was wurde erstellt?**

- **Erweiterter Abnahmetest** über die ganze Erweiterung: zwei Themenbereiche (Ernährung, Gaming) mit je zwei Kanälen, von der Idee über Redaktionsplan, Eigenproduktion, Mediathek, Freigabecenter und Strategie bis zum Mock-Beitrag. Die Regel „Ein Ernährungsvideo darf niemals versehentlich auf dem Gaming-Kanal veröffentlicht werden“ wird auf jeder Ebene geprüft, die sie brechen könnte, und am Ende noch einmal über die ganze Datenbank. Einstufung echt/simuliert je Schritt in [ACCEPTANCE_TEST.md](ACCEPTANCE_TEST.md).
- **Sicherheitsprüfung** aller neuen Endpunkte und Abläufe ([SECURITY.md](SECURITY.md), Abschnitt 11): Ein neuer Test liest alle 132 API-Routen ein und schlägt fehl, sobald eine Route ohne Rollenprüfung oder eine ändernde Route ohne CSRF-Schutz dazukommt. Weitere neue Tests: OAuth-Tokens erscheinen in keiner API-Antwort; KI-Textvorschläge können keine Aktionen, Kanäle oder Sichtbarkeit einschmuggeln und werden auf Plattformlängen gekürzt.
- **Zwei Befunde behoben:** Die Fehlermeldung beim R2-Upload konnte die signierte Adresse enthalten (jetzt neutrale Meldung). Der Link zum veröffentlichten Beitrag im Freigabecenter wird nur noch angezeigt, wenn er mit `https://` beginnt.
- **Abhängigkeiten:** `pip-audit` und `npm audit --omit=dev` ohne Befund.
- **Bedienungsanleitung** für die neuen Seiten mit der **gesammelten Liste offener Freigaben und Voraussetzungen**: [BEDIENUNGSANLEITUNG.md](BEDIENUNGSANLEITUNG.md).
- **Produktionscheckliste** an E8 angepasst: Instagram ohne Facebook-Seite (neue Punkte A15a Instagram-App, A15b R2), TikTok-Entwurf mit Scope `video.upload` (A16, A17 neu gefasst), KI-Entscheidung Claude mit 20 $/Monat (A19, A20), B19 erledigt.

**2. Geänderte Dateien**

- Neu: `backend/tests/acceptance/test_content_platform.py`, `backend/tests/unit/test_route_security.py`, `docs/BEDIENUNGSANLEITUNG.md`
- Geändert: `backend/services/r2.py`, `backend/tests/integration/test_approval.py`, `frontend/dashboard/ApprovalView.tsx`, `README.md`, `docs/{PROJECT_STATUS,SECURITY,ACCEPTANCE_TEST,PRODUCTION_CHECKLIST}.md`

**3. Durchgeführte Tests**

- Neuer Abnahmetest (echtes Rendern mit FFmpeg, Mock-KI, Mock-Veröffentlichung), Routen-Inventar, Token-Leck-Test, Test mit feindlicher KI-Ausgabe
- `scripts/test_backend.sh` (ruff, Format, mypy, alle Tests mit Abdeckung), `alembic check`, Frontend `typecheck` und `build`, E2E, `scripts/verify_phase1.sh`, `pip-audit`, `npm audit --omit=dev`

**4. Erfolgreiche Tests**

- 512 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund
- E2E: 26 Schritte bestanden
- `verify_phase1.sh`: 70 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- Alle Plattformwege sind nur gegen Attrappen und im Mock-Modus geprüft. Ob YouTube, Instagram und TikTok die Beiträge echt annehmen, zeigt sich erst mit eingerichteten Apps und deiner Freigabe.
- Offen bleiben die ⚠️-Punkte aus E8 (drei Instagram-Token-Adressen, TikTok-Entwurf ohne Audit) und die Entscheidung über eine echte Stimme.
- Zwei-Faktor-Anmeldung für Admins fehlt weiterhin (SECURITY.md, Abschnitt 10).

**6. Nächster Schritt**

Phase E10: Vorbereitung Hetzner (Speicherbedarf, Aufräumregeln, Checkliste je Plattform-App), nur Doku und Skripte, nichts wird bestellt oder deployt.

### Phase E8 – Bericht

**1. Was wurde erstellt?**

- **Freigabecenter** (neue Seite unter Steuerung): Ein fertiges Video aus der Mediathek wird für einen oder mehrere Kanäle **desselben Themenbereichs** vorbereitet. Je Kanal entsteht ein eigener Beitrag mit Titel, Beschreibung, Hashtags und Plattform-Optionen; die Texte schlägt die KI-Schicht vor (Haiku, im Mock aus Titel, Notiz und Tags der Datei). Du siehst Vorschau, technische Prüfung und den fertigen Posttext mit Zeichenzahl, änderst Texte und Optionen und gibst jeden Beitrag einzeln frei. Freigaben lassen sich zurückziehen (auch wenn der Beitrag schon eingeplant ist; der Auftrag wird dann storniert), nicht freigegebene Beiträge verwerfen.
- **Über die bestehende Maschine:** Beiträge sind Varianten mit `library_item_id` statt Clip. Sie starten nach der technischen Prüfung (Länge, Auflösung, Hochformat wo nötig, Datei lesbar) direkt bei „Qualität bestanden“ und durchlaufen die Clip-Pipeline nie. Erst deine Freigabe macht sie veröffentlichungsbereit; **Menge und Zeitpunkt entscheidet weiter der Strategie-Agent je Kanal**, nichts ist fest eingestellt. Die Gates prüfen bei jedem Schritt erneut: Video bereit, nicht archiviert, gleicher Themenbereich, Rechte bestätigt bzw. Eigenproduktion ohne Fremdvideo. Ein Beitrag kann technisch nicht auf einem Kanal eines anderen Bereichs landen (Prüfung beim Speichern und im Gate).
- **YouTube:** je Beitrag Sichtbarkeit (Standard privat), Short oder normales Video, geplanter Zeitpunkt über `publishAt` (setzt automatisch privat), „speziell für Kinder“, Kategorie; Hashtags gehen in Tags und Beschreibung. YouTube hat kein Shorts-Feld: Hochformat bis 3 Minuten wird automatisch ein Short.
- **TikTok als Entwurf (neuer Standard):** Das Video geht über den offiziellen Entwurfsweg (`inbox/video/init`, Scope `video.upload`) ins TikTok-Postfach; Text und Veröffentlichung machst du in der App. Direct Post bleibt als Option je Beitrag.
- **Instagram ohne Facebook-Seite:** neuer Weg „Instagram-Login“ (`graph.instagram.com`, Scopes `instagram_business_*`), mit eigener Verbindung, verschlüsseltem 60-Tage-Token und automatischer Verlängerung. Weil Meta das Video bei diesem Weg selbst abholen muss, wird es kurz in einen privaten Cloudflare-R2-Bucket gelegt und über eine signierte Adresse (15 Minuten gültig) bereitgestellt, danach gelöscht. **Dashboard und API bleiben privat.** Der alte Weg über eine Facebook-Seite bleibt mit `INSTAGRAM_LOGIN=facebook` erhalten.
- **Twitch:** im Freigabecenter steht offen, dass Twitch keine Upload-Schnittstelle hat.
- **API:** `GET /api/approval/info`, `GET /api/approval`, `POST /api/approval/suggest`, `POST /api/approval/prepare`, `PATCH /api/approval/{id}`, `POST /api/approval/{id}/approve|withdraw|discard`; neue Rückleitung `GET /api/oauth/instagram/callback`.

**2. Geänderte Dateien**

- Neu: `backend/services/{approval,instagram,r2}.py`, `backend/api/approval.py`, Migration `79004ffcd696_posts_from_library_videos`, `backend/tests/integration/test_approval.py`, `frontend/dashboard/ApprovalView.tsx`, `frontend/app/(dashboard)/freigabe/page.tsx`
- Geändert: `backend/models/production.py` (Variante: Clip optional, `library_item_id`, `hashtags`, `publish_options`, genau eine Quelle), `backend/core/{config,states}.py`, `backend/services/{gates,projects,strategy,workflow,publishers,tiktok,youtube,platform}.py`, `backend/agents/publishing_strategy.py`, `backend/api/{channels,analytics,production}.py`, `backend/app/main.py`, `backend/tests/integration/test_social_publishing.py`, `.env.example`, `frontend/lib/{api,types}.ts`, `frontend/components/AppShell.tsx`, `frontend/dashboard/ChannelsTable.tsx`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, `docs/{PROJECT_STATUS,API_INTEGRATIONS,ARCHITECTURE,AGENTS}.md`

**3. Durchgeführte Tests**

- 18 neue Tests, alle ohne echte Plattform (HTTP geht an Attrappen): Beitrag je Kanal mit technischer Prüfung; Dublette; falscher Themenbereich (auch direkt in der Datenbank); Querformat nur als normales YouTube-Video; fehlende Rechtebestätigung und Eigenproduktion mit Fremdvideo; Freigeben, Sperre nach Freigabe, Zurückziehen, Verwerfen, archiviertes Video; Clip-Agenten lehnen Mediathek-Beiträge ab; Strategie plant den Beitrag, Zurückziehen storniert, Mock-Veröffentlichung; YouTube-Upload mit Sichtbarkeit, Kategorie, Tags und Link; TikTok-Entwurf ohne Direct Post; Instagram-Login über signierte R2-Adresse mit Löschen danach; ohne R2 kein Versuch; Instagram-Verbindung, Verschlüsselung und Verlängerung; R2-Signatur gegen das offizielle AWS-Beispiel; Optionen und Hashtags; komplette API mit Rollen
- Bisherige Phase-13-Tests laufen jetzt ausdrücklich im Direct-Post- und Facebook-Seiten-Modus (beide Wege bleiben getestet)
- Migration hin und zurück, `alembic check`
- `scripts/test_backend.sh`, Frontend `typecheck` und `build`, E2E mit neuem Schritt „Freigabecenter“, `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 507 Backend-Tests bestanden (95 % Abdeckung); ruff, mypy und `alembic check` ohne Befund
- E2E: 26 Schritte bestanden (neu: „Freigabecenter“; der Verbindungsschritt prüft jetzt Instagram-Login und Facebook getrennt)
- `verify_phase1.sh`: 70 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- **Drei Instagram-Login-Seiten waren nicht automatisch abrufbar** (Code gegen Token, Langzeit-Token, Verlängerung). Die Adressen entsprechen Metas bekannter Doku, müssen aber vor dem ersten echten Verbinden im Browser bestätigt werden (in `API_INTEGRATIONS.md` markiert).
- Instagram-Login braucht Cloudflare R2. Solange R2 nicht eingerichtet ist, meldet ein Instagram-Kanal „nicht eingerichtet“; Kennzahlen über Instagram-Login sind noch nicht angebunden.
- TikTok-Entwürfe zählen als „veröffentlicht“, sobald sie im Postfach liegen; ob du sie in der App wirklich postest, sieht das System erst über die Kennzahlen. Höchstens 5 offene Entwürfe pro Tag.
- Freigabe-Modi je Bereich oder Kanal (z. B. „automatisch freigeben ab Qualitätswert X“) sind noch nicht eingebaut; jeder Mediathek-Beitrag braucht deine Freigabe.
- Clips aus der Gameplay-Pipeline laufen weiter ohne Freigabecenter direkt in die Strategie (wie bisher).
- Weiter offen aus E7: keine echte Stimme.

**6. Nächster Schritt**

Phase E9: Tests, Sicherheitsprüfung und Doku für die ganze Erweiterung (erweiterter Abnahmetest, Prüfung der neuen Endpunkte und Token-Speicherung).

### Phase E7 – Bericht

**1. Was wurde erstellt?**

- **Mediathek** (`library_items`, neue Seite unter Steuerung): eigene Videos (MP4, MOV, MKV), Bilder (PNG, JPEG, WebP) und Ton (MP3, WAV, M4A) je Themenbereich. Upload über den fortsetzbaren Upload (Verbraucher `library`) mit **Pflichtbestätigung „eigene Aufnahme“** je Datei; Bestätigungstext, Person und Zeit werden gespeichert. Die Datei wird geprüft (Länge, Auflösung, Bildrate, Format, lesbar) und inhaltsadressiert abgelegt; dieselbe Datei kann je Bereich nur einmal vorkommen.
- **Original bleibt, 9:16 kommt dazu:** Der neue Agent *Media Library* (Nr. 21) erzeugt Vorschaubild und Hochformat-Fassung (Video 1080×1920 bzw. 720×1280 mit unscharfem Hintergrund, Bild als 9:16-JPEG). Schon senkrechte H.264-Videos verwenden das Original; Videos über 3 Minuten behalten nur das Original (die Produktion schneidet daraus). Archivieren und Zurückholen statt Löschen; ein Bild, das ein offener Entwurf nutzt, lässt sich nicht archivieren.
- **Eigenproduktion ohne fremdes Video** (`own_productions`, neue Seite): Skript aus einer übernommenen Idee oder einem Thema über die KI-Schicht (Sonnet, im Mock ein festes Testskript), danach jeder Abschnitt änderbar (Überschrift, Sprechtext, Bild, Reihenfolge). Der neue Agent *Own Production* (Nr. 22) macht daraus: Stimme je Abschnitt → Zeitplan → Bild-/Textvideo (eigene Bilder aus der Mediathek **nur desselben Bereichs** oder Farbflächen, Überschrift oben) → Untertitel unten im sicheren Bereich, eingebrannt plus SRT/WebVTT → Video 1080×1920 H.264/AAC in der Mediathek als „selbst erzeugt“ mit Herkunftsnachweis.
- **Stimme:** Standard bleibt die stumme, kostenlose Teststimme. Nur Anbieter mit Freigabe für kommerzielle Nutzung werden angenommen; bezahlte Stimmen fragen vorher das Budget und werden gebucht. Eine echte Stimme (z. B. Piper lokal oder ein bezahlter Dienst) ist noch nicht eingebaut, siehe Punkt 5.
- **API:** `GET /api/library`, `GET/PATCH /api/library/{id}`, `GET /api/library/{id}/file?which=original|rendition|thumb`, `POST /api/library/{id}/archive|restore|reprocess`, `GET /api/library/info`; `GET/POST /api/productions`, `GET/PATCH/DELETE /api/productions/{id}`, `POST /api/productions/{id}/render`, `GET /api/productions/{id}/subtitles?fmt=srt|vtt`.

**Gemessene Renderzeiten** (lokal, 4 Kerne, ähnlich Hetzner CX33):

| Aufgabe | Dauer | Faktor |
|---|---|---|
| 9:16-Fassung eines 30-s-Videos 1080p (unscharfer Hintergrund) | 23–24 s | 1,3× Echtzeit |
| Eigenproduktion 39 s, 6 Abschnitte, 3 mit Bild, Untertitel | 19–20 s | 2× Echtzeit |
| Eigenproduktion 15,5 s im E2E-Test | 6,6 s | 2,4× Echtzeit |

Die Voreinstellung `RENDER_PRESET` ändert daran kaum etwas (ultrafast bis medium ±1 s); die Zeit steckt in Skalierung, Unschärfe und Untertiteln.

**2. Geänderte Dateien**

- Neu: `backend/models/library.py`, `backend/services/{library,own_production}.py`, `backend/agents/library.py`, `backend/api/library.py`, Migration `5487266eb759_media_library_and_own_production`, `backend/tests/integration/test_library.py`, `frontend/dashboard/{LibraryView,OwnProductionView}.tsx`, `frontend/app/(dashboard)/{mediathek,eigenproduktion}/page.tsx`
- Geändert: `backend/agents/registry.py`, `backend/services/{uploads,render,orchestrator}.py`, `backend/api/uploads.py`, `backend/app/{main,scheduler}.py`, `backend/core/{config,enums}.py`, `backend/models/__init__.py`, Agenten-Tests (jetzt 22 Agenten), `.env.example`, `frontend/lib/{api,types}.ts`, `frontend/components/{AppShell,icons}.tsx`, `frontend/dashboard/AgentsView.tsx`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, `docs/{PROJECT_STATUS,AGENTS,UPLOADS}.md`

**3. Durchgeführte Tests**

- 13 neue Tests mit echten, selbst erzeugten Testvideos und -bildern: Querformat-Upload → Original unverändert (SHA-256), 9:16-Fassung 720×1280, Vorschau, Dateiabruf; senkrechtes Video nutzt das Original; langes Video nur Original; Bild → 1080×1920; Upload ohne Bestätigung, für unbekannten Bereich oder mit falschem Typ abgelehnt; Dublette je Bereich, aber erlaubt in anderem Bereich; kaputte Datei; Rollen (Betrachter sieht, ändert nicht); Produktion vom Thema bis zum fertigen Video (Codecs, Länge, Untertitel-Dateien, Bild im Herkunftsnachweis, gemessene Renderzeit); Bild aus anderem Bereich wird abgelehnt; Produktion aus Idee nur im eigenen Bereich und nicht aus verworfener Idee; fehlende Stimme wird als Fehler festgehalten; KI kann keine Bilder wählen; Zeitplan und Überschriften-Spur
- Migration hin und zurück, `alembic check`
- Gefundener Fehler im Abnahmetest (nicht aus E7): Nach 21 Uhr Berliner Zeit hatte der Strategie-Agent für heute kein Zeitfenster mehr, der Test schlug abends fehl. Der Test entscheidet in dem Fall jetzt wie am Mittag desselben Tages.
- `scripts/test_backend.sh`, Frontend `typecheck` und `build`, E2E mit neuem Schritt „Mediathek und Eigenproduktion“ (Bild hochladen, Skript, Bild zuordnen, Video erzeugen), `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 489 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund
- E2E: 25 Schritte bestanden
- `verify_phase1.sh`: 69 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- **Noch keine echte Stimme.** Die Teststimme ist stumm; Videos haben eingebrannte Untertitel, aber keinen Ton. Vorschlag aus dem Plan: Piper lokal (kostenlos, Lizenz der jeweiligen Stimme vor dem Einbau prüfen) oder ein bezahlter Anbieter nach Kostenvergleich. Das entscheidest du.
- Fertige Videos sind noch nicht veröffentlichbar: Aus Mediathek-Videos werden erst im Freigabecenter (E8) Beiträge für Kanäle.
- Ein erneutes Rendern nach Änderungen legt ein weiteres Video in der Mediathek an; das alte bleibt, bis du es archivierst.
- Bilder werden als Standbild gezeigt (kein Zoom oder Schwenk), Übergänge sind harte Schnitte.
- Eigene Gameplay-Aufnahmen aus der Mediathek gehen noch nicht in die bestehende Gameplay-Produktion; für Spielszenen gilt weiter die Rechteprüfung mit Publisher-Richtlinie.

**6. Nächster Schritt**

Phase E8: Freigabecenter und Plattformen (Texte je Plattform, Vorschau, Termin, Freigabe; Instagram Login, TikTok als Entwurf, YouTube Shorts und Video, Twitch ehrlich ohne Upload).

### Phase E6 – Bericht

**1. Was wurde erstellt?**

- **Redaktionsplan wirkt auf die Publishing-Strategie:** Hat ein Tag Einträge, planen nur Kanäle der eingetragenen Themenbereiche an diesem Tag Videos; schon geplante, noch nicht fällige Videos anderer Bereiche werden mit Begründung zurückgenommen. Ein Tag ohne Eintrag bleibt für alle offen (bisheriges Verhalten). **Die Menge je Kanal bleibt dynamisch** beim Strategie-Agenten, der Plan setzt keine Zahl.
- **Schwerpunkte zählen bei der Auswahl:** Videos, deren Spiel oder Titel zu einem aktiven Schwerpunkt passt (z. B. „GTA 6“), bekommen einen kleinen Vorrang (+0,1 auf den Qualitätswert) und die Begründung „Schwerpunkt GTA 6“ in der Entscheidung.
- **Kalender-API:** `GET /api/planning/calendar` (Woche oder Monat, bis 62 Tage, je Tag Einträge und die geplanten Videos aus der Strategie), `POST/PATCH/DELETE /api/planning/days` (einplanen, verschieben, Notiz, entfernen), `POST/DELETE /api/planning/focus`.
- **Seite „Redaktionsplan“** (Steuerung): Wochen- und Monatsansicht, blättern, Filter je Bereich, „+“ je Tag zum Einplanen, Einträge per Ziehen oder über ein Bearbeitungsfeld verschieben, Notizen, entfernen, geplante Videos mit Uhrzeit, Kanal und Status, Schwerpunkte setzen und entfernen; auf dem Handy als Liste.

**2. Geänderte Dateien**

- Neu: `backend/api/calendar.py`, `backend/tests/integration/test_calendar.py`, `frontend/dashboard/CalendarView.tsx`, `frontend/app/(dashboard)/redaktionsplan/page.tsx`
- Geändert: `backend/services/{planning,strategy}.py`, `backend/agents/publishing_strategy.py`, `backend/app/main.py`, `frontend/lib/{api,types}.ts`, `frontend/components/{AppShell,icons}.tsx`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, `docs/{PROJECT_STATUS,AGENTS}.md`

**3. Durchgeführte Tests**

- 8 neue Tests: Tag für anderen Bereich verplant → keine Posts, Menge trotzdem aus den Daten; Tag für den eigenen Bereich → normal; Planänderung nimmt geplante Posts zurück; Schwerpunkt gewinnt gegen etwas höhere Qualität; Tag ohne Eintrag offen; Kalender mit Einträgen, Videos und Filter, Zeitraum-Grenze; Einplanen, Dublette, Verschieben, Konflikt beim Verschieben, Notiz, zu weit voraus, Entfernen, Rollen; Schwerpunkt anlegen, ungültiger Zeitraum, löschen
- Alle bisherigen Strategie-Tests unverändert grün
- `scripts/test_backend.sh`, Frontend `typecheck` und `build`, E2E mit neuem Schritt „Redaktionsplan“, `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 476 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund (keine Schemaänderung)
- E2E: 24 Schritte bestanden
- `verify_phase1.sh`: 69 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- Der Plan gilt je Kalendertag in der Zeitzone des Kanals; Kanäle in anderen Zeitzonen sehen den Tag versetzt.
- Ziehen und Ablegen funktioniert mit der Maus; auf dem Handy wird über das Bearbeitungsfeld verschoben.
- Einzelne Videos lassen sich im Kalender noch nicht verschieben; das kommt mit dem Freigabecenter (E8), wo Termine je Video gesetzt werden.

**6. Nächster Schritt**

Phase E7: Mediathek (Upload, Erkennung von Länge, Auflösung und Format, Hochformat-Fassungen, Original bleibt erhalten) und Eigenproduktion ohne Fremdvideo (Skript → Stimme → Bild-/Textvideo → Untertitel).

### Phase E5 – Bericht

**1. Was wurde erstellt?**

- **Recherche-Quellen je Themenbereich** (`research_sources`): RSS- und Atom-Feeds, im Ideenlabor vom Admin anzulegen, ein- und auszuschalten. Abruf mit Schutz gegen interne Ziele (auch nach Weiterleitungen), Größen- und Zeitlimit, sicherem XML-Parser (`defusedxml`, neue Abhängigkeit) und entferntem HTML. Im Testmodus (Standard) kein Netzabruf, sondern Beispiel-Feeds aus den Unterthemen des Bereichs.
- **Zwei neue Agenten** (jetzt 20): *Research* sammelt Einträge (`research_items`, ohne Dubletten), *Idea Lab* macht daraus bewertete Ideen (`ideas`) mit Quellenliste, Format und Begründung. Beide laufen in einer **eigenen Queue `research`**, damit Recherche nie die Produktion aufhält, und im Zeitplan (Recherche alle 6 h, Ideen täglich).
- **Bewertung im Code statt durch die KI:** Trend, Passung (Schwerpunkt aus dem Chat zählt), Aufwand und Rechte-Risiko mit fester, sichtbarer Formel. Die KI schreibt nur Titel und Beschreibung und nennt die genutzten Einträge; ungültige oder doppelte Vorschläge werden verworfen.
- **Schutz vor Anweisungen in Feeds:** Feed-Text steht im Prompt als markiertes Material mit dem Hinweis, darin keine Anweisungen zu befolgen; der Ideen-Schritt hat keine Werkzeuge und kann weder Plan noch Produktion ändern.
- **Ideenlabor** (neue Seite unter Steuerung): Ideen nach Bereich und Status, Punktzahl, Balken je Kriterium, Begründung, Quellen-Links, „Übernehmen“ (optional mit Tag, dann steht der Bereich an dem Tag im Redaktionsplan), „Verwerfen“, „Wieder öffnen“; Quellenverwaltung, neueste Einträge und „Recherche starten“ (Admin).
- **Chat:** „Recherchiere für Ernährung“ startet Recherche und Ideenlabor für jeden Bereich (bei Gaming zusätzlich die Trendrecherche), „Zeig mir die Ideen“ listet die besten offenen Ideen.
- **API:** `GET/POST /api/research/sources`, `PATCH/DELETE /api/research/sources/{id}`, `GET /api/research/items`, `POST /api/research/run`, `GET /api/ideas`, `POST /api/ideas/{id}/accept|reject|reopen`.

**2. Geänderte Dateien**

- Neu: `backend/models/research.py`, `backend/services/{research,ideas}.py`, `backend/agents/research.py`, `backend/api/research.py`, Migration `e7ef1942573e_research_and_idea_lab`, `backend/tests/integration/test_research.py`, `frontend/dashboard/IdeasView.tsx`, `frontend/app/(dashboard)/ideen/page.tsx`
- Geändert: `backend/agents/registry.py`, `backend/services/{assistant,orchestrator,queue}.py`, `backend/app/{main,scheduler}.py`, `backend/api/agents.py`, `backend/core/{config,enums}.py`, `backend/models/__init__.py`, `backend/pyproject.toml`, Tests zu Agenten und Assistent, `.env.example`, `frontend/lib/{api,types}.ts`, `frontend/components/{AppShell,icons}.tsx`, `frontend/dashboard/{AgentsView,ChatView}.tsx`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, `docs/{PROJECT_STATUS,AGENTS,API_INTEGRATIONS}.md`

**3. Durchgeführte Tests**

- 24 neue Tests mit festen Feeds: RSS und Atom (Bereinigung, relative Links, `javascript:`-Links verworfen), kaputtes XML und Entity-Bombe abgelehnt, interne Ziele (localhost, 10.x, 169.254.x, ::1, gemischt) abgelehnt, Weiterleitung auf internes Ziel abgelehnt, Größenlimit, Mock-Sammeln ohne Dubletten, Live-Sammeln mit Fehlerquelle und ausgeschalteter Quelle, Testideen mit Schwerpunkt-Bewertung, Formel der Bewertung, Claude-Antwort mit ungültiger Quelle und Dublette (nachgebauter Client, keine Werkzeuge im Aufruf), beide Agenten über den Orchestrator, eigene Queue, API (Rollen, Adressprüfung, Dublette, Übernehmen mit Plantag, Verwerfen, Wieder öffnen, pausierter Bereich, Start der Recherche); Chat-Tests für Recherche je Bereich und Ideenliste
- `alembic upgrade`, `downgrade -1`, erneut `upgrade`, `alembic check`
- `scripts/test_backend.sh`, Frontend `typecheck` und `build`, E2E mit neuem Schritt „Ideenlabor“, `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 468 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund
- E2E: 23 Schritte bestanden
- `verify_phase1.sh`: 69 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- Kein echter Feed-Abruf und kein echter Claude-Aufruf; beides erst nach Freigabe (`RESEARCH_SOURCES_MODE=live`, Claude-Schlüssel).
- Es sind noch keine echten Feeds eingetragen; welche Quellen je Bereich sinnvoll sind, legt der Betreiber fest.
- DNS-Rebinding ist nur durch die Adressprüfung abgedeckt; auf dem Server sollte die Firewall ausgehende Verbindungen in interne Netze zusätzlich sperren (E10).
- Übernommene Ideen setzen nur den Bereich auf den Plan; die Produktion aus einer Idee kommt mit E7.

**6. Nächster Schritt**

Phase E6: Redaktionskalender (Woche und Monat, Einträge verschieben) und Anbindung an den Publishing-Strategie-Agenten, der die Menge weiter selbst bestimmt.

### Phase E4 – Bericht

**1. Was wurde erstellt?**

- **Chat-Assistent** (`services/assistant.py`, Seite „Assistent“ als zweiter Eintrag unter Steuerung): Den Plan in normalem Deutsch ändern. Der Assistent arbeitet nur über fünf fest definierte Werkzeuge: Überblick lesen, Schwerpunkt setzen („diese Woche GTA 6“), Tag einplanen oder herausnehmen („Mittwoch zusätzlich Ernährung“, „Freitag kein Gaming“), Themenbereich pausieren oder fortsetzen (nur Admin), Trendrecherche starten (nur Admin, bisher nur Gaming).
- **Kein Werkzeug zum Veröffentlichen.** Bitten darum lehnt der Assistent ab und verweist auf die Seite Veröffentlichung, die Sicherheitsprüfungen und die Freigabe. Ein Test stellt sicher, dass kein Werkzeug „publish“, „post“ oder „upload“ heißt.
- **Aktionskarten mit Rückgängig:** Jede Änderung wird als Karte mit Status (ausgeführt, rückgängig gemacht, nicht ausgeführt) gespeichert, samt dem vorherigen Zustand. „Rückgängig“ stellt ihn wieder her (einmal, nur eigene Aktionen; Status von Themenbereichen nur Admin). Jede Aktion steht zusätzlich im Audit-Log.
- **Zwei Modi:** Im Mock-Modus (Standard, kostenlos) versteht eine feste Befehlserkennung die üblichen Sätze, auch mehrere Sätze in einer Nachricht. Mit Claude läuft Sonnet 5.5 in einer Werkzeug-Schleife (höchstens 4 Runden, 12 Aktionen je Nachricht); jede Runde geht durch die KI-Schicht und zählt gegen die 20-$-Grenze. Ist Claude gewählt, aber gesperrt (z. B. kein Schlüssel), sagt der Assistent das und nutzt sichtbar die Befehlserkennung.
- **Redaktionsplan-Daten** (`services/planning.py`, Tabellen `editorial_days` und `content_focus`): welcher Themenbereich an welchem Tag läuft und welche Themen Vorrang haben. Die Menge der Videos legt weiterhin der Publishing-Strategie-Agent fest; der Plan bestimmt nur Themen und Tage. Wochenansicht neben dem Chat und `GET /api/planning/week`.
- **Chatverlauf** je Nutzer (`chat_messages`, `chat_actions`); an Claude gehen nur die letzten 10 Nachrichten als reiner Text.
- **KI-Schicht erweitert:** Werkzeug-Definitionen, Inhaltsblöcke und Stop-Grund werden durchgereicht; die Blöcke einer Antwort gehen innerhalb einer Runde unverändert zurück.
- **API:** `GET/POST /api/assistant/messages` (Schreiben ab Operator), `POST /api/assistant/actions/{id}/undo`, `GET /api/planning/week`.

**2. Geänderte Dateien**

- Neu: `backend/services/{assistant,planning}.py`, `backend/models/{assistant,planning}.py`, `backend/api/assistant.py`, Migration `7e4806afbb52_assistant_and_editorial_plan`, `backend/tests/integration/test_assistant.py`, `frontend/dashboard/ChatView.tsx`, `frontend/app/(dashboard)/assistent/page.tsx`
- Geändert: `backend/services/ai.py`, `backend/core/enums.py`, `backend/models/__init__.py`, `backend/app/main.py`, `frontend/lib/{api,types}.ts`, `frontend/components/{AppShell,icons}.tsx`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, `docs/{PROJECT_STATUS,API_INTEGRATIONS,CONTENT_PLATFORM_PLAN}.md`

**3. Durchgeführte Tests**

- 20 neue Tests: Rollen, kein Veröffentlichungswerkzeug, Ablehnung beim Veröffentlichen, Hilfetext, jedes Werkzeug im Mock (Überblick, Schwerpunkt diese und nächste Woche, Tag einplanen/herausnehmen/doppelt, mehrere Tage und Bereiche, Datum zu weit voraus, pausierter Bereich, Status nur Admin, Recherche nur Gaming), Rückgängig (einmalig, nur eigene), Verlauf je Nutzer, Satzerkennung, Claude-Schleife mit nachgebautem Client (Werkzeugaufruf, Ergebnis zurück, System-Prompt bleibt gleich, zwei Aufrufe gebucht), Verlauf nur als Text, Werkzeugfehler gehen an das Modell, gesperrtes Claude fällt sichtbar auf die Befehlserkennung zurück
- `alembic upgrade`, `downgrade -1`, erneut `upgrade`, `alembic check`
- `scripts/test_backend.sh`, Frontend `typecheck` und `build`, E2E mit neuem Schritt „Plan per Chat ändern“, `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 443 Backend-Tests bestanden (96 % Abdeckung); ruff, mypy und `alembic check` ohne Befund
- E2E: 22 Schritte bestanden
- `verify_phase1.sh`: 69 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- Kein echter Claude-Aufruf; die Werkzeug-Schleife ist nur mit einem nachgebauten Client getestet.
- Die Befehlserkennung im Mock-Modus versteht nur typische Sätze; alles andere beantwortet sie mit einer Hilfeliste.
- Der Redaktionsplan wird bisher nur gespeichert und angezeigt. Ideenlabor (E5) und Kalender (E6) nutzen ihn; die Produktion richtet sich ab E6/E7 danach.
- Trendrecherche gibt es bisher nur für Gaming; Recherche für andere Bereiche kommt mit E5.

**6. Nächster Schritt**

Phase E5: Recherche und Ideenlabor je Themenbereich (Ideen mit Begründung, Bewertung, Übernahme in den Plan), im Mock-Modus mit Beispieldaten.

### Phase E3 – Bericht

**1. Was wurde erstellt?**

- **KI-Schicht** (`services/ai.py`): ein Einstieg für alle KI-Aufrufe mit zwei Stufen. „Kurze Texte“ (Titel, Beschreibungen, Hooks) laufen über Claude Haiku 5.5, „Chat, Ideen, Planung“ über Claude Sonnet 5.5. Beide Modelle sind per Umgebungsvariable austauschbar.
- **Zwei Anbieter:** „Test (Mock)“ ist Standard, ohne Netz und ohne Kosten; spätere Phasen liefern dafür passende Beispieldaten. „Claude“ nutzt das offizielle SDK `anthropic` und ruft nur auf, wenn alles zutrifft: Anbieter „Claude“ gewählt, API-Schlüssel auf dem Server, `PAID_API_CALLS_ENABLED=true`, kein Not-Aus, Euro-Budget frei. Fehlt etwas, wird der Aufruf blockiert und protokolliert, nie still durch Testdaten ersetzt.
- **Harte Monatsgrenze 20 $:** Vor jedem echten Aufruf wird der ungünstigste Preis (geschätzter Prompt plus alle erlaubten Ausgabe-Tokens) unter einer Datenbanksperre reserviert. Passt er nicht mehr unter die Grenze, wird nichts gesendet. Danach ersetzt der echte Verbrauch die Reservierung. Hängen gebliebene Reservierungen (Absturz) werden nach 30 Minuten mit dem reservierten Betrag abgeschlossen, damit die Grenze nie zu niedrig rechnet. Im Dashboard lässt sich die Grenze nur senken, nie über `AI_MONTHLY_CAP_USD_MAX` (20 $) heben.
- **Kostenbuchung:** jeder Aufruf (auch Mock und blockierte) als Zeile in `ai_calls` mit Zweck, Modell, Tokens, Kosten in Dollar und Themenbereich; echte Kosten zusätzlich in Euro in `costs` (Kategorie KI) und damit im Monatsbudget.
- **Sicherungen bei Claude:** kurzer Aufwand (`effort=low`) als Standard, Obergrenzen für Prompt (60.000 Zeichen) und Antwort (16.000 Tokens), Ablehnungen werden erkannt und gebucht; bei Sonnet 5.5 springt bei einer Sicherheitsablehnung automatisch Sonnet 5 zum gleichen Preis ein.
- **API:** `GET /api/ai/status`, `GET /api/ai/usage`, `POST /api/ai/test` (nur Admin). Einstellung `ai_monthly_cap_usd` in den Betriebseinstellungen; der KI-Anbieter ist dort jetzt wählbar.
- **Dashboard:** neuer Bereich „KI-Nutzung (Claude)“ auf der Kostenseite (Modus, Verbrauch gegen die Grenze, Modelle mit Preisen, Schlüssel- und Freigabestatus, Verbrauch nach Zweck, letzte Aufrufe, Testaufruf). Unter Einstellungen Auswahl des Anbieters und Feld für die Monatsgrenze.

**2. Geänderte Dateien**

- Neu: `backend/services/ai.py`, `backend/models/ai.py`, `backend/api/ai.py`, Migration `7edd378c8370_ai_calls`, `backend/tests/integration/test_ai.py`, `frontend/dashboard/AIUsagePanel.tsx`
- Geändert: `backend/core/{config,enums}.py`, `backend/models/__init__.py`, `backend/services/controls.py`, `backend/api/settings.py`, `backend/app/main.py`, `backend/pyproject.toml` (Abhängigkeit `anthropic`), `backend/tests/integration/test_auth.py`, `.env.example`, `frontend/lib/{api,types}.ts`, `frontend/dashboard/{CostsView,OperationsForm}.tsx`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, `docs/{PROJECT_STATUS,API_INTEGRATIONS}.md`

**3. Durchgeführte Tests**

- 21 neue Tests mit einem nachgebauten Claude-Client (kein echter Aufruf): Preisrechnung inkl. Haiku über 100.000 Tokens, Mock ist Standard und kostenlos, Mock-Daten des Aufrufers, Grenzen für Prompt und Antwort, Blockade ohne Schlüssel, ohne Freigabe, bei Not-Aus und bei leerem Euro-Budget, echter Aufruf wird gebucht (Dollar und Euro), Sonnet mit Rückfallmodell, Ablehnung, API-Fehler ohne Kosten, Grenze nie über Server-Maximum, Aufruf über der Grenze wird nicht gesendet, Verbrauch plus Reservierung zählen, alte Reservierungen, API (Status, Verbrauch, Testaufruf, 409 ohne Schlüssel, Grenze über Maximum abgelehnt, Rollen)
- `alembic upgrade`, `downgrade -1`, erneut `upgrade`, `alembic check`
- `scripts/test_backend.sh`, Frontend `typecheck`, `build`, E2E mit neuem Schritt „KI-Schicht“, `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 423 Backend-Tests bestanden; ruff, mypy und `alembic check` ohne Befund
- E2E: 21 Schritte bestanden
- `verify_phase1.sh`: 69 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- Es wurde **kein echter Claude-Aufruf** gemacht; das passiert erst, wenn der Betreiber einen API-Schlüssel hinterlegt und kostenpflichtige Aufrufe freigibt. Empfehlung: in der Anthropic-Konsole zusätzlich ein Ausgabenlimit von 20 $ setzen (zweite Sicherung).
- Die Kostenschätzung vor dem Aufruf ist bewusst grob (3 Zeichen je Token); sie rechnet eher zu hoch.
- Der Script & Hook Agent nutzt weiter die Vorlagen; bei Auswahl „Claude“ meldet er „nicht angebunden“ und bleibt bei der Vorlage. Die KI-Texte für Videos werden mit der Eigenproduktion (E7) über die neue Schicht angebunden.
- Preise sind Stand 03.11.2026 und im Code hinterlegt; vor der Freischaltung gegen die aktuelle Preisliste prüfen.
- Behoben nebenbei: Der Test „manipuliertes Token“ setzte das Cookie doppelt; mit der neuen HTTP-Bibliothek `httpx2` (kommt mit dem SDK) wurde dabei das gültige Cookie mitgeschickt.

**6. Nächster Schritt**

Phase E4: Chat-Assistent, der den Plan per natürlicher Sprache ändert („diese Woche GTA 6“, „Mittwoch Ernährung“), mit Aktionskarten, Rückgängig und Verlauf; im Mock-Modus mit festen Beispielantworten.

### Phase E2 – Bericht

**1. Was wurde erstellt?**

- **Dark Mode als Standard:** neue Farbpalette (dunkle Flächen, Akzent Violett, Statusfarben für OK, Warnung, Fehler, Info). Über das Sonnen-/Mond-Symbol oben rechts lässt sich auf Hell umschalten; die Wahl wird nur in diesem Browser gespeichert, ohne Aufblitzen beim Laden.
- **Navigation links** mit Symbolen und Gruppen „Steuerung“ (Übersicht, Themenbereiche), „Engine“ (Agenten, Rechte, Videoproduktion, Publishing, Analytics, Kosten) und „System“ (System, Einstellungen), Benutzer unten. Auf Handy und Tablet (unter 900 px) klappt sie als Seitenmenü über den Menüknopf auf (schließt mit Escape, Klick daneben oder Seitenwechsel). Keine Platzhalter-Einträge für spätere Phasen; Chat, Ideenlabor, Redaktionsplan usw. kommen mit ihren Phasen dazu. Alle bestehenden Seiten bleiben unverändert erreichbar.
- **Neue Startseite** (aktualisiert sich alle 30 s, solange sie sichtbar ist, plus Knopf „Jetzt aktualisieren“):
  - Kennzahlen: Videos gesamt, veröffentlicht, geplant, unveröffentlicht, fehlgeschlagen, aktive Kanäle, Kosten des Monats.
  - Statusleiste aller Videos mit Entwurf, In Bearbeitung, Bereit zur Veröffentlichung, Geplant, Wird hochgeladen, Veröffentlicht, Fehlgeschlagen.
  - Plattformkacheln YouTube, Twitch, Instagram, TikTok mit Verbindungsstatus, verbundenen Kanälen, Veröffentlichungen, Testläufen (Mock-Posts getrennt gezählt), offenen und fehlgeschlagenen Aufträgen und letzter Veröffentlichung. **Twitch** ist ehrlich als Datenquelle gekennzeichnet („Videos können nicht zu Twitch hochgeladen werden“), mit Status Testdaten/aktiv/Fehler.
  - Letzte Veröffentlichungen (mit Themenbereich, Test/Live), Fehler (Produktion und Veröffentlichung mit Fehlermeldung), Aktivitäten (Audit-Log und Agentenläufe auf Deutsch; fehlgeschlagene Anmeldungen und IP-Adressen werden nicht angezeigt), Systemstatus und aktuelle Trends.
- **API:** `GET /api/overview/dashboard` liefert alles für die Startseite in einer Anfrage; `GET /api/overview` bleibt unverändert.
- Plattform-Symbole sind schlichte eigene Zeichen in Markenfarbe, keine offiziellen Logos.

**2. Geänderte Dateien**

- Neu: `backend/tests/integration/test_dashboard.py`, `frontend/components/icons.tsx`, `frontend/lib/theme.ts`
- Geändert: `backend/api/overview.py`, `frontend/components/{AppShell,ui}.tsx`, `frontend/dashboard/OverviewView.tsx`, `frontend/app/{layout.tsx,globals.css,login/page.tsx}`, `frontend/lib/{api,types}.ts`, `frontend/e2e/smoke.mjs`, `docs/PROJECT_STATUS.md`

**3. Durchgeführte Tests**

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest inkl. Abnahmetest); 4 neue Tests: Anmeldung nötig, leeres Dashboard (Reihenfolge der Status, Twitch ohne Upload), Zählung von Status, Upload, Testposts, Fehlern und Aktivitäten, keine fehlgeschlagenen Anmeldungen in den Aktivitäten
- Frontend `typecheck`, `build`, Playwright-E2E (Startseite prüft jetzt zusätzlich alle vier Plattformkacheln, den Twitch-Hinweis und die Statusleiste)
- Screenshots in drei Breiten (1440, 820, 390 px) und mobiles Menü; kein waagerechtes Scrollen
- `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 402 Backend-Tests bestanden; ruff und mypy ohne Befund
- E2E: 20 Schritte bestanden
- `verify_phase1.sh`: 68 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- Die Unterseiten (Agenten, Rechte usw.) haben das neue Farbschema und die neue Navigation, aber noch ihr bisheriges Layout; sie werden mit den Phasen, die sie betreffen, überarbeitet.
- Die Startseite zeigt noch keine Kennzahlen je Themenbereich und keinen Wochenkalender; der Kalender kommt mit dem Redaktionsplan (E6), das Freigabecenter mit E8.
- „Wird hochgeladen“ zählt laufende Veröffentlichungsaufträge; ein Video kann dabei gleichzeitig als „Geplant“ zählen.

**6. Nächster Schritt**

Phase E3: KI-Schicht (Mock-Anbieter und Claude, Budget-Obergrenze 20 $/Monat, Kostenbuchung je Aufruf). Ohne hinterlegten und freigegebenen API-Schlüssel bleibt alles im Mock-Modus.

### Phase E1 – Bericht

**1. Was wurde erstellt?**

- **Themenbereiche** (Tabelle `content_projects`): Name, Beschreibung, Sprachen, Zielgruppe, Tonalität, Unterthemen, Priorität, Status (aktiv, pausiert, archiviert). Gaming ist per Migration der erste Bereich (Standard); alle vorhandenen Kanäle, Materialien, Videos, Aufträge und Beiträge gehören ihm.
- **Kanalzuordnung:** Jeder Kanal gehört zu genau einem Themenbereich. Neue Kanäle (z. B. „YouTube Ernährung“) lassen sich anlegen; sie starten pausiert, nicht verbunden, Obergrenze 0. Ein Kanal kann den Bereich nur wechseln, solange er keine Videos oder Beiträge hat.
- **Harte Sperre, dreifach:**
  1. Datenbank: zusammengesetzte Fremdschlüssel (Kanal-ID + Themenbereich) auf `variants`, `publishing_jobs` und `posts`. Selbst ein direkter SQL-Befehl kann ein Video nicht auf den Kanal eines anderen Bereichs legen.
  2. Code: Vor jedem Speichern füllt `services/projects.py` den Bereich aus Kanal bzw. Video und lehnt ein Video ab, dessen Ausgangsmaterial zu einem anderen Bereich gehört als der Kanal (`ProjectMismatchError`).
  3. Gates: Pausierte oder archivierte Bereiche stoppen Produktion und Veröffentlichung; zusätzlich Vergleich Material ↔ Video ↔ Kanal vor jedem Schritt. Der Publishing Strategy Agent plant für Kanäle eines inaktiven Bereichs nichts.
- **Neue Videos** starten nur auf Kanälen des Themenbereichs ihres Materials. Material wird beim Registrieren/Hochladen einem Bereich zugeordnet (ohne Angabe: Gaming).
- **API:** `GET/POST /api/projects`, `GET/PATCH /api/projects/{id}`, `POST /api/channels`, `PUT /api/channels/{id}/project`; `content_project_id` bei Material (auch im fortsetzbaren Upload). Alle Änderungen im Audit-Log.
- **Dashboard:** neue Seite „Themenbereiche“ (Karten mit Kennzahlen, Unterthemen, Bearbeiten, Pausieren/Archivieren, Kanäle je Bereich, Kanal anlegen); Spalte „Themenbereich“ in der Kanaltabelle der Einstellungen.

**2. Geänderte Dateien**

- Neu: `backend/models/projects.py`, `backend/services/projects.py`, `backend/api/projects.py`, Migration `9fbc1a219fbe_content_projects`, `backend/tests/integration/test_projects.py`, `frontend/dashboard/ProjectsView.tsx`, `frontend/app/(dashboard)/themenbereiche/page.tsx`, `docs/CONTENT_PLATFORM_PLAN.md`
- Geändert: `backend/core/enums.py`, `backend/models/{__init__,channels,production,publishing}.py`, `backend/services/{gates,seed}.py`, `backend/agents/{gameplay_analysis,creative_director,publishing,publishing_strategy}.py`, `backend/api/{channels,rights,schemas}.py`, `backend/app/main.py`, `frontend/lib/{api,types}.ts`, `frontend/components/AppShell.tsx`, `frontend/dashboard/ChannelsTable.tsx`, `frontend/app/globals.css`, `frontend/e2e/smoke.mjs`, `docs/{PROJECT_STATUS,ARCHITECTURE}.md`

**3. Durchgeführte Tests**

- `scripts/test_backend.sh` (ruff, mypy --strict, pytest) inkl. Abnahmetest
- 17 neue Tests: Standardbereich und Bestandsdaten, Vererbung des Bereichs, Ernährungsvideo auf Gaming-Kanal (auch mit ausdrücklich falschem Bereich, beim Umhängen und per direktem SQL), Auftrag auf fremdem Kanal, Kanalauswahl neuer Videos, Gate bei pausiertem Bereich, Strategieplanung bei pausiertem Bereich, API (Anlegen, Doppelname, Kanal anlegen, Umhängen nur leerer Kanäle, Standardbereich nicht archivierbar, archivierter Bereich ohne neue Kanäle, Rollen, Material mit Bereich)
- `alembic upgrade`, `downgrade -1`, erneut `upgrade` und `alembic check`
- Frontend `typecheck`, `build`, Playwright-E2E mit neuem Schritt „Themenbereiche“
- `scripts/verify_phase1.sh`

**4. Erfolgreiche Tests**

- 398 Backend-Tests bestanden; ruff, mypy und `alembic check` ohne Befund
- E2E: 20 Schritte bestanden
- `verify_phase1.sh`: 68 bestanden, 0 fehlgeschlagen

**5. Bestehende Fehler / Einschränkungen**

- Trends und Spiele sind noch nicht Themenbereichen zugeordnet (Recherche je Bereich kommt in Phase E5).
- Modus je Bereich (nur sammeln / mit Freigabe / automatisch) und Not-Aus je Kanalebene folgen mit dem Freigabecenter (E8); heute wirkt „pausiert“ als Stopp je Bereich.
- Das Dashboard hatte noch das bisherige Design (erledigt in Phase E2).

**6. Nächster Schritt**

Phase E2: Dashboard-Grundstruktur und Design im Dark Mode (Navigation links, Startseite mit Kennzahlen, Plattformkacheln, Statuschips, responsive), bestehende Seiten unter „Engine“.

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
| 15.11.2026 | Mediathek-Beiträge als Varianten mit `library_item_id` über die bestehende Strategie und Veröffentlichung (Plan 5.3) | Eine Maschine für Clips und eigene Videos; Menge bleibt dynamisch, Gates und Mock-Schutz gelten unverändert |
| 15.11.2026 | Jeder Mediathek-Beitrag braucht eine menschliche Freigabe; YouTube standardmäßig privat, TikTok standardmäßig als Entwurf | Nichts geht ungeprüft raus; Entwurf ist der sicherste offizielle TikTok-Weg ohne Audit |
| 15.11.2026 | Instagram-Login holt das Video über eine signierte, 15 Minuten gültige R2-Adresse | Meta erlaubt dort nur `video_url`; Dashboard und API bleiben privat |

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
