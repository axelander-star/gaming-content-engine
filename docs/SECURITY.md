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

## 3. Anmeldung und Rollen (umgesetzt in Phase 3)

- Passwörter mit **Argon2id** gehasht; Richtlinie: mindestens 12 Zeichen und drei Zeichenklassen.
- **Session:** signiertes Token (HS256, 30 Minuten) im Cookie `gce_session` mit `HttpOnly`, `Secure`, `SameSite=Strict`. In production verweigert das Backend den Start mit `SESSION_COOKIE_SECURE=false`.
- **CSRF:** Double-Submit. Jede schreibende Anfrage muss den Wert des Cookies `gce_csrf` im Header `X-CSRF-Token` mitsenden.
- **Widerruf:** Jeder Benutzer hat eine `session_version`. Rollenwechsel, Deaktivierung, Passwortänderung und „überall abmelden“ erhöhen sie; alte Tokens werden damit sofort ungültig.
- **Login-Sperre:** nach 5 Fehlversuchen pro E-Mail und pro IP für 15 Minuten (Redis). Unbekannte Konten und falsche Passwörter liefern dieselbe Antwort; die Antwortzeit ist durch einen Dummy-Hash angeglichen.
- **Rollen:** `admin` (alles, inkl. Not-Aus lösen, Auto-Publish, Budget, Kanalgrenzen, Benutzer), `operator` (Not-Aus auslösen, Kanäle pausieren), `viewer` (lesen). Der letzte aktive Admin kann nicht entfernt werden.
- Rechteprüfung serverseitig in jedem Endpunkt; das Dashboard blendet nur aus.
- **Kein Standard-Admin:** Der erste Admin wird per CLI (`python -m app.create_admin`) mit Passwortabfrage angelegt.
- **Doppelte Sperre für Veröffentlichungen:** Auto-Publish im Dashboard wirkt nur, wenn auch die Serverkonfiguration `AUTO_PUBLISH_ENABLED=true` und `PUBLISHING_MODE=live` erlaubt. Der Not-Aus greift, wenn er in der Konfiguration *oder* im Dashboard aktiv ist.

## 4. Netzwerk

- PostgreSQL, Redis, n8n und Uptime Kuma sind nur auf `127.0.0.1` gebunden.
- **Private Nutzung (15.11.2026):** Zugang nur über Cloudflare Access; der Server ist über einen Cloudflare Tunnel angebunden und hat außer SSH keine offenen Ports. Das Backend prüft bei `ACCESS_GUARD=cloudflare` jedes Access-Token selbst (Signatur, Zielgruppe, Aussteller, Ablauf, optional E-Mail) und lehnt Anfragen ohne gültiges Token mit 403 ab; ausgenommen ist nur `/api/health` für interne Healthchecks. `SINGLE_USER_MODE=true` verhindert weitere Konten. Details: [PRIVATE_ACCESS.md](PRIVATE_ACCESS.md).
- Ohne Tunnel (alter Weg): öffentlich nur Caddy (80/443) mit automatischem TLS und Sicherheitsheadern.
- Server: SSH nur mit Schlüssel, Firewall (ufw, zusätzlich Hetzner Firewall empfohlen) nur 22/80/443, fail2ban, automatische Sicherheitsupdates. Umgesetzt in Phase 15 als `infrastructure/server/harden.sh` (siehe [OPERATIONS.md](OPERATIONS.md)).
- Zusätzliche Header in Caddy (Phase 15): `Content-Security-Policy` mit `frame-ancestors 'none'`, `base-uri 'self'`, `object-src 'none'` und `form-action 'self'`; dazu `Permissions-Policy` ohne Kamera, Mikrofon, Standort, Zahlung und USB sowie `Cross-Origin-Opener-Policy: same-origin`.

## 5. Steuerung und Eingriff

- **Not-Aus** (global), **Pausieren einzelner Agenten**, **Pausieren einzelner Plattformen/Kanäle**: im Dashboard und per API; wirken sofort, da jeder Job vor Ausführung die Gates prüft.
- **Schutz vor Doppelveröffentlichung:** Idempotenzschlüssel pro (Variante, Kanal), eindeutiger Index in `posts`, Duplikat-Fingerprints in QC.
- **Rechte- und Qualitäts-Gate** sind zentrale Services, die der Publishing Agent nicht umgehen kann.

## 6. Protokollierung und Nachweise

- `audit_logs`: alle Logins, Einstellungsänderungen, Statuswechsel, Veröffentlichungen, Not-Aus-Aktionen.
- `agent_decisions`: jede Agentenentscheidung mit Eingaben und Begründung.
- Lizenznachweise (Dokumente, Herkunft, Gültigkeit) sind mit jedem Asset verknüpft und unveränderlich versioniert.
- **Umsetzung Phase 6:** Nachweise werden über `POST /api/licenses/{id}/documents` hochgeladen. Erlaubt sind nur PDF, PNG und JPEG bis `MAX_DOCUMENT_BYTES` (Standard 10 MB); der Dateiinhalt muss zum Typ passen (Magic Bytes). Dateien liegen inhaltsadressiert (SHA-256) unter `MEDIA_ROOT` (Docker-Volume `media_data`) und werden nie überschrieben; jede neue Datei ist eine neue Version in `license_documents`. Der Download prüft, dass der Pfad innerhalb von `MEDIA_ROOT` liegt. Die Dateien wandern nach R2, sobald Zugangsdaten vorliegen.
- **Umsetzung Phase 7:** Gameplay-Upload (`POST /api/materials/upload`, Operator) nur als MP4, MOV oder MKV bis `MAX_UPLOAD_BYTES` (Standard 4 GiB). Die Datei wird in ein Arbeitsverzeichnis gestreamt, mit ffprobe geprüft und nur bei bestandener Prüfung inhaltsadressiert gespeichert; abgelehnte Dateien werden sofort gelöscht. FFmpeg läuft ohne Shell mit festen Argumentlisten und Zeitlimit. Clips werden nur an angemeldete Benutzer ausgeliefert.
- Rollen: Operatoren legen Creator, Quellen, Lizenzen und Material an, laden Nachweise hoch, sperren und widerrufen. Nur Admins geben Lizenzen frei (erst nach hochgeladenem Nachweis), heben Sperren auf und legen Publisher-Richtlinien fest. Jede Änderung steht im Audit-Log; jede Rechteprüfung mit allen Kriterien in `rights_checks`.

## 7. Backups und Wiederherstellung (umgesetzt in Phase 15)

- Täglich `pg_dump`, mit GnuPG verschlüsselt (AES-256, Schlüssel `BACKUP_PASSPHRASE` nur aus der Umgebung). Die Sicherung wird direkt verschlüsselt geschrieben, unverschlüsselt landet nichts auf der Platte. Die Dateirechte sind 0600.
- Nach jeder Sicherung folgt ein Wiederherstellungstest in eine leere Datenbank. Prüfsumme, Schema-Version, Tabellen und jede Zeilenzahl müssen stimmen. Ein Fehlschlag löst einen Alarm aus.
- Aufbewahrung 14 Tage, mindestens die drei neuesten Sicherungen. Kopie außerhalb des Servers: siehe [OPERATIONS.md](OPERATIONS.md).
- Wiederhergestellt wird immer in eine neue Datenbank; die laufende wird nie überschrieben.
- Medien werden nicht doppelt gesichert, sind aber über DB-Referenzen wiederauffindbar (später in R2).

## 8. Plattformregeln

- Nur offizielle APIs; **keine Passwort-Bots**, kein Scraping, das Nutzungsbedingungen verletzt.
- Keine unberechtigte Stream-Aufzeichnung oder Video-Übernahme.
- API-Quoten und Rate-Limits werden pro Plattform in Redis gezählt und respektiert.

## 9. Sicherheitsprüfung Phase 15

| Bereich | Ergebnis | Maßnahme |
|---|---|---|
| Python-Abhängigkeiten (`pip-audit`) | `cryptography` 46.0.7 mit 4 bekannten Schwachstellen (Fix ab 48.0.1 bzw. 50.0.0) | auf `cryptography>=50,<51` angehoben, danach ohne Befund |
| Dashboard-Abhängigkeiten (`npm audit --omit=dev`) | 0 Schwachstellen | – |
| Schlüsselwechsel `CREDENTIALS_ENCRYPTION_KEY` | war nicht möglich, ohne alle Kanäle neu zu verbinden | `CREDENTIALS_ENCRYPTION_KEY_OLD` plus `python -m app.rotate_credentials` (MultiFernet) |
| Fehlerüberwachung | Entscheidung offen (selbst gehostet oder SaaS) | selbst gehostet: Systemprüfung, Benachrichtigungen, Uptime Kuma; kein externer Dienst, keine Kosten |
| Sicherheitsheader | ohne CSP und Permissions-Policy | ergänzt (Abschnitt 4) |
| Server | keine Härtung festgelegt | `harden.sh` (Abschnitt 4) |
| Sicherungen | nicht vorhanden | Abschnitt 7 |
| Geheimnisse in Protokollen | maskiert; die Uptime-Kuma-Push-URL enthält ein Token und wird nie protokolliert | – |
| Schreibende API-Zugriffe | Rollenprüfung serverseitig, CSRF-Schutz, Login-Sperre (Phase 3) | unverändert, durch Tests abgedeckt |

## 10. Offene Sicherheitspunkte

- Cloudflare Access und Tunnel: im Code vorbereitet, noch nicht eingerichtet ([PRIVATE_ACCESS.md](PRIVATE_ACCESS.md)).
- Zwei-Faktor-Anmeldung (TOTP) für Admins: noch nicht umgesetzt. Bis dahin gelten eine starke Passwortrichtlinie, die Login-Sperre, kurze Sitzungen (30 min) und ein Dashboard, das nur über HTTPS erreichbar ist. Bevor weitere Personen Zugang bekommen, sollte TOTP nachgezogen werden.
- Kopie der Sicherungen außerhalb des Servers: Ziel (Storage Box oder R2) und Kosten müssen noch freigegeben werden.
