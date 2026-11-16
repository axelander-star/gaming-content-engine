# Betrieb

Stand: Phase 15. Dieses Dokument beschreibt den Betrieb auf dem Server: Einrichtung, Updates, Überwachung, Datensicherung, Wiederherstellung, Härtung und Skalierung. Sicherheitsgrundsätze stehen in [SECURITY.md](SECURITY.md).

## 1. Erstinstallation

1. Server mit Ubuntu 24.04 anlegen (geplant: Hetzner CX33) und SSH-Schlüssel hinterlegen.
2. Härtung ausführen (Abschnitt 6): `sudo ./infrastructure/server/harden.sh --tunnel --dry-run`, dann ohne `--dry-run`. `--tunnel` für den privaten Betrieb hinter Cloudflare Tunnel (nur SSH offen, siehe [PRIVATE_ACCESS.md](PRIVATE_ACCESS.md)); ohne Tunnel die Option weglassen.
3. Docker Engine mit Compose-Plugin nach der offiziellen Docker-Anleitung installieren.
4. Repository klonen und `./scripts/setup_env.sh` ausführen. Das Skript legt `.env` an, erzeugt alle Passwörter und Schlüssel, setzt die Schalter für den privaten Betrieb, fragt nur nach E-Mail, Teamdomäne, AUD-Tag, Tunnel-Token und den Angaben für die Rechtstext-Seite und startet danach die Vorabprüfung. Erneut ausführen ist gefahrlos, vorhandene Werte bleiben. Von Hand: `.env` aus `.env.example` erstellen und alle Pflichtwerte setzen: `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `SECRET_KEY`, `CREDENTIALS_ENCRYPTION_KEY`, `BACKUP_PASSPHRASE`, `APP_ENV=production`; für den privaten Betrieb zusätzlich `ACCESS_GUARD=cloudflare`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`, `CF_ACCESS_ALLOWED_EMAILS`, `SINGLE_USER_MODE=true`, `CLOUDFLARE_TUNNEL_TOKEN`, `CADDY_BIND=127.0.0.1` und `ACME_EMAIL` (Caddy startet ohne diesen Wert nicht, auch im Tunnel-Betrieb; ohne Tunnel zusätzlich `DOMAIN`). Die Sicherheitsschalter bleiben auf ihren Standardwerten (`AUTO_PUBLISH_ENABLED=false`, `PUBLISHING_MODE=mock`).
5. Vorabprüfung: `./infrastructure/server/preflight.sh --env .env` (ändert nichts), bis alle Punkte „OK“ sind. Dann `./scripts/deploy.sh` ausführen.
6. Ersten Admin anlegen: `docker compose run --rm backend python -m app.create_admin`.
7. Uptime Kuma einrichten (Abschnitt 3).

`BACKUP_PASSPHRASE` zusätzlich außerhalb des Servers aufbewahren (z. B. im Passwortmanager). Ohne sie sind die Sicherungen nicht lesbar.

## 2. Updates und Rücksprung

```bash
./scripts/deploy.sh             # neuester Stand von main
./scripts/deploy.sh <commit>    # bestimmte Version, auch zum Zurückspringen
```

Ablauf des Skripts:

1. prüft `.env` (Pflichtwerte gesetzt, Warnung bei eingeschalteter echter Veröffentlichung) und ob das Arbeitsverzeichnis sauber ist;
2. sichert die Datenbank, wenn der Stack läuft (`python -m app.backup run`). Schlägt das fehl, bricht das Update ab;
3. holt die Version, baut die Images und startet alles. Die Migrationen laufen dabei im Dienst `migrate`;
4. wartet, bis `/api/health/ready` antwortet, und gibt den Befehl zum Zurückspringen aus.

Migrationen laufen nur vorwärts. Braucht ein Rücksprung das alte Datenbankschema, wird die vor dem Update erstellte Sicherung wiederhergestellt (Abschnitt 5).

## 3. Überwachung und Alarme

**Systemprüfung:** Die Zeitsteuerung (`scheduler`) prüft alle `MONITOR_SECONDS` (Standard 60 s):

| Prüfung | Warnung | Kritisch |
|---|---|---|
| Datenbank, Redis | – | nicht erreichbar |
| Worker | – | kein Worker mit Lebenszeichen in den letzten 2 min |
| Zeitsteuerung | – | kein Lebenszeichen seit 3 min |
| Warteschlangen | Wartezeit > `QUEUE_WAIT_WARN_S` (30 min) | Wartezeit > das Vierfache |
| Agentenfehler | ≥ 3 Fehlschläge und ≥ `AGENT_ERROR_WARN_RATIO` (20 %) der Läufe in 24 h | – |
| Serverfehler der API | ≥ 10 Antworten mit 5xx in 24 h | – |
| Datensicherung | kein Schlüssel, keine Sicherung, Wiederherstellung nie getestet | letzte Sicherung älter als `BACKUP_MAX_AGE_HOURS` (30 h), Wiederherstellungstest fehlgeschlagen |
| Speicherplatz | ≥ `DISK_WARN_PCT` (80 %) | ≥ `DISK_CRITICAL_PCT` (90 %) |
| Auslastung | weniger als 7,5 % Arbeitsspeicher frei | – |

Das Ergebnis steht im Dashboard unter **System**. Wird eine Prüfung schlechter, entsteht eine Benachrichtigung, ebenso wenn sie sich wieder erholt. Ein andauerndes Problem wird nur einmal gemeldet.

**Uptime Kuma** (Profil `monitoring`, nur unter `127.0.0.1:3001`; Zugriff per SSH-Tunnel `ssh -L 3001:127.0.0.1:3001 server`) überwacht von außen und verschickt die Alarme über die dort eingerichteten Kanäle (E-Mail, Telegram usw.):

1. **HTTP-Monitor** auf `http://backend:8000/api/health/ready`. Er meldet einen Ausfall von Backend, Datenbank oder Redis.
2. **HTTP-Monitor** auf `https://<DOMAIN>/healthz`. Er meldet einen Ausfall von Caddy, TLS oder DNS.
3. **Push-Monitor** (Intervall z. B. 120 s). Die Push-URL kommt als `UPTIME_KUMA_PUSH_URL` in `.env`. Die Zeitsteuerung meldet dann bei jeder Prüfung „up“ oder „down“, sobald eine Prüfung kritisch ist; der Grund steht in der Meldung. Bleiben die Meldungen aus, ist die Zeitsteuerung selbst ausgefallen, und Uptime Kuma schlägt ebenfalls Alarm.

**Protokolle:** Alle Dienste schreiben JSON-Zeilen mit maskierten Geheimnissen nach stdout (`docker compose logs -f backend worker scheduler backup`). Docker rotiert sie (10 MB × 5 je Dienst).

## 3a. Speicherplatz und Aufräumen (Erweiterung E10)

```bash
docker compose exec -T backend python -m app.housekeeping report            # was liegt wo, Hochrechnung 1 Jahr
docker compose exec -T backend python -m app.housekeeping cleanup           # Probelauf: zeigt nur
docker compose exec -T backend python -m app.housekeeping cleanup --apply   # löscht
```

Gelöscht werden nur Arbeitsdateien in `media/tmp` (älter als 6 h, ohne `tmp/uploads`) und gespeicherte Dateien, auf die keine Datenbankzeile mehr verweist (älter als 7 Tage). Regeln, Speicherbedarf und Cron-Vorschlag: [HETZNER_VORBEREITUNG.md](HETZNER_VORBEREITUNG.md).

## 4. Datensicherung

Der Dienst `backup` sichert täglich um `BACKUP_HOUR` Uhr (Zeitzone `TZ`). Beim Start sichert er sofort, wenn die letzte Sicherung älter als ein Tag ist.

1. `pg_dump` im Custom-Format. Die Zeilenzahlen aller Tabellen stammen aus demselben Datenbank-Schnappschuss wie die Sicherung.
2. Die Sicherung wird mit GnuPG verschlüsselt (symmetrisch, AES-256, Schlüssel `BACKUP_PASSPHRASE`). Unverschlüsselt landet nichts auf der Platte.
3. Daneben liegt ein Manifest (`*.json`) mit Größe, SHA-256, Schema-Version und Zeilenzahlen.
4. **Wiederherstellungstest:** Die neue Sicherung wird in eine leere Datenbank `<db>_restore_check` entschlüsselt und eingespielt. Prüfsumme, Schema-Version, Tabellen und jede Zeilenzahl müssen übereinstimmen. Danach wird die Testdatenbank gelöscht.
5. Ältere Sicherungen als `BACKUP_KEEP_DAYS` (14 Tage) werden gelöscht, die neuesten `BACKUP_KEEP_MIN` (3) bleiben immer erhalten.

Bei einem Fehler gibt es eine kritische Benachrichtigung, und die Systemprüfung schlägt Alarm.

Die Sicherungen liegen im Volume `backup_data`. **Kopie außerhalb des Servers:** Sie sind bereits verschlüsselt und können unverändert kopiert werden. Möglich sind die Hetzner Storage Box oder Cloudflare R2, sobald die Kosten geprüft und freigegeben sind; bis dahin mindestens die Server-Snapshots von Hetzner verwenden.

Befehle:

```bash
docker compose run --rm backup python -m app.backup run           # jetzt sichern + testen
docker compose run --rm backup python -m app.backup list          # Übersicht
docker compose run --rm backup python -m app.backup restore-test  # neueste Sicherung testen
```

## 5. Wiederherstellung

Die Wiederherstellung geht immer in eine **neue** Datenbank. Die laufende wird nie überschrieben.

```bash
docker compose stop backend worker scheduler backup
docker compose run --rm backup python -m app.backup list
docker compose run --rm backup python -m app.backup restore gce-JJJJMMTT-HHMMSS.dump.gpg --into gce_restored --yes
# Prüfen, dann umschalten: POSTGRES_DB=gce_restored in .env setzen (die alte Datenbank bleibt erhalten)
./scripts/deploy.sh <commit-zur-sicherung-passend>
```

Ist der ganze Server verloren: Server neu aufsetzen (Abschnitt 1), die Sicherungsdateien samt Manifest in das Volume `backup_data` kopieren und `BACKUP_PASSPHRASE` eintragen. Danach wie oben wiederherstellen.

Bei Verlust des `CREDENTIALS_ENCRYPTION_KEY` sind die gespeicherten Plattform-Tokens nicht mehr lesbar. Die Kanäle müssen dann neu verbunden werden; alle anderen Daten sind nicht betroffen.

## 6. Server-Härtung

`infrastructure/server/harden.sh` (als root, wiederholbar, mit `--dry-run` zur Vorschau):

- automatische Sicherheitsupdates (`unattended-upgrades`);
- Firewall `ufw`: eingehend nur 22 (mit Rate-Limit), 80 und 443;
- SSH nur mit Schlüssel, kein Passwort-Login, root nur mit Schlüssel. Das Skript bricht ab, wenn kein SSH-Schlüssel hinterlegt ist;
- `fail2ban` für SSH;
- Docker-Protokollrotation.

Alle Container außer Caddy lauschen nur auf `127.0.0.1`. Deshalb öffnen die Docker-Portregeln nichts an der Firewall vorbei. Empfohlen wird zusätzlich eine Hetzner Cloud Firewall mit denselben Regeln.

## 7. Lasttest

`scripts/load_test.py` meldet sich einmal an und ruft dann gleichzeitig die lesenden Endpunkte des Dashboards ab. Es ändert nichts und veröffentlicht nichts.

```bash
LOAD_TEST_EMAIL=… LOAD_TEST_PASSWORD=… python scripts/load_test.py --users 20 --seconds 30
```

Ergebnis in der Entwicklungsumgebung (ein Uvicorn-Prozess, 4 Kerne, Worker rendert parallel):

| Endpunkt | Anfragen | p50 | p95 |
|---|---|---|---|
| `/api/health/ready` | 322 | 117 ms | 182 ms |
| `/api/overview` | 325 | 171 ms | 249 ms |
| `/api/agents` | 324 | 189 ms | 281 ms |
| `/api/trends` | 325 | 151 ms | 237 ms |
| `/api/analytics/overview` | 328 | 153 ms | 252 ms |
| `/api/costs/summary` | 329 | 730 ms | 894 ms |
| `/api/system/status` | 322 | 314 ms | 413 ms |

Gesamt: 20 gleichzeitige Clients, 75 Anfragen/s, p95 757 ms, keine Fehler. Das Dashboard wird von einer Person bedient, das ist also ein Vielfaches des Bedarfs. Die Grenze setzt die Videoproduktion (FFmpeg), nicht die API. Wird die API doch einmal zum Engpass, kann Uvicorn mit mehreren Prozessen gestartet werden (`--workers 2`).

## 8. Skalierungskriterien

Skaliert wird nur, wenn Messwerte einen **dauerhaften** Engpass zeigen (Spezifikation Abschnitt 14, Stufe 8). Die Zeitsteuerung speichert dazu bei jeder Prüfung einen Messwert: Wartezeit, wartende Aufträge, CPU-Last je Kern, freier Arbeitsspeicher, belegter Speicher. Die Seite **System** wertet die letzten 6 Stunden aus. Eine Empfehlung gibt es erst, wenn Messwerte über mindestens 3 Stunden vorliegen und der Engpass in mindestens 75 % davon auftritt. Eine einzelne Spitze reicht nie.

| Befund | Empfehlung |
|---|---|
| Aufträge warten > 30 min **und** CPU > 90 % je Kern | Mehr Renderkapazität: größerer Server oder zweiter Render-Server |
| Aufträge warten > 30 min, CPU hat Reserven | weiteren Worker starten (`docker compose up -d --scale worker=2`), ggf. „Parallele Render-Jobs“ in den Einstellungen erhöhen |
| weniger als 15 % Arbeitsspeicher frei | mehr Arbeitsspeicher |
| Speicher ≥ 80 % belegt | Speicher erweitern oder fertige Medien nach Cloudflare R2 auslagern |
| nichts davon | keine Skalierung nötig |

Jede Skalierung kostet Geld. Sie wird deshalb nur empfohlen und nie automatisch ausgeführt; die Entscheidung trifft der Betreiber mit Blick auf das Budget.
