# Architektur

Dieses Dokument beschreibt die Zielarchitektur der Gaming Content Engine. Verbindliche Anforderungen stehen in [PROJECT_SPEC.md](../PROJECT_SPEC.md); hier stehen die technischen Entscheidungen, wie sie umgesetzt werden.

## 1. Überblick

```
                          ┌──────────────────────────────┐
                          │   Dashboard (Next.js, TS)    │
                          └──────────────┬───────────────┘
                                         │ HTTPS (Caddy)
                          ┌──────────────▼───────────────┐
                          │     Backend API (FastAPI)    │
                          │  Auth · REST · Settings ·    │
                          │  Not-Aus · Audit             │
                          └───┬──────────────┬───────────┘
                              │              │
                ┌─────────────▼───┐    ┌─────▼──────────────┐
                │   PostgreSQL    │    │  Redis (Queue,     │
                │ Daten, Entschei-│    │  Locks, Rate-Limit)│
                │ dungen, Audit   │    └─────┬──────────────┘
                └─────────────▲───┘          │
                              │        ┌─────▼──────────────────────────┐
                              └────────┤   Worker (Python)              │
                                       │   Master Orchestrator          │
                                       │   + 17 Fach-Agenten            │
                                       │   FFmpeg / OpenCV / SceneDetect│
                                       └─────┬───────────────┬──────────┘
                                             │               │
                                ┌────────────▼───┐   ┌───────▼───────────────┐
                                │ Cloudflare R2  │   │ Externe APIs über     │
                                │ (Medien)       │   │ Adapter (Mock | Live) │
                                └────────────────┘   └───────────────────────┘
```

**Dienste (Docker Compose):** `postgres`, `redis`, `backend` (API, Phase 2), `worker` (Agenten, Phase 4), `frontend` (Phase 3), `caddy`, optional `n8n` und `uptime-kuma`.

## 2. Architekturentscheidungen

| # | Entscheidung | Begründung |
|---|---|---|
| A1 | **Ein Python-Backend-Paket** für API und Worker, zwei Prozesse (`api`, `worker`) aus demselben Image. | Gemeinsame Modelle und Services, kein doppelter Code, passt auf einen CX33. |
| A2 | **Redis als Aufgabenwarteschlange mit RQ** (entschieden in Phase 2). Drei Queues `high`, `default`, `low`; deterministische Job-IDs (`enqueue_unique`) verhindern doppelte Jobs. | Spezifikation gibt Redis vor. RQ ist synchron, aktiv gepflegt und passt zu CPU-lastigen Jobs (FFmpeg); arq wäre nur bei async-Agenten im Vorteil. |
| A3 | **PostgreSQL ist die Quelle der Wahrheit.** Redis enthält nur flüchtige Zustände (Jobs, Locks, Rate-Limit-Zähler). | Jede Entscheidung muss nachvollziehbar und nach Neustart vorhanden sein. |
| A4 | **Jeder externe Dienst hinter einem Adapter-Interface** mit `Mock`- und `Live`-Implementierung. Auswahl über Konfiguration, Standard ist `Mock`. | Entwicklung ohne echte Veröffentlichungen und ohne Kosten; Tests deterministisch. |
| A5 | **n8n nur für Zeitsteuerung und Benachrichtigungen**, nicht für Geschäftslogik. | Logik bleibt testbar und versioniert im Python-Code. n8n ist optional. |
| A6 | **SQLAlchemy 2.x + Alembic** für Datenmodell und Migrationen, **Pydantic v2** für Schemas. | Saubere Typisierung, Standard im FastAPI-Umfeld. |
| A7 | **Medien liegen in Cloudflare R2**, lokal nur als temporäre Arbeitskopie. In Entwicklung ein lokales Verzeichnis als Mock-Speicher. | 80 GB Serverplatte reichen nicht für ein Medienarchiv. |
| A8 | **Gate-Prüfungen im Code, nicht nur in Agenten.** Rechte-, Qualitäts-, Budget- und Not-Aus-Prüfung sind zentrale Services, die vor jedem Statuswechsel und jedem externen Aufruf erzwungen werden. | Geschäftsregeln 1, 2, 8, 9 dürfen nicht von einem einzelnen Agenten abhängen. |
| A9 | **Veröffentlichungsmenge wird nie als Konstante programmiert.** Es gibt nur pro Kanal konfigurierte Sicherheitsgrenzen (min/max); die Menge berechnet der Publishing Strategy Agent. | CLAUDE.md, Spezifikation Abschnitt 3. |
| A10 | **Enums als VARCHAR + CHECK-Constraint** statt nativer PostgreSQL-Enums. | Neue Statuswerte lassen sich per einfacher Migration ergänzen; die Datenbank lehnt trotzdem ungültige Werte ab. |

## 3. Datenfluss (Pipeline)

```
Trendquellen → Trend Research → Master Orchestrator → Material Scout → Rights & License
  → Gameplay Analysis → Clip Production → Creative Director → Script & Hook
  → Localization (DE | EN) → Voice → Subtitle → Quality Control
  → Publishing Strategy → Publishing → Analytics → Learning
                                                     └──► Rückkopplung an Trend, Creative, Strategy
```

Querschnitt: **Budget & Cost Agent** wird vor jeder kostenpflichtigen Aktion befragt; **Game Intelligence** liefert Kontext an Trend, Creative und Strategy.

### Kommunikation zwischen Agenten

Agenten rufen sich **nie direkt** auf. Ablauf:

1. Ein Agent schreibt sein Ergebnis in PostgreSQL und protokolliert einen `agent_run` (und ggf. `agent_decisions`).
2. Er meldet dem Master Orchestrator das Ergebnis (Job-Ergebnis in Redis).
3. Der Master prüft Gates (Not-Aus, Agent pausiert, Budget, Rechte, Qualität) und reiht den nächsten Job ein.
4. Fehler führen zu Status `FAILED` mit Fehlerdetails; Wiederholung mit begrenztem Retry und exponentiellem Backoff.

Jeder Job ist **idempotent** (Job-Schlüssel aus Entität + Schritt), damit Wiederholungen keine Doppelarbeit oder Doppelveröffentlichung erzeugen.

## 4. Statusmaschine

Die Spezifikation listet `ANALYZED` zweimal (nach der Rechteprüfung und nach der Performance-Auswertung). Daraus folgt die Entscheidung, **zwei getrennte Statusmaschinen** für zwei Entitäten zu führen. Innerhalb jeder Entität ist der Status eindeutig.

**Material (`gameplay_files`)**

```
DISCOVERED → RIGHTS_PENDING → RIGHTS_APPROVED → ANALYZED
                     └──► RIGHTS_REJECTED (gesperrt)
```

**Video (`variants`, eine Sprachfassung je Kanal)**

```
SCENE_SELECTED → EDITING → LOCALIZATION → VOICEOVER → SUBTITLES → QUALITY_CHECK
  → QUALITY_APPROVED → READY_TO_PUBLISH → SCHEDULED → PUBLISHED
  → ANALYTICS_PENDING → ANALYZED → ARCHIVED
```

Zusätzlich auf beiden Ebenen:

- `FAILED`: Fehler mit Ursache (`failed_step`, `error_message`, `retry_count`); erneute Verarbeitung setzt auf den letzten gültigen Status zurück.
- `QUALITY_REJECTED`: von QC abgelehnt, zurück zu `EDITING` oder `ARCHIVED`.
- `READY_TO_PUBLISH` bleibt bestehen, wenn die Plattform nicht autorisiert ist (Spezifikation Abschnitt 11).

Erlaubte Übergänge stehen zentral in `backend/core/states.py` und werden von `backend/services/workflow.py` erzwungen (`transition`, `mark_failed`, `retry`). Jeder Übergang erzeugt einen Eintrag in `audit_logs`. Ein Video kann nur aus `SCHEDULED` veröffentlicht werden, und `SCHEDULED` ist nur über `QUALITY_APPROVED → READY_TO_PUBLISH` erreichbar; Material erreicht `ANALYZED` nur über `RIGHTS_APPROVED`.

## 5. Datenmodell

Mindestumfang laut Spezifikation Abschnitt 10, gruppiert nach Bereich:

| Bereich | Tabellen |
|---|---|
| Zugang | `users`, `audit_logs`, `notifications`, `system_settings` |
| Kanäle | `platforms`, `channels` (Plattform × Sprache, eigene Strategie und Grenzen) |
| Trends | `games`, `trends` |
| Rechte | `creators`, `sources`, `licenses`, `assets` |
| Produktion | `gameplay_files`, `scenes`, `clips`, `variants`, `scripts`, `voiceovers`, `subtitles`, `quality_checks` |
| Publishing | `publishing_jobs`, `posts` |
| Analytics | `metrics`, `analytics_snapshots` |
| Steuerung | `agent_runs`, `agent_decisions`, `costs` |

Umgesetzt in Phase 2 (`backend/models/`, Migration `backend/database/migrations/`). Abweichungen und Details:

- `metrics.measure_window` statt `window` (reserviertes SQL-Wort), Werte `1h`, `6h`, `24h`, `48h`, `7d`, `other`; alle Kennzahlen nullable, weil Plattformen unterschiedliche Werte liefern.
- `channels.max_posts_per_day` ist eine Sicherheitsgrenze mit Standard **0**: Ein neuer Kanal kann nichts veröffentlichen, bis der Betreiber ihn konfiguriert. Die Datenbank erzwingt `max >= min >= 0`.
- Lizenzrechte (`allows_*`, `music_cleared`) stehen standardmäßig auf `false`.
- `posts` hat einen eindeutigen Index auf (`variant_id`, `channel_id`), `publishing_jobs.idempotency_key` ist eindeutig.

Ergänzend in Phase 11/14 geplant: `strategy_versions` (gespeicherte Publishing-Strategien je Kanal für Rollback) und `experiments` (kontrollierte Tests).

### Rückverfolgbarkeit

Jeder Post ist lückenlos bis zur Lizenz verfolgbar:

```
posts → publishing_jobs → variants → clips → scenes → gameplay_files → assets → sources → licenses / creators
```

Fremdschlüssel sind `NOT NULL` entlang dieser Kette. Ein Post ohne Lizenzpfad ist im Datenmodell nicht darstellbar.

### Duplikaterkennung

`clips` und `variants` speichern SHA-256 der Datei, einen perzeptuellen Video-Fingerprint (Frame-Hashes) und die Szenen-IDs. QC blockiert Varianten, deren Fingerprint-Distanz zu bereits veröffentlichten Varianten unter einem Schwellwert liegt.

## 6. Publishing Strategy (Konzept)

Für jeden Kanal getrennt:

1. **Eingaben:** Kennzahlen nach 1 h, 6 h, 24 h, 48 h und 7 Tagen (nur verfügbare Werte), Qualitätswerte der freigegebenen Videos, Produktionskapazität, Plattformgrenzen, Budgetstufe.
2. **Bewertung:** Vergleich jedes Videos mit dem Kanal-Baseline für **denselben Messzeitpunkt** (z. B. Perzentil im Vergleich zu früheren Videos nach 24 h). Ein Video gilt erst nach ausreichendem Messzeitraum als schwach.
3. **Entscheidung:** Menge und Zeitpunkte für den nächsten Zeitraum, begrenzt durch `channel.min_posts` / `channel.max_posts`, Mindestabstand und Plattformlimits. Änderungen der Menge sind pro Zyklus gedämpft (keine Sprünge durch ein einzelnes virales Video).
4. **Protokoll:** Jede Entscheidung mit Begründung und Eingangswerten in `agent_decisions`; die vorherige Strategie bleibt in `strategy_versions` und kann zurückgesetzt werden.

Die konkreten Formeln und Schwellwerte werden in Phase 11 festgelegt und getestet.

## 7. Budgetsteuerung

Der Budget-Service berechnet den Monatsverbrauch aus `costs` und liefert eine Stufe:

| Verbrauch | Stufe | Wirkung |
|---|---|---|
| < 50 % | `normal` | keine Einschränkung |
| ≥ 50 % | `warn` | Benachrichtigung |
| ≥ 70 % | `reduced` | lokale Verarbeitung bevorzugt, weniger Varianten |
| ≥ 85 % | `priority_only` | nur priorisierte Jobs |
| ≥ 95 % | `stop_paid` | keine kostenpflichtigen externen Aufrufe |

Jeder kostenpflichtige Adapter ruft vor dem Aufruf `budget.authorize(estimated_cost)` auf. Zusätzlich gilt der globale Schalter `PAID_API_CALLS_ENABLED`.

## 8. Ausfallsicherheit

- Fällt eine externe API aus, bleiben betroffene Jobs in ihrem Status und werden mit Backoff erneut versucht; andere Kanäle laufen weiter.
- Fällt Redis aus, gehen keine Daten verloren (PostgreSQL ist führend); offene Jobs werden beim Start aus dem Status rekonstruiert.
- Veröffentlichungen nutzen einen Idempotenzschlüssel pro (Variante, Kanal), damit ein Retry keinen Doppelpost erzeugt.

## 9. Deployment-Ziel

Hetzner Cloud CX33 (4 vCPU, 8 GB RAM, 80 GB, Ubuntu 24.04 LTS), Docker Compose, Caddy mit automatischem TLS. Renderjobs werden über `max_parallel_render_jobs` begrenzt, damit API und Datenbank reaktionsfähig bleiben. Die tatsächliche Kapazität wird in Phase 7 gemessen und in `PROJECT_STATUS.md` dokumentiert.
