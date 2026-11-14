# Agenten

18 Agenten mit klar abgegrenzten Aufgaben (Spezifikation Abschnitt 6). Alle Agenten laufen im Worker-Prozess, kommunizieren ausschließlich über Backend und Warteschlange und protokollieren jeden Lauf in `agent_runs` sowie jede Entscheidung in `agent_decisions`.

## Gemeinsamer Vertrag (umgesetzt in Phase 4)

Jeder Agent implementiert:

| Element | Beschreibung |
|---|---|
| `name`, `description` | Anzeige im Dashboard |
| `status` | `idle`, `running`, `paused`, `error` |
| `run(job) -> AgentResult` | Ein Arbeitsschritt; idempotent bezogen auf den Job-Schlüssel |
| `estimate_cost(job)` | Geschätzte externe Kosten; 0 bei lokaler Verarbeitung |
| Ergebnis | Daten in PostgreSQL, Rückmeldung an Master, Kosten in `costs` |

Vor jedem Lauf prüft der Master: Not-Aus, Agent pausiert, Budgetstufe, fachliche Gates (Rechte, Qualität).

## Übersicht

| # | Agent | Phase | Eingabe | Ausgabe | Statuswirkung | Kosten |
|---|---|---|---|---|---|---|
| 1 | Master Orchestrator | 4 | Ergebnisse aller Agenten, Einstellungen | Jobs, Prioritäten, Entscheidungsprotokoll | steuert alle Übergänge | lokal |
| 2 | Trend Research | 5 | YouTube, Twitch, Steam, eigene Metriken | `trends`, Trendberichte | – | API-Quoten (kostenlos) |
| 3 | Game Intelligence | 5 | `games`, `trends`, Kanalperformance | Spielprofile, Videoideen | – | lokal / LLM optional |
| 4 | Material Scout | 6 | Trends, Creator-Uploads, Quellen | `sources`, `assets`, `gameplay_files` | → `DISCOVERED` | lokal |
| 5 | Rights & License | 6 | `licenses`, Publisher-Policies | Freigabe/Sperre mit Begründung | → `RIGHTS_PENDING` / `RIGHTS_APPROVED` / `RIGHTS_REJECTED` | lokal |
| 6 | Gameplay Analysis | 7 | freigegebenes Material | `scenes` mit Bewertung und Zeitmarken | → `ANALYZED` | lokal (CPU) |
| 7 | Clip Production | 7 | Szenen | `clips` (9:16, H.264/AAC) | → `SCENE_SELECTED` → `EDITING` | lokal (CPU) |
| 8 | Creative Director | 8 | Clips, Learning-Erkenntnisse | Konzepte, Formatwahl, Varianten A–D | – | LLM optional |
| 9 | Script & Hook | 8 | Konzepte | `scripts` (Hook, Voiceover, CTA, Titel) | – | LLM optional |
| 10 | Localization | 9 | Skripte | DE- und EN-Fassungen (keine Wort-für-Wort-Übersetzung) | → `LOCALIZATION` | LLM optional |
| 11 | Voice | 9 | lokalisierte Skripte | `voiceovers` | → `VOICEOVER` | TTS (lizenziert) |
| 12 | Subtitle | 9 | Voiceover, Skript | `subtitles` (SRT/VTT, eingebrannt) | → `SUBTITLES` | lokal |
| 13 | Quality Control | 10 | fertige Variante | `quality_checks` | → `QUALITY_CHECK` → `QUALITY_APPROVED` / `QUALITY_REJECTED` | lokal |
| 14 | Publishing Strategy | 11 | Metriken, Qualität, Kapazität, Grenzen | Plan je Kanal (Menge, Zeit, Auswahl) | → `READY_TO_PUBLISH` → `SCHEDULED` | lokal |
| 15 | Publishing | 12/13 | geplante Jobs | `publishing_jobs`, `posts` | → `PUBLISHED` (nur `authorized`) | API (kostenlos) |
| 16 | Analytics | 14 | Plattform-Metriken | `metrics`, `analytics_snapshots`, Berichte | → `ANALYTICS_PENDING` → `ANALYZED` | API (kostenlos) |
| 17 | Learning | 14 | Snapshots, Experimente | Erkenntnisse, Strategievorschläge | – | lokal |
| 18 | Budget & Cost | 14 (Basis ab 4) | `costs`, Settings | Budgetstufe, Freigabe/Ablehnung | – | lokal |

## Grenzen und Pflichten einzelner Agenten

- **Rights & License:** Prüft alle Kriterien aus Spezifikation Abschnitt 5 (kommerziell, Bearbeitung, Kurzvideo, Plattformen, Sprachen, Gültigkeit, Monetarisierung, Musik/Bestandteile). Ein fehlendes Kriterium bedeutet Ablehnung, nicht Annahme. Publisher-Policies (z. B. GTA 6) werden als Regeln gepflegt; keine pauschale Freigabe.
- **Quality Control:** Prüft zusätzlich die Rechtefreigabe erneut (Lizenz kann seit der ersten Prüfung abgelaufen sein) und blockiert Duplikate über Hash, visuellen Fingerprint und Szeneninformationen.
- **Publishing Strategy:** Keine fest programmierte Menge. Entscheidet pro Kanal innerhalb der Kanal-Sicherheitsgrenzen. Keine Erhöhung aufgrund eines einzelnen viralen Videos; kein Urteil allein nach 1 h. Jede Entscheidung mit Begründung; vorherige Strategie bleibt für Rollback gespeichert.
- **Publishing:** Veröffentlicht nur bei `AUTO_PUBLISH_ENABLED=true`, `PUBLISHING_MODE=live`, Kanalstatus `authorized`, gültiger Rechte- und Qualitätsfreigabe und ohne Not-Aus. Idempotenzschlüssel verhindert Doppelposts.
- **Learning:** Lernt erst ab einer Mindestanzahl von Datenpunkten; Änderungen laufen als kontrollierter Test (Experiment) und werden erst danach übernommen.
- **Budget & Cost:** Wird vor jeder kostenpflichtigen Anfrage befragt; Stufen 50/70/85/95 % (siehe ARCHITECTURE.md Abschnitt 7).
- **Voice:** Nur Stimmen und TTS-Dienste mit kommerziellen Nutzungsrechten.
