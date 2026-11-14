# Agenten

18 Agenten mit klar abgegrenzten Aufgaben (Spezifikation Abschnitt 6). Alle Agenten laufen im Worker-Prozess, kommunizieren ausschließlich über Backend und Warteschlange und protokollieren jeden Lauf in `agent_runs` sowie jede Entscheidung in `agent_decisions`.

## Gemeinsamer Vertrag (umgesetzt in Phase 4)

Code: `backend/agents/base.py`, Registry `backend/agents/registry.py`.

| Element | Beschreibung |
|---|---|
| `AgentSpec` (Registry) | Name, Nummer, Titel, Beschreibung, Phase, Kostenart (`local`, `free_api`, `paid`), Pipeline-Stufe (Entität + Status), Produktionsagent ja/nein |
| `Agent.run(ctx, payload) -> AgentResult` | Ein Arbeitsschritt; idempotent bezogen auf den Job-Schlüssel |
| `ctx.decide(...)` | Entscheidung mit Eingaben und Begründung in `agent_decisions` |
| `ctx.authorize_cost(eur)` | Vor jedem kostenpflichtigen Aufruf; wirft `BudgetExceededError`, wenn das Budget oder `PAID_API_CALLS_ENABLED` es verbietet |
| `ctx.add_cost(eur, kategorie)` | Tatsächliche Kosten in `costs`, verknüpft mit dem Lauf |
| Statuswechsel | nur über `services/workflow.py` |

**Ablauf eines Jobs** (`services/orchestrator.py`): Der Master reiht pro wartender Entität einen Job mit festem Schlüssel `agent-<agent>-<entität>-<id>-<status>` ein (kein doppeltes Einreihen). Der Worker prüft vor der Ausführung erneut alle Gates, legt einen `agent_run` an, führt den Agenten aus und bucht das Ergebnis. Ist ein Gate zu, wird der Lauf als `skipped` mit Grund gespeichert. Wirft der Agent einen Fehler, wird der Lauf `failed` und die Entität `FAILED` (mit Schritt und Meldung); eine Budget-Ablehnung zählt als `skipped`, nicht als Fehler.

**Gates** (`services/gates.py`), in dieser Reihenfolge: Not-Aus → Agent in dieser Phase umgesetzt → Agent nicht pausiert → Budgetstufe (nur für kostenpflichtige Agenten und nur, wenn kostenpflichtige Aufrufe überhaupt erlaubt sind) → Tageslimit `max_daily_production_jobs` → Entität im richtigen Status → Rechte noch gültig (Lizenz freigegeben, im Gültigkeitszeitraum, Quelle/Creator nicht gesperrt; Videos erst, wenn das Ausgangsmaterial `ANALYZED` ist) → Qualitätsfreigabe ab `READY_TO_PUBLISH` (bestandene Prüfung, Wert ≥ Mindestqualität) → Kanal/Plattform nicht pausiert, im Live-Modus zusätzlich Auto-Publish-Freigabe und Kanalstatus `authorized`.

**Master-Durchlauf** (`agents/master.py`): Fehlgeschlagene Entitäten werden bis `AGENT_MAX_RETRIES` mal in den Status zurückgesetzt, in dem sie scheiterten (Wartezeit `AGENT_RETRY_BASE_DELAY_S`, verdoppelt sich je Versuch). Danach werden alle wartenden Entitäten den zuständigen Agenten zugeteilt; Stufen ohne fertigen Agenten werden als „wartet auf Phase X“ gemeldet. Jeder Durchlauf mit Wirkung wird mit Begründung protokolliert.

**Zeitsteuerung** (`app/scheduler.py`, Compose-Dienst `scheduler`): Master alle `MASTER_TICK_SECONDS` (Standard 300 s), Budget-Agent alle `BUDGET_CHECK_SECONDS` (Standard 3600 s); bei Not-Aus wird nichts eingereiht.

**Steuerung im Dashboard** (Seite „Agenten“): Status aller 18 Agenten, letzter Lauf, aktuelle Aufgabe, Fehler, Läufe heute, Kosten im Monat, Pausieren (Operator) und Fortsetzen (Admin), Master und Budget-Agent manuell starten (Admin), letzte Läufe und Entscheidungen.

## Übersicht

| # | Agent | Phase | Eingabe | Ausgabe | Statuswirkung | Kosten |
|---|---|---|---|---|---|---|
| 1 | Master Orchestrator | 4 | Ergebnisse aller Agenten, Einstellungen | Jobs, Prioritäten, Entscheidungsprotokoll | steuert alle Übergänge | lokal |
| 2 | Trend Research | 5 | YouTube, Twitch, Steam, eigene Metriken | `trends`, Trendberichte | – | API-Quoten (kostenlos) |
| 3 | Game Intelligence | 5 | `games`, `trends`, Kanalperformance | Spielprofile, Videoideen | – | lokal / LLM optional |
| 4 | Material Scout | 6 | registriertes Material (`DISCOVERED`), Trends | Herkunftsnachweis, Zuordnung zum Spiel, Materialbedarf | `DISCOVERED` → `RIGHTS_PENDING` | lokal |
| 5 | Rights & License | 6 | `licenses`, Nachweise, Publisher-Richtlinien | `rights_checks` (12 Kriterien mit Begründung), Ablaufwarnungen | `RIGHTS_PENDING` → `RIGHTS_APPROVED` / `RIGHTS_REJECTED` | lokal |
| 6 | Gameplay Analysis | 7 | freigegebenes Material (`RIGHTS_APPROVED`) | `scenes` mit Bewertung, Clips und Varianten je Sprache | Material → `ANALYZED`, Varianten neu in `SCENE_SELECTED` | lokal (CPU) |
| 7 | Clip Production | 7 | Varianten in `SCENE_SELECTED` | gerenderte `clips` (9:16, H.264/AAC) | `SCENE_SELECTED` → `EDITING` | lokal (CPU) |
| 8 | Creative Director | 8 | Varianten in `EDITING` ohne Konzept | Format, Hook-Struktur, Varianten A–D (`variants.concept`) | bleibt `EDITING` (Teilschritt Konzept) | LLM optional |
| 9 | Script & Hook | 8 | Varianten in `EDITING` mit Konzept | `scripts` (Hook, Sprechertext mit Zeitmarken, CTA, Titel, Beschreibung) | `EDITING` → `LOCALIZATION` | LLM optional |
| 10 | Localization | 9 | Skripte | DE- und EN-Fassungen (keine Wort-für-Wort-Übersetzung) | → `LOCALIZATION` | LLM optional |
| 11 | Voice | 9 | lokalisierte Skripte | `voiceovers` | → `VOICEOVER` | TTS (lizenziert) |
| 12 | Subtitle | 9 | Voiceover, Skript | `subtitles` (SRT/VTT, eingebrannt) | → `SUBTITLES` | lokal |
| 13 | Quality Control | 10 | fertige Variante | `quality_checks` | → `QUALITY_CHECK` → `QUALITY_APPROVED` / `QUALITY_REJECTED` | lokal |
| 14 | Publishing Strategy | 11 | Metriken, Qualität, Kapazität, Grenzen | Plan je Kanal (Menge, Zeit, Auswahl) | → `READY_TO_PUBLISH` → `SCHEDULED` | lokal |
| 15 | Publishing | 12/13 | geplante Jobs | `publishing_jobs`, `posts` | → `PUBLISHED` (nur `authorized`) | API (kostenlos) |
| 16 | Analytics | 14 | Plattform-Metriken | `metrics`, `analytics_snapshots`, Berichte | → `ANALYTICS_PENDING` → `ANALYZED` | API (kostenlos) |
| 17 | Learning | 14 | Snapshots, Experimente | Erkenntnisse, Strategievorschläge | – | lokal |
| 18 | Budget & Cost | 4 (Ausbau 14) | `costs`, Settings | Budgetstufe, Freigabe/Ablehnung | – | lokal |

## Trend Research und Game Intelligence (umgesetzt in Phase 5)

**Trend Research** (`agents/trend_research.py`, alle 6 Stunden): holt Beobachtungen von Twitch, Steam und YouTube (Standard: Testdaten), legt neue Spiele an und bewertet jedes Spiel je Sprache mit einem Score von 0 bis 100 (`services/trends.py`):

| Anteil | Gewicht | Bedeutung |
|---|---|---|
| Reichweite | 40 % | Größe im Verhältnis zum größten Spiel der Quelle (logarithmisch über drei Größenordnungen) |
| Wachstum | 30 % | Veränderung gegenüber der Messung 7 Tage vorher bzw. dem letzten Lauf |
| Sprachpassung | 15 % | Interesse in dieser Sprache im Verhältnis zur anderen |
| Eigene Performance | 10 % | Aufrufe unserer echten Videos des Spiels im Verhältnis zum Durchschnitt |
| Neuheit | 5 % | Neuerscheinung oder nach dem ersten Lauf neu aufgetaucht |

Fehlende Werte (z. B. noch keine eigenen Videos) zählen neutral mit 0,5 und werden als „unbekannt“ markiert. Pro Sprache entsteht ein Trendbericht (`trend_reports`) mit Top 10, Gruppierung nach Zielgruppe und Zusammenfassung; Testdaten sind als solche gekennzeichnet.

**Game Intelligence** (`agents/game_intelligence.py`, täglich): erstellt für jedes Spiel mit aktuellem Trend ein Profil in `games.profile`: Zielgruppe, typische Spielmodi, vier Videoideen aus den Formaten der Spezifikation (deutsch und englisch, steigende Spiele mit Priorität), Kanalperformance je Sprache und eine Gesamtbewertung (Trend-Score; sobald eigene Videos existieren 70 % Trend und 30 % eigene Performance). Regelbasiert ohne kostenpflichtige Aufrufe. Profile werden nach 7 Tagen erneuert.

## Material Scout und Rights & License (umgesetzt in Phase 6)

Material kommt nur über registrierte, lizenzierte Quellen ins System (Dashboard-Seite „Rechte“ oder `POST /api/materials`). Kein Agent lädt, zeichnet auf oder scrapt Videos.

**Material Scout** (`agents/material_scout.py`)
- Je Material (`DISCOVERED`): dokumentiert Quelle, Lizenz und Spiel, übernimmt die Spielzuordnung aus dem Asset, meldet fehlende Nachweise (Benachrichtigung) und übergibt an die Rechteprüfung (`RIGHTS_PENDING`). Gibt selbst nie frei.
- Täglich (`{"sweep": true}`): vergleicht die Top-5-Trends je Sprache mit freigegebenem Material und meldet, für welche Trend-Spiele lizenziertes Material fehlt.

**Rights & License** (`agents/rights_license.py`, Logik in `services/rights.py`)
- Je Material (`RIGHTS_PENDING`): prüft 12 Kriterien einzeln und speichert das Ergebnis in `rights_checks`. Jedes Kriterium ist `ok`, `denied` (Nachweis sagt nein) oder `missing` (Nachweis fehlt). Freigabe nur, wenn alle 12 `ok` sind (deny by default).

| Kriterium | `missing` wenn | `denied` wenn |
|---|---|---|
| Lizenz | Status `pending` | `rejected`, `expired`, `revoked` |
| Nachweis | kein Dokument oder nicht von einem Admin geprüft | – |
| Herkunft | weder URL noch Herkunftsnotiz | Quelle oder Creator gesperrt |
| Kommerziell, Bearbeitung, Kurzvideo, Monetarisierung, Musik | – | nicht ausdrücklich erlaubt |
| Plattformen | keine angegeben | eine gewünschte Plattform fehlt |
| Sprachen | keine angegeben | Deutsch oder Englisch fehlt |
| Gültigkeit | – | vor Beginn oder nach Ablauf |
| Publisher-Richtlinie | Spiel unbekannt oder Richtlinie ungeprüft | `forbidden`, oder `license_required` ohne Erlaubnis des Rechteinhabers |

- Täglich (`{"sweep": true}`): setzt abgelaufene Lizenzen auf `expired`, warnt 14 Tage vor Ablauf (einmal je Lizenz) und schickt betroffenes Material zurück in die Prüfung.
- Jede Änderung an Nachweisen (Lizenz bearbeitet, freigegeben, widerrufen; Quelle oder Creator gesperrt; Richtlinie geändert) schickt Material in `RIGHTS_APPROVED`, `ANALYZED` oder `RIGHTS_REJECTED` zurück nach `RIGHTS_PENDING`. Die Gates prüfen dieselben Kriterien vor jedem späteren Produktionsschritt erneut.

## Gameplay Analysis und Clip Production (umgesetzt in Phase 7)

**Gameplay Analysis** (`agents/gameplay_analysis.py`, Logik in `services/analysis.py`): prüft das Material mit ffprobe, misst je Sekunde Bewegung (mittlere Bilddifferenz), wo im Bild sie stattfindet, Lautstärke und Schnitte und bewertet jedes Fenster in Zielclip-Länge (`CLIP_TARGET_S`, Standard 30 s). Alle Werte sind relativ zum selben Material, damit ein ruhiges Strategiespiel und ein lauter Shooter fair bewertet werden.

| Anteil | Gewicht | Bedeutung |
|---|---|---|
| Bewegung | 35 % | mittlere Bewegung im Verhältnis zum 95. Perzentil des Materials |
| Lautstärke | 25 % | Pegel zwischen 5. und 95. Perzentil; ohne Ton oder bei konstantem Pegel neutral 0,5 |
| Überraschung | 20 % | plötzlicher Sprung von Lautstärke oder Bewegung gegenüber den 3 s davor |
| Schnitte | 10 % | Schnittdichte im Fenster |
| Spannungsaufbau | 10 % | letztes Drittel intensiver als das erste |

Gewählt werden die besten Szenen ohne Überschneidung mit mindestens `MIN_SCENE_SCORE` (0,35), höchstens `MAX_CLIPS_PER_MATERIAL` (3). Start und Ende rücken an einen Schnitt innerhalb von 3 s. Schlagworte: Action, Überraschung, Spannung, Ruhig. Humor und Spielinhalte sind aus diesen Signalen nicht erkennbar. Gibt es keine geeignete Szene, erhält der Betreiber eine Benachrichtigung.

**Clip Production** (`agents/clip_production.py`, Logik in `services/render.py`): rendert den Clip einer Variante einmalig (Sperre auf den Clip, die zweite Sprache übernimmt die Datei). Bildaufbau `crop` (9:16-Ausschnitt um den Bewegungsschwerpunkt) oder `blur_fit` (ganzes Bild über unscharfem Hintergrund), wenn die Action weit verteilt oder nicht messbar ist. Ausgabe H.264 High, yuv420p, AAC 48 kHz Stereo (ohne Quellton eine stille Spur), 1080×1920 bzw. 720×1280 bei 720p-Quellen. Der fertige Clip wird mit ffprobe geprüft (Auflösung, Codecs, Länge ±0,5 s, Größe). Höchstens `max_parallel_render_jobs` Renderjobs laufen gleichzeitig.

## Creative Director und Script & Hook (umgesetzt in Phase 8)

Beide Agenten arbeiten auf `EDITING`; der Teilschritt entscheidet (`Stage.step`, `services/gates.STEPS`): ohne `video_format` ist der Creative Director dran, mit `video_format` Script & Hook.

**Creative Director** (`agents/creative_director.py`, Logik in `services/creative.py`)

| Anteil | Gewicht | Bedeutung |
|---|---|---|
| Szenensignal | 60 % | wie gut Bewegung, Lautstärke, Überraschung und Spannungsaufbau das Format tragen |
| Spielprofil | 20 % | Format steht in den Videoideen von Game Intelligence |
| Eigene Performance | 20 % | Ergebnis des Formats auf unseren Kanälen (bis Phase 14 neutral 0,5) |

Automatisch wählbar: Epische Szene, Überraschung, Unerwartete Wendung, Storytelling (Mindesteignung 0,3). Formate mit inhaltlichem Versprechen (lustig, knapp gescheitert, Tipps, Challenge, Vergleich, Analyse) werden nicht automatisch gewählt. Passt kein Format, endet der Lauf als dauerhafter Fehler. Hook-Strukturen: Frage, starke Behauptung, Countdown, POV, Herausforderung, „was auf dem Spiel steht“. Varianten: Anzahl laut `creative_variants`; jede hat eine eigene Hook-Struktur, bevorzugt auch ein anderes Format; B–D sind als Test markiert.

**Script & Hook** (`agents/script_hook.py`): Hook, Sprechertext in Abschnitten mit Zeitmarken, Aufruf, Titel (≤ 100 Zeichen) und Beschreibung mit Quellenangabe, je Sprache eigene Formulierung. Wortbudget: 2,2 Wörter/s (DE), 2,5 Wörter/s (EN); zuerst entfällt der Einstieg, die Auflösung bleibt. Ein Sprachmodell (`ai_provider`) wird nur nach Budgetfreigabe aufgerufen und gebucht, sonst Vorlage.

## Localization, Voice und Subtitle (umgesetzt in Phase 9)

**Localization** (`LOCALIZATION` → `VOICEOVER`, `services/localization.py`): Sprachprüfung über häufige Funktionswörter der anderen Sprache (ab zwei Treffern, Spiel- und Quellennamen ausgenommen), Formkorrekturen, Zielgruppen-Hashtag, keine identischen Hooks oder Titel zwischen DE und EN. Korrekturen ergeben eine neue Skriptversion (`source` endet auf `+localized`); falsche Sprache ist ein dauerhafter Fehler.

**Voice** (`VOICEOVER` → `SUBTITLES`, `services/voice.py`): Anbieter laut `tts_provider`; nur `commercial_use_cleared`. Je Abschnitt Tempo 1,0–1,15×, Überlänge wird in `voiceovers.segments` vermerkt. Kostenpflichtige Anbieter nur nach `authorize_cost`, Buchung als TTS-Kosten. Nicht angebunden: Lauf übersprungen (`provider`), Variante wartet.

**Subtitle** (`SUBTITLES` → `QUALITY_CHECK`, `services/subtitles.py`): Untertitel aus den Sprachabschnitten (2 × 32 Zeichen, ≥ 0,8 s, ≤ 17 Zeichen/s), SRT, VTT und ASS; fertige Variante mit eingebrannten Untertiteln (unten mittig, 22 % Abstand zum unteren Rand, 8 % seitlich), Stimme gemischt, Gameplay beim Sprechen abgesenkt. Nutzt die Renderslots.

**Quality Control** (`QUALITY_CHECK` → `QUALITY_APPROVED` → `READY_TO_PUBLISH` oder `QUALITY_REJECTED`, `services/quality.py`): blockierende Prüfungen (Datei und Hash, Dekodierung, H.264/AAC, Hochformat, ≤ 60 fps, Plattformgrenzen des Kanals, Lizenz erneut, Stimmrechte, Untertitel, Schwarzbild, Duplikate) und Abzüge vom Qualitätswert (Ton, Lautheit, Spitzenpegel, Schwarz- und Standbild, Überlänge der Stimme, Lesbarkeit). Freigabe nur ohne blockierenden Befund und mit Wert ≥ `min_quality_score`. Ergebnis in `quality_checks` (Prüfungen, Messwerte, Gründe), Wert in `variants.quality_score`; Ablehnung erzeugt eine Benachrichtigung.

**Publishing Strategy** (`READY_TO_PUBLISH` → `SCHEDULED`, `services/strategy.py`): läuft je Kanal (Payload `sweep` + `channel_id`), vom Master höchstens alle `strategy_interval_minutes` gestartet. Einmal pro Ortstag eine neue `strategy_versions`-Zeile (Menge, Begründung, Messwerte); danach Rücknahme nicht mehr passender Planungen und Auswahl der besten Videos für die freien Plätze mit Zeitpunkten im Tagesfenster. Legt `publishing_jobs` an (Modus wie `PUBLISHING_MODE`, Standard Mock), veröffentlicht nichts.

**Publishing** (`SCHEDULED` → `PUBLISHED`, umgesetzt in Phase 12, `services/publishers.py`, `services/youtube.py`): startet für Varianten, deren geplanter Auftrag fällig ist (Schritt `due`). Ein als Test geplanter Auftrag bleibt ein Test (Mock-Post, nichts wird hochgeladen). Live nur, wenn der Auftrag im Live-Modus geplant wurde, `PUBLISHING_MODE=live` gilt und `publish_block` nichts meldet (Pause, Not-Aus, Freigabe, Kanal `authorized`). Vor dem Upload wird der Auftrag als `running` gespeichert; ein `running`-Auftrag ohne Post wird nicht erneut hochgeladen, sondern muss auf der Plattform geprüft werden. Quote, 5xx und Netzfehler: neuer Versuch später (`retry_later`); abgelaufene Verbindung: Kanal `expired` plus Benachrichtigung; andere Fehler: Auftrag `failed` plus Benachrichtigung. Seit Phase 13 auch TikTok (privat als Standard, `connected_restricted` bis zum TikTok-Audit), Instagram Reels und Facebook Reels (immer öffentlich, eigene Tagesgrenzen). Eine eingeschränkte Verbindung setzt den Kanal auf `connected_restricted` und benachrichtigt den Betreiber.

## Grenzen und Pflichten einzelner Agenten

- **Rights & License:** Prüft alle Kriterien aus Spezifikation Abschnitt 5 (kommerziell, Bearbeitung, Kurzvideo, Plattformen, Sprachen, Gültigkeit, Monetarisierung, Musik/Bestandteile). Ein fehlendes Kriterium bedeutet Ablehnung, nicht Annahme. Publisher-Policies (z. B. GTA 6) werden als Regeln gepflegt; keine pauschale Freigabe.
- **Quality Control:** Prüft zusätzlich die Rechtefreigabe erneut (Lizenz kann seit der ersten Prüfung abgelaufen sein) und blockiert Duplikate über Hash, visuellen Fingerprint und Szeneninformationen.
- **Publishing Strategy:** Keine fest programmierte Menge. Entscheidet pro Kanal innerhalb der Kanal-Sicherheitsgrenzen. Keine Erhöhung aufgrund eines einzelnen viralen Videos; kein Urteil allein nach 1 h. Jede Entscheidung mit Begründung; vorherige Strategie bleibt für Rollback gespeichert.
- **Publishing:** Veröffentlicht nur bei `AUTO_PUBLISH_ENABLED=true`, `PUBLISHING_MODE=live`, Kanalstatus `authorized`, gültiger Rechte- und Qualitätsfreigabe und ohne Not-Aus. Idempotenzschlüssel verhindert Doppelposts.
- **Learning:** Lernt erst ab einer Mindestanzahl von Datenpunkten; Änderungen laufen als kontrollierter Test (Experiment) und werden erst danach übernommen.
- **Budget & Cost:** Wird vor jeder kostenpflichtigen Anfrage befragt; Stufen 50/70/85/95 % (siehe ARCHITECTURE.md Abschnitt 7).
- **Voice:** Nur Stimmen und TTS-Dienste mit kommerziellen Nutzungsrechten.
