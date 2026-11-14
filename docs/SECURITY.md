# Sicherheitskonzept

Grundlage: Spezifikation Abschnitt 15 und Geschäftsregeln Abschnitt 17.

## 1. Sichere Standardwerte

| Schalter | Standard | Wirkung |
|---|---|---|
| `AUTO_PUBLISH_ENABLED` | `false` | Ohne aktive Freigabe wird nichts automatisch veröffentlicht. |
| `PUBLISHING_MODE` | `mock` | Publishing-Adapter schreiben nur in die Datenbank, kein Netzwerkaufruf. |
| `PAID_API_CALLS_ENABLED` | `false` | Kostenpflichtige KI-/API-Adapter verweigern jeden Aufruf. |
| `EMERGENCY_STOP` | `false` | `true` stoppt alle Agenten und Veröffentlichungen sofort. |

Die automatische Veröffentlichung wird erst eingeschaltet, wenn alle Tests bestanden und die Plattformzugänge freigegeben sind. Der Wechsel auf `live` erfordert einen Admin und wird im Audit-Log festgehalten.

## 2. Secrets und Zugangsdaten

- **Keine Secrets im Quellcode oder Repository.** `.env` ist in `.gitignore`; nur `.env.example` mit Platzhaltern wird eingecheckt.
- Infrastruktur-Secrets (DB, Redis, App-Schlüssel) kommen aus Umgebungsvariablen.
- **Plattform-OAuth-Tokens** (Refresh/Access) werden in PostgreSQL **verschlüsselt** gespeichert (Fernet/AES, Schlüssel `CREDENTIALS_ENCRYPTION_KEY` aus der Umgebung, nicht in der DB).
- Secrets werden nie geloggt; der Logger maskiert bekannte Schlüsselnamen.
- `scripts/verify_phase1.sh` und später ein CI-Schritt prüfen auf versehentlich eingecheckte Secrets.

## 3. Anmeldung und Rollen (Phase 3)

- Passwort-Hashing mit Argon2id, Mindestlänge, Login-Rate-Limit.
- Rollen: `admin` (alles inkl. Live-Schaltung, Budget, Not-Aus), `operator` (Agenten/Plattformen pausieren, Inhalte prüfen), `viewer` (lesen).
- Rechteprüfung serverseitig in jedem Endpunkt, nicht nur im Frontend.
- Kurzlebige Access-Tokens, sichere Cookies (`HttpOnly`, `Secure`, `SameSite=Strict`).

## 4. Netzwerk

- PostgreSQL, Redis, n8n und Uptime Kuma sind nur auf `127.0.0.1` gebunden.
- Öffentlich nur Caddy (80/443) mit automatischem TLS und Sicherheitsheadern.
- Server: SSH nur mit Schlüssel, Firewall (ufw/Hetzner Firewall) nur 22/80/443, automatische Sicherheitsupdates (Phase 15).

## 5. Steuerung und Eingriff

- **Not-Aus** (global), **Pausieren einzelner Agenten**, **Pausieren einzelner Plattformen/Kanäle**: im Dashboard und per API; wirken sofort, da jeder Job vor Ausführung die Gates prüft.
- **Schutz vor Doppelveröffentlichung:** Idempotenzschlüssel pro (Variante, Kanal), eindeutiger Index in `posts`, Duplikat-Fingerprints in QC.
- **Rechte- und Qualitäts-Gate** sind zentrale Services, die der Publishing Agent nicht umgehen kann.

## 6. Protokollierung und Nachweise

- `audit_logs`: alle Logins, Einstellungsänderungen, Statuswechsel, Veröffentlichungen, Not-Aus-Aktionen.
- `agent_decisions`: jede Agentenentscheidung mit Eingaben und Begründung.
- Lizenznachweise (Dokumente, Herkunft, Gültigkeit) sind mit jedem Asset verknüpft und unveränderlich versioniert.

## 7. Backups und Wiederherstellung (Phase 15)

- Tägliches `pg_dump`, verschlüsselt, Ablage in R2 mit Aufbewahrungsregel.
- Regelmäßiger Restore-Test auf einer leeren Instanz.
- Medien in R2 werden nicht doppelt gesichert, sind aber über DB-Referenzen wiederauffindbar.

## 8. Plattformregeln

- Nur offizielle APIs; **keine Passwort-Bots**, kein Scraping, das Nutzungsbedingungen verletzt.
- Keine unberechtigte Stream-Aufzeichnung oder Video-Übernahme.
- API-Quoten und Rate-Limits werden pro Plattform in Redis gezählt und respektiert.

## 9. Offene Sicherheitspunkte

- Auswahl des Fehlerüberwachungsdienstes (selbst gehostet vs. SaaS) – Phase 15.
- Schlüsselrotation für `CREDENTIALS_ENCRYPTION_KEY` – Konzept in Phase 12.
- Zwei-Faktor-Anmeldung für Admins – Entscheidung in Phase 3.
