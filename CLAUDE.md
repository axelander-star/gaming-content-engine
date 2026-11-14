# Claude Code – Projektregeln

Du entwickelst die Gaming Content Engine auf Grundlage der vollständigen PROJECT_SPEC.md.

1. Lies zuerst PROJECT_SPEC.md vollständig.
2. Lies danach docs/ARCHITECTURE.md und docs/DEVELOPMENT_PLAN.md, sofern vorhanden.
3. Arbeite ausschließlich in klar abgegrenzten Entwicklungsphasen.
4. Beginne mit Phase 1.
5. Erstelle echte, ausführbare Software und keine bloßen Platzhalter für Kernfunktionen.
6. Verwende Docker, FastAPI, PostgreSQL, Redis, Next.js und TypeScript.
7. Implementiere Agenten modular und mit nachvollziehbaren Aufgaben.
8. Schreibe Tests für jede wichtige Funktion.
9. Verwende Mock-Dienste, solange keine echten API-Zugänge freigegeben sind.
10. Führe keine kostenpflichtigen API-Aufrufe ohne ausdrückliche Freigabe durch.
11. Veröffentliche niemals echte Inhalte während der Entwicklungs- und Testphase.
12. Speichere Zugangsdaten ausschließlich sicher und niemals im Git-Repository.
13. Dokumentiere alle Entscheidungen, Fehler und offenen Punkte.
14. Aktualisiere nach jeder Phase docs/PROJECT_STATUS.md.
15. Beginne die nächste Phase erst, wenn die aktuelle Phase getestet wurde.

## WICHTIG

Die Veröffentlichungsmenge darf nicht fest programmiert werden.

Der Publishing Strategy Agent soll sie pro Kanal dynamisch anhand der verfügbaren Performance-Daten, Qualitätswerte, Produktionskapazität und Plattformregeln bestimmen.

## Arbeitshinweise (ergänzt in Phase 1)

- **Aktueller Stand:** siehe `docs/PROJECT_STATUS.md`. Dort steht, welche Phase abgeschlossen ist und welche als Nächstes kommt.
- **Phasenabschluss:** Nach jeder Phase `scripts/verify_phase1.sh` und `scripts/test_backend.sh` ausführen (plus die Tests der jeweiligen Phase) und die sechs Punkte aus PROJECT_SPEC.md Abschnitt 19 ausgeben.
- **Backend:** Code in `backend/` (Importwurzel ist `backend/`). Statusänderungen nur über `services/workflow.py`. Neue Tabellen/Spalten immer mit Alembic-Migration (`alembic revision --autogenerate`), danach `alembic check`. Details: `backend/README.md`.
- **Sprache:** Dokumentation und Kommunikation auf Deutsch; Code-Bezeichner, Commit-Messages und Kommentare im Code auf Englisch.
- **Sicherheitsvorgaben:** `AUTO_PUBLISH_ENABLED=false` und `PUBLISHING_MODE=mock` bleiben Standard. Nie echte Plattform-Credentials in Dateien schreiben, die eingecheckt werden.
- **Agenten-Referenz:** `docs/AGENTS.md` (Zuständigkeiten, Ein-/Ausgaben, Status-Übergänge).
- **API-Referenz:** `docs/API_INTEGRATIONS.md`. Nur dokumentierte, offizielle Endpunkte verwenden; vor Nutzung gegen die aktuelle Anbieter-Dokumentation prüfen.
