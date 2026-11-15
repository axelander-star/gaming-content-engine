# Checkliste für den Produktivstart auf Hetzner Cloud

**Stand:** 15.11.2026 · **Grundlage:** Code auf `main` (Phase 15), [OPERATIONS.md](OPERATIONS.md), [SECURITY.md](SECURITY.md), [API_INTEGRATIONS.md](API_INTEGRATIONS.md), die Plattform-Recherche [PLATFORM_PUBLISHING_REVIEW.md](PLATFORM_PUBLISHING_REVIEW.md) (PR #17), [ACCEPTANCE_TEST.md](ACCEPTANCE_TEST.md) und [ROADMAP.md](ROADMAP.md) (PR #18) sowie [PRIVATE_ACCESS.md](PRIVATE_ACCESS.md).

**Geändert am 15.11.2026: rein private Nutzung.** Die Anwendung ist nur für den Betreiber bestimmt, kein öffentliches Produkt. Sie ist nur über Cloudflare Access erreichbar, der Server hat keine offenen Web-Ports (Cloudflare Tunnel), es gibt keine öffentlichen Seiten, keine Registrierung und nur ein Benutzerkonto. Anforderungen an eine öffentliche Website wurden gestrichen; Details und Begründung in [PRIVATE_ACCESS.md](PRIVATE_ACCESS.md).

Diese Liste sagt, was bis zum 24/7-Betrieb auf einem Hetzner-Server noch fehlt. Sie wiederholt keine Recherche, sondern baut auf den genannten Dokumenten auf. Was im Code schon gebaut ist, steht als **erledigt** da und wird nicht neu gefordert.

**Grundregeln für alle Punkte**

- Nichts Kostenpflichtiges wird aktiviert, bevor der Betreiber es ausdrücklich freigibt. Alle Preise in dieser Liste sind Richtwerte vom 15.11.2026 und müssen vor dem Kauf beim Anbieter bestätigt werden.
- Zugangsdaten gehören in einen Passwortmanager und auf dem Server in die Datei `.env` (nicht eingecheckt). Nie in `.env.example`, nie in den Chat, nie in ein Issue.
- `AUTO_PUBLISH_ENABLED=false` und `PUBLISHING_MODE=mock` bleiben Standard, bis die erste echte Veröffentlichung je Plattform einzeln freigegeben ist.

**Legende**

| Zeichen | Bedeutung |
|---|---|
| ✅ erledigt | vorhanden und geprüft (im Code: gebaut und getestet) |
| ⬜ offen | noch zu tun |
| ⚠️ | Angabe beim Anbieter vor der Umsetzung bestätigen |
| 💶 | verursacht Kosten, nur nach Freigabe |
| P1 / P2 / P3 | P1 = Pflicht vor dem Start · P2 = Pflicht vor der ersten echten Veröffentlichung · P3 = später / optional |

---

## 1. Kurzfassung

1. **Das Grundgerüst für den Server ist fertig:** Dockerfiles, Docker Compose mit Neustarts und Healthchecks, Caddy mit automatischem HTTPS, Härtungs-Skript, Deploy-Skript mit Rücksprung, verschlüsselte tägliche Sicherung mit Wiederherstellungstest, Systemüberwachung mit Uptime Kuma.
2. **Was der Code für den Betrieb noch braucht:** Ablage der Videos in Cloudflare R2, Kopie der Sicherungen außerhalb des Servers, automatisches Aufräumen alter Mediendateien, automatisches Deployment über GitHub Actions, Zwei-Faktor-Anmeldung, Upload in Teilstücken (Cloudflare lässt höchstens 100 MB je Anfrage durch), echte Anbieter für KI-Texte und Stimme, X/Twitter-Anbindung, TikTok-Entwurfsmodus, Instagram Login.
3. **Was nur du erledigen kannst:** Konten und Entwickler-Apps anlegen, Domain kaufen, Server bestellen, Zahlungsarten hinterlegen, Schlüssel erneuern, rechtliche Texte und Lizenzen beschaffen, Entscheidungen zu TikTok, X und den KI-Anbietern treffen.
4. **Privater Zugang:** Cloudflare Tunnel + Cloudflare Access sind im Code vorbereitet (Zugangsprüfung im Backend, Einzelbenutzer-Modus, Tunnel-Dienst). Einrichtung erst nach deiner Prüfung, kostenlos ⚠️.
5. **Sofort nötig:** YouTube-API-Key und Twitch-Client-Secret erneuern. Beide standen mehrfach in `.env.example` und sind damit in der Git-Historie sichtbar.
6. **Plattformgrenzen, die bleiben:** Twitch hat keine Upload-API (nur Datenquelle). TikTok erlaubt ohne Prüfung nur private Posts, und die Prüfung schließt private Apps ausdrücklich aus („Apps must not be for private or personal use“) → TikTok halbautomatisch. X kostet je Post Geld (Prepaid-Guthaben).
7. **Laufende Kosten beim geplanten Aufbau:** grob 12–17 € im Monat ohne KI (Server, Server-Backup, Domain, R2), dazu die KI-Nutzung nach Verbrauch. Das passt in das Budget von ca. 50 €/Monat, wenn für die KI-Dienste ein festes Ausgabenlimit gesetzt wird (Abschnitt 10).

---

## 2. Haupttabelle

### A. Was du persönlich erledigen musst

| # | Aufgabe | Wo muss ich das erledigen? | Benötigte Unterlagen oder Informationen | Kosten | Prio | Status |
|---|---|---|---|---|---|---|
| A1 | YouTube-API-Key **neu erstellen**, alten löschen | Google Cloud Console → APIs & Dienste → Anmeldedaten | Zugang zum Google-Cloud-Projekt | 0 € | P1 | ⬜ offen |
| A2 | Twitch-Client-Secret **neu erstellen** (alter war eingecheckt) | dev.twitch.tv → Console → Anwendung → „Neues Geheimnis“ | Twitch-Konto mit 2FA | 0 € | P1 | ⬜ offen |
| A3 | Neue Werte nur in Passwortmanager und Cloud-Umgebung eintragen, danach Verbindungstest im Dashboard | Passwortmanager; claude.ai Umgebungseinstellungen; später `.env` auf dem Server | neue Schlüssel | 0 € | P1 | ⬜ offen |
| A4 | Zwei-Faktor-Anmeldung auf **allen** Anbieter-Konten einschalten (Google, GitHub, Hetzner, Cloudflare, Meta, TikTok, X, OpenAI, Domain-Anbieter) | jeweilige Sicherheitseinstellungen | Authenticator-App, sichere Ablage der Wiederherstellungscodes | 0 € | P1 | ⬜ offen |
| A5 | Passwortmanager mit eigenem Tresor „Gaming Content Engine“ anlegen | z. B. Bitwarden, 1Password, KeePassXC | – | 0–3 €/Monat | P1 | ⬜ offen |
| A6 | Domain registrieren (z. B. für Dashboard und Rechtstexte) | Domain-Anbieter (z. B. Cloudflare Registrar, INWX, Hetzner) | Name, Anschrift, Zahlungsart | 💶 ca. 5–15 €/Jahr | P1 | ⬜ offen |
| A7 | Hetzner-Konto anlegen und Identität bestätigen | accounts.hetzner.com | Ausweis oder Zahlungsnachweis ⚠️ (Hetzner prüft Neukunden), Zahlungsart | 0 € | P1 | ⬜ offen |
| A8 | Server bestellen (Freigabe nötig) | Hetzner Cloud Console → Projekt → Server | Standort (Falkenstein oder Nürnberg), Ubuntu 24.04, SSH-Schlüssel | 💶 CX33: 8,49 € netto + 0,50 € IPv4 ⚠️ (siehe Abschnitt 10) | P1 | ⬜ offen |
| A9 | SSH-Schlüsselpaar auf deinem Rechner erzeugen (Ed25519, mit Passphrase), öffentlichen Teil bei Hetzner hinterlegen | eigener Rechner, Hetzner Cloud Console → Sicherheit → SSH-Keys | – | 0 € | P1 | ⬜ offen |
| A10 | Cloudflare-Konto anlegen, R2 aktivieren (Freigabe nötig) | dash.cloudflare.com → R2 | Zahlungsart (Cloudflare verlangt sie auch im Freikontingent ⚠️) | 💶 0 € bis wenige €/Monat | P1 | ⬜ offen |
| A11 | Entscheidung: Offsite-Backup in R2 (empfohlen) oder Hetzner Storage Box | – | Empfehlung in PR #17, Abschnitt 6 | R2 ≈ 0–1 €; BX11 3,20 € netto | P1 | ⬜ offen |
| A12 | Google-OAuth-Client für YouTube-Uploads anlegen, Zustimmungsbildschirm einrichten, App auf **„In production“** stellen (sonst verfällt die Verbindung nach 7 Tagen); Google-Prüfung ist bei persönlicher Nutzung nicht nötig | Google Cloud Console → Google Auth Platform | Link zur Rechtstext-Seite (A30), Rückleitungs-URL `https://<domain>/api/oauth/youtube/callback`, eigenes Konto als Nutzer | 0 € | P2 | ⬜ offen |
| A13 | YouTube-Kanäle anlegen (DE, EN, je als Brand-Kanal) und per Telefon bestätigen | youtube.com, YouTube Studio | Telefonnummer | 0 € | P2 | ⬜ offen |
| A14 | Meta: Entwicklerkonto, App vom Typ „Business“ anlegen; klären, ob Posts im Entwicklungsmodus öffentlich sichtbar sind, sonst Live-Modus ⚠️ | developers.facebook.com | Facebook-Konto, Kontakt-E-Mail, App-Icon; für den Live-Modus Nutzungsbedingungen-URL (A30) ⚠️ | 0 € | P2 | ⬜ offen |
| A15 | Facebook-Seite(n) anlegen; Instagram-Konten in **Profikonten** (Business oder Creator) umstellen und mit der Seite verknüpfen | Facebook, Instagram-App → Einstellungen → Kontotyp | – | 0 € | P2 | ⬜ offen |
| A16 | ~~TikTok-App~~ **entfällt** bei der empfohlenen halbautomatischen Lösung: TikTok prüft keine Apps für private Nutzung. Optional nur Sandbox für private Testposts | developers.tiktok.com (nur falls Sandbox) | – | 0 € | P3 | ⬜ offen |
| A17 | **Entscheidung TikTok:** Empfehlung jetzt B) halbautomatisch (Datei und Text fertig, Upload in der TikTok-App); A) Entwurfs-Upload braucht eine geprüfte App und entfällt damit | – | [PRIVATE_ACCESS.md](PRIVATE_ACCESS.md), Abschnitt 4 | 0 € | P2 | ⬜ offen |
| A18 | **Entscheidung X/Twitter:** anbinden ja/nein (Abschnitt 4.6) | – | Kosten je Post, Prepaid-Guthaben | 💶 nach Verbrauch | P3 | ⬜ offen |
| A19 | **Entscheidung KI-Anbieter** für Texte, Stimme, Transkription (Abschnitt 5) | – | Kostenvergleich, Nutzungsrechte | 💶 nach Verbrauch | P2 | ⬜ offen |
| A20 | KI-Konto anlegen (z. B. OpenAI oder Anthropic), Projekt nur für dieses System, **hartes Monatslimit** setzen | Plattform des Anbieters → Limits | Zahlungsart, Budgetbetrag | 💶 nach Verbrauch | P2 | ⬜ offen |
| A21 | Rechtstexte: kurze Datenschutzerklärung und Nutzungsbedingungen für die Plattform-Apps (Google, Meta). **Kein Impressum für den Server nötig** (keine Dienste für andere); Impressum nur auf den Social-Media-Profilen, sobald sie monetarisiert werden | Generator (z. B. eRecht24) oder Anwalt | Name, Kontakt-E-Mail, Liste der Dienstleister | 0 € bis 💶 | P2 | ⬜ offen |
| A22 | Auftragsverarbeitungsverträge (AVV/DPA) abschließen | Hetzner Konsole (AVV online), Cloudflare DPA, KI-Anbieter DPA | Firmendaten | 0 € | P2 | ⬜ offen |
| A23 | Rechte am Gameplay klären und als Lizenz mit Nachweis im Dashboard erfassen | Publisher-Richtlinien, eigene Aufnahmen, Verträge; Dashboard → Rechte | Lizenztexte, Screenshots der Richtlinie, Verträge als PDF | 0 € bis 💶 | P2 | ⬜ offen |
| A24 | Musik und Bildmaterial nur mit Lizenz für kommerzielle Social-Media-Nutzung | Musikbibliothek mit passender Lizenz | Lizenzurkunden | 0 € bis 💶 | P2 | ⬜ offen |
| A25 | Gewerbe und Steuern klären, sobald Einnahmen geplant sind (Partnerprogramme, Werbung) | Gewerbeamt, Finanzamt, Steuerberatung | Personalausweis | 💶 Gebühr Gewerbeamt | P3 | ⬜ offen |
| A26 | Alarmkanal für Uptime Kuma festlegen (E-Mail oder Telegram) | Telegram-Bot oder SMTP-Zugang | Bot-Token bzw. SMTP-Daten | 0 € | P1 | ⬜ offen |
| A27 | Bekannte Lücke in der Git-Historie bewerten: alte Schlüssel stehen weiter in alten Commits | – | nach Erneuerung (A1, A2) sind sie wertlos; eine Bereinigung der Historie ist dann nicht nötig | 0 € | P1 | ⬜ offen |
| A28 | Pull Request #18 (Abnahmetest, Roadmap) prüfen und mergen lassen; #17 (Plattform-Recherche) ist gemergt | GitHub | – | 0 € | P1 | ⬜ offen |
| A29 | Cloudflare Zero Trust aktivieren (Gratistarif), Domain auf Cloudflare-Nameserver, Tunnel und Access-Anwendung anlegen (Einrichtung gemeinsam, Schritt für Schritt) | dash.cloudflare.com → Zero Trust | Domain, deine E-Mail-Adresse | 0 € ⚠️ (evtl. Zahlungsart nötig) | P1 | ⬜ offen |
| A30 | **Entscheidung Rechtstext-Seite:** Variante 1 eine einzige statische Textseite auf der eigenen Domain, als einziger Pfad von Access freigegeben (empfohlen), oder Variante 2 extern | – | [PRIVATE_ACCESS.md](PRIVATE_ACCESS.md), Abschnitt 4 | 0 € | P2 | ⬜ offen |

### B. Was der Coding-Agent vorbereiten kann

Diese Punkte sind Programmierarbeit im Mock-Modus. Sie kosten nichts und brauchen keine echten Zugangsdaten.

| # | Aufgabe | Wo? | Benötigte Unterlagen oder Informationen | Kosten | Prio | Status |
|---|---|---|---|---|---|---|
| B1 | Dockerfiles für Backend (mit FFmpeg, GnuPG, pg-Client) und Dashboard | `backend/Dockerfile`, `frontend/Dockerfile` | – | 0 € | P1 | ✅ erledigt |
| B2 | Docker Compose mit PostgreSQL, Redis, Migration, API, Worker, Zeitsteuerung, Backup, Dashboard, Caddy, Uptime Kuma; `restart: unless-stopped`, Healthchecks, Log-Rotation | `docker-compose.yml` | – | 0 € | P1 | ✅ erledigt |
| B3 | `.env.example` mit allen Variablen, ohne echte Werte | `.env.example` | – | 0 € | P1 | ✅ erledigt (Stand `main` geprüft: Schlüsselfelder leer) |
| B4 | Caddy mit Sicherheitsheadern; HTTPS über Cloudflare (Tunnel) oder alternativ Let’s Encrypt | `infrastructure/caddy/Caddyfile` | – | 0 € | P1 | ✅ erledigt |
| B5 | Server-Härtung (Firewall, SSH nur mit Schlüssel, fail2ban, automatische Updates) | `infrastructure/server/harden.sh` | – | 0 € | P1 | ✅ erledigt |
| B6 | Deploy mit Vorab-Sicherung, Healthcheck und Rücksprung | `scripts/deploy.sh` | – | 0 € | P1 | ✅ erledigt |
| B7 | Tägliche verschlüsselte Datenbanksicherung mit Wiederherstellungstest | Dienst `backup`, `services/backup.py` | `BACKUP_PASSPHRASE` | 0 € | P1 | ✅ erledigt |
| B8 | Systemüberwachung (DB, Redis, Worker, Warteschlangen, Fehlerquote, Speicherplatz, Backup-Alter) und Uptime-Kuma-Push | `scheduler`, Seite „System“ | `UPTIME_KUMA_PUSH_URL` | 0 € | P1 | ✅ erledigt |
| B9 | Strukturierte JSON-Logs mit maskierten Geheimnissen | Backend-Logger | – | 0 € | P1 | ✅ erledigt |
| B10 | Fehlerbehandlung: Wiederholungen mit Backoff, Not-Aus, Gates je Auftrag, Idempotenz bei Veröffentlichungen | Master Agent, `services/workflow.py` | – | 0 € | P1 | ✅ erledigt |
| B11 | Verschlüsselte Ablage der OAuth-Tokens und Schlüsselwechsel | `channel_credentials`, `app.rotate_credentials` | – | 0 € | P1 | ✅ erledigt |
| B12 | CI: Lint, Typprüfung, Tests, Migrationsprüfung, Secret-Prüfung, Image-Builds, E2E | `.github/workflows/ci.yml` | – | 0 € | P1 | ✅ erledigt |
| B13 | **Automatisches Deployment über GitHub Actions** (nach grüner CI auf `main`, per SSH mit eigenem Deploy-Benutzer, GitHub-Environment „production“ mit manueller Bestätigung) | neue Datei `.github/workflows/deploy.yml` | Server-IP, Deploy-SSH-Schlüssel, `known_hosts` (alles als GitHub Secrets, siehe C9) | 0 € | P2 | ⬜ offen |
| B14 | **Cloudflare-R2-Speicher im Code** (heute nur Variablen in `.env.example`; Dateien liegen lokal unter `MEDIA_ROOT`): fertige Clips und Nachweise nach R2, lokale Kopie danach löschen | `services/storage.py` | – (Test gegen S3-Mock) | 0 € | P1 | ⬜ offen |
| B15 | **Offsite-Kopie der Sicherungen** nach R2 (eigener Bucket, Schreib-Token ohne Löschrecht) und Prüfung auf der Seite „System“ | Dienst `backup` | Entscheidung A11 | 0 € | P1 | ⬜ offen |
| B16 | **Aufräumen von Mediendateien:** verwaiste Dateien in `media/tmp` nach Absturz löschen, Rohmaterial und lokale Clips nach Aufbewahrungsfrist löschen, ab `DISK_WARN_PCT` keine neuen Render-Jobs mehr annehmen | Zeitsteuerung, `services/storage.py` | Aufbewahrungsfristen (Vorschlag Abschnitt 7) | 0 € | P1 | ⬜ offen |
| B17 | Zwei-Faktor-Anmeldung (TOTP) für Admins | Backend + Dashboard (Roadmap B1) | – | 0 € | P1 | ⬜ offen |
| B18 | ~~Öffentliche Seiten `/impressum` und `/datenschutz`~~ **gestrichen** (private Nutzung). Stattdessen: Zugangsschutz Cloudflare Access im Backend, Einzelbenutzer-Modus, Tunnel-Dienst, Firewall-Option `--tunnel` | `core/access_guard.py`, `docker-compose.yml`, `harden.sh` | – | 0 € | P1 | ✅ erledigt (PR zur privaten Nutzung) |
| B19 | Adapter für Sprachmodell (Texte, Hooks, Titel) mit Kostenzählung und Budgetstopp | `services/llm.py` (Gerüst vorhanden, Anbieterliste leer) | Entscheidung A19 | 0 € (Entwicklung) | P2 | ⬜ offen |
| B20 | Adapter für Text-zu-Sprache mit Kennzeichnung „KI-Stimme“ | `services/voice.py` (Gerüst vorhanden) | Entscheidung A19 | 0 € | P2 | ⬜ offen |
| B21 | Lokale Transkription (z. B. faster-whisper auf der CPU) für Originalton im Gameplay, falls gewünscht | neuer Dienst | – | 0 € (läuft auf dem Server) | P3 | ⬜ offen |
| B22 | TikTok halbautomatisch: fertige Datei, Titel und Hashtags im Dashboard zum Herunterladen bereitstellen (statt API) | Dashboard | Entscheidung A17 | 0 € | P2 | ⬜ offen |
| B23 | Instagram Login (ohne Facebook-Seite) als zweiter Weg | `services/meta.py` | – | 0 € | P3 | ⬜ offen |
| B24 | X/Twitter-Adapter (OAuth 2.0 mit PKCE, Video-Upload, Post) mit Kostenzählung je Post | neuer Adapter | Entscheidung A18 | 0 € | P3 | ⬜ offen |
| B25 | Warnung im Dashboard, wenn das Tageslimit für Produktionsaufträge die Pipeline anhält | Dashboard (Roadmap A2) | – | 0 € | P2 | ⬜ offen |
| B26 | KI-Kennzeichnung beim Upload setzen (YouTube „veränderte oder synthetische Inhalte“, TikTok „KI-generiert“, Meta „KI-Info“), wo die API es erlaubt ⚠️ | Publishing-Adapter | – | 0 € | P2 | ⬜ offen |
| B27 | Betriebsanleitung um R2, Offsite-Backup und Deploy-Workflow ergänzen | `docs/OPERATIONS.md` | – | 0 € | P2 | ⬜ offen |
| B28 | **Upload in Teilstücken** (< 100 MB je Anfrage), damit Gameplay-Dateien bis 4 GB durch Cloudflare passen | `api/rights.py`, Dashboard | – | 0 € | P1 | ⬜ offen |
| B29 | Rechtstext-Seite nach Entscheidung A30 (eine statische Seite, ohne Verbindung zur Anwendung) | Caddy | Texte aus A21 | 0 € | P2 | ⬜ offen |

### C. Was bei der Einrichtung des Hetzner-Servers erledigt wird

Reihenfolge wie in [OPERATIONS.md](OPERATIONS.md), Abschnitt 1. Die Schritte führst du aus; der Agent kann jeden Befehl vorbereiten und erklären.

| # | Aufgabe | Wo? | Benötigte Unterlagen oder Informationen | Kosten | Prio | Status |
|---|---|---|---|---|---|---|
| C1 | Hetzner Cloud Firewall: eingehend **nur 22** (am besten nur von deiner IP); dem Server zuweisen | Hetzner Cloud Console → Firewalls | eigene IP-Adresse | 0 € | P1 | ⬜ offen |
| C2 | Server-Backups von Hetzner einschalten (tägliche Abbilder, 7 Stück) | Server → Backups | Freigabe | 💶 +20 % des Serverpreises ⚠️ (≈ 1,70 €) | P1 | ⬜ offen |
| C3 | DNS: Domain auf Cloudflare-Nameserver; der Hostname für das Dashboard entsteht beim Anlegen des Tunnels (kein A-Eintrag auf die Server-IP nötig) | Domain-Anbieter, Cloudflare DNS | – | 0 € | P1 | ⬜ offen |
| C4 | Eigenen Benutzer mit `sudo` anlegen, SSH-Schlüssel hinterlegen, dann `harden.sh --tunnel --dry-run`, danach ohne `--dry-run` | Server (SSH) | SSH-Schlüssel aus A9 | 0 € | P1 | ⬜ offen |
| C5 | Docker Engine mit Compose-Plugin nach offizieller Anleitung installieren; Benutzer `deploy` ohne sudo, nur Docker-Gruppe | Server | – | 0 € | P1 | ⬜ offen |
| C6 | Repository auf den Server holen: **Deploy-Key nur mit Leserecht** für das private Repo | GitHub → Repo → Settings → Deploy keys | öffentlicher Schlüssel vom Server | 0 € | P1 | ⬜ offen |
| C7 | `.env` aus `.env.example` erzeugen, alle Pflichtwerte setzen (`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `SECRET_KEY`, `CREDENTIALS_ENCRYPTION_KEY`, `BACKUP_PASSPHRASE`, `APP_ENV=production`) und für den privaten Betrieb `ACCESS_GUARD=cloudflare`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`, `CF_ACCESS_ALLOWED_EMAILS`, `SINGLE_USER_MODE=true`, `CLOUDFLARE_TUNNEL_TOKEN`, `CADDY_BIND=127.0.0.1`; Dateirechte `600` | Server | zufällig erzeugte Werte; Kopie von `BACKUP_PASSPHRASE` und `CREDENTIALS_ENCRYPTION_KEY` in den Passwortmanager | 0 € | P1 | ⬜ offen |
| C8 | `./scripts/deploy.sh`, danach ersten Admin anlegen (`python -m app.create_admin`) | Server | E-Mail, starkes Passwort | 0 € | P1 | ⬜ offen |
| C9 | GitHub Secrets für das automatische Deployment anlegen (nur SSH-Zugang, **keine** App-Schlüssel) | GitHub → Settings → Environments → production | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` | 0 € | P2 | ⬜ offen |
| C10 | Uptime Kuma per SSH-Tunnel einrichten: interner HTTP-Monitor auf das Backend, Push-Monitor, Alarmkanal aus A26. Ein Monitor auf die öffentliche Adresse wird von Access blockiert (nur mit Access-Service-Token) | Server, `127.0.0.1:3001` | Push-URL nach `.env` | 0 € | P1 | ⬜ offen |
| C11 | R2: zwei Buckets (`media`, `backups`) in EU-Jurisdiktion ⚠️, je ein API-Token mit minimalen Rechten, Lebenszyklus-Regeln; Werte in `.env` | Cloudflare → R2 | Freigabe A10 | 💶 siehe Abschnitt 10 | P1 | ⬜ offen |
| C12 | Erste Sicherung und Wiederherstellungstest auf dem Server, dann eine Rücksicherung in eine Testdatenbank von Hand üben | Server | – | 0 € | P1 | ⬜ offen |
| C13 | Echte Trendquellen einschalten (`TREND_SOURCES_MODE=live`), Twitch-Helix-Abfrage prüfen (in der Entwicklungsumgebung nicht prüfbar) | Server, Dashboard | Schlüssel aus A1, A2 | 0 € | P1 | ⬜ offen |
| C14 | OAuth-Rückleitungs-URLs bei Google, Meta, TikTok (und X) auf `https://<domain>/api/oauth/<plattform>/callback` eintragen, gleiche Werte in `.env` (`*_OAUTH_REDIRECT_URI`); Kanäle im Dashboard verbinden | Entwicklerportale, Dashboard | Domain mit HTTPS | 0 € | P2 | ⬜ offen |
| C15 | Kanäle entpausieren (neue Kanäle starten pausiert) | Dashboard → Publishing | – | 0 € | P2 | ⬜ offen |
| C16 | Je Plattform eine erste **private** Testveröffentlichung, nach einzelner Freigabe | Dashboard | Freigabe je Plattform | 0 € (X 💶) | P2 | ⬜ offen |
| C17 | Prüfen: ohne Anmeldung nur die Cloudflare-Anmeldeseite; Server-IP direkt nicht erreichbar; Zugriff von PC und Handy; nach Neustart des Servers läuft alles wieder | Browser, Server | – | 0 € | P1 | ⬜ offen |

---

## 3. API-Zugänge und Entwicklerkonten

| Dienst | Konto | Zu beantragende API / Produkt | Berechtigungen (Scopes) | App-Prüfung nötig? | Laufende Kosten | Stand |
|---|---|---|---|---|---|---|
| **YouTube** | Google-Konto, Google-Cloud-Projekt | YouTube Data API v3 (Trends), YouTube Analytics API, OAuth-Client „Webanwendung“ | `youtube.upload`, `youtube.readonly`, `yt-analytics.readonly` | Für eigene Kanäle im Testmodus nicht; **aber:** Refresh-Tokens im Testmodus laufen nach 7 Tagen ab ⚠️. Für Dauerbetrieb App auf „In Produktion“, dann verlangt Google für `youtube.upload` eine Verifizierung ⚠️. Höheres Kontingent nur per Antrag | 0 € (Kontingent: 10.000 Einheiten/Tag, Uploads 100/Tag je Projekt) | API-Key gültig getestet 15.11.; OAuth-Client fehlt |
| **Twitch** | Twitch-Konto mit 2FA | Twitch-Anwendung (Client Credentials) | keine (App-Token); für eigene Clips später Benutzer-OAuth `clips:edit` | nein | 0 € | Client-ID + Secret gültig getestet 15.11.; Secret erneuern |
| **TikTok** | TikTok-Konto; Entwicklerkonto nur für die Sandbox | Login Kit, Content Posting API (gebaut) | gebaut: `video.publish`, `video.list` | Prüfung schließt private Apps aus („Apps must not be for private or personal use“); ohne Prüfung nur Sandbox, keine öffentlichen Videos | 0 € | gebaut, für private Nutzung nicht verwendbar → halbautomatisch |
| **Instagram** | Meta-Entwicklerkonto, Business-Portfolio, Instagram-Profikonto, Facebook-Seite | Facebook Login for Business (gebaut) oder Instagram Login (fehlt) | gebaut: `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, `pages_show_list`; für Instagram Login (B23): `instagram_business_basic`, `instagram_business_content_publish` | Für Konten mit Rolle in der App nicht ⚠️; App muss trotzdem „Live“ sein, dafür Datenschutz-URL nötig | 0 € | gebaut, nie echt ausgeführt |
| **Facebook** | wie Instagram, Seite mit Aufgabe `CREATE_CONTENT` | Facebook Login for Business, Video API (Reels) | `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement`, `read_insights` | wie Instagram | 0 € | gebaut, nie echt ausgeführt |
| **X / Twitter** | X-Konto, Entwicklerkonto (console.x.com) | X API v2: Posts, Media Upload | OAuth 2.0 mit PKCE: `tweet.read`, `tweet.write`, `users.read`, `media.write`, `offline.access` ⚠️ | kein Audit, aber Prepaid-Guthaben | 💶 nach Verbrauch (Abschnitt 4.6) | **fehlt im Code** |
| **KI-Anbieter** (z. B. OpenAI, Anthropic) | Organisation, Projekt nur für dieses System | Text-API; ggf. Sprache/Transkription | API-Key mit Projektbindung | nein | 💶 nach Verbrauch | Gerüst im Code, Anbieter nicht angebunden |
| **Cloudflare R2** | Cloudflare-Konto | R2 Object Storage | API-Token je Bucket: `media` Lesen+Schreiben, `backups` nur Schreiben | nein | 💶 ab 10 GB/Monat | Variablen vorhanden, Code fehlt (B14) |
| **Hetzner Cloud** | Hetzner-Konto (Identitätsprüfung) | Cloud-Projekt, ggf. API-Token nur für Snapshots | – | nein | 💶 monatlich | – |
| **Hetzner Storage Box** | Hetzner-Konto | BX11 | SFTP/rsync-Unterkonto | nein | 💶 3,20 € netto | **optional**, R2 empfohlen |
| **GitHub** | vorhanden | Deploy-Key, Actions, Environments | Deploy-Key nur lesen | nein | 0 € (private Repos: begrenzte Actions-Minuten im Gratisplan ⚠️) | Repo und CI vorhanden |

**Welche Dienste kosten laufend?** Hetzner-Server (+ Backups, IPv4), Domain, R2 ab dem Freikontingent, KI-Anbieter nach Nutzung, X je Post, optional Storage Box und ein TikTok-Drittanbieter. Alle Entwicklerkonten bei Google, Meta, TikTok, Twitch und GitHub sind kostenlos.

---

## 4. Social-Media-Veröffentlichung

Details und Quellen: `docs/PLATFORM_PUBLISHING_REVIEW.md` (PR #17). Hier nur, was du dafür tun musst.

### 4.1 YouTube

- **Kontotyp:** normales Google-Konto; für mehrere Kanäle Brand-Kanäle. Kanal per Telefon bestätigen.
- **OAuth:** Client vom Typ „Webanwendung“, autorisierte Rückleitungs-URL mit `https://<domain>`, Zustimmungsbildschirm mit App-Name, Support-E-Mail und Link zur Datenschutzerklärung (Pflicht für „In production“). Kein Impressum nötig. Persönliche Nutzung (unter 100 Nutzer) braucht keine Google-Prüfung; beim Verbinden die Warnung „nicht verifizierte App“ bestätigen.
- **Sichtbarkeit:** Uploads aus nicht geprüften Projekten sind laut aktueller Doku **nicht** mehr auf privat beschränkt; ohne Angabe sind sie öffentlich. Der Code setzt die Sichtbarkeit immer ausdrücklich.
- **Beschränkungen:** 100 Uploads/Tag je Google-Projekt für **alle** Kanäle zusammen, 10.000 Einheiten/Tag für den Rest. Shorts bis 3 Minuten, Hochformat. KI-veränderte, realistisch wirkende Inhalte müssen gekennzeichnet werden.
- **Achtung Testmodus:** Refresh-Token verfällt nach 7 Tagen ⚠️; für 24/7 muss die App „In Produktion“ und ggf. verifiziert sein.

### 4.2 Twitch

- Nur **Datenquelle**, keine Upload-API. Vorhandene App reicht. Clips anderer Kanäle sind nicht automatisch nutzbar.

### 4.3 TikTok

- **Kontotyp:** ohne Audit müssen die Zielkonten beim Posten **privat** sein; höchstens 5 Konten in 24 h; Sichtbarkeit nur `SELF_ONLY`.
- **Private Nutzung:** Die TikTok-Prüfung verlangt eine öffentliche Website mit Datenschutz und Nutzungsbedingungen und lehnt private Apps ab. Ohne Prüfung: Sandbox mit bis zu 10 eigenen Konten, keine öffentlichen Videos. → halbautomatisch, keine App nötig.
- **Beschränkungen:** ca. 15 Posts/Tag je Creator-Konto; mit Audit Pflicht-Dialog je Post (Sichtbarkeit wählen, Musik-Zustimmung). Vollautomatisches öffentliches Posten ist für eigene Konten voraussichtlich nicht möglich → **Entscheidung A17**.

### 4.4 Instagram

- **Kontotyp:** Profikonto (Business oder Creator). Für den gebauten Weg mit Facebook-Seite verknüpft.
- **OAuth:** Meta-App „Business“, Facebook Login for Business mit Konfigurations-ID ⚠️, https-Rückleitung. Im Entwicklungsmodus nutzen nur Personen mit Rolle in der App die Berechtigungen; laut Meta sind dort erzeugte Daten „such as test posts“ nur für diese Personen sichtbar ⚠️. Für öffentliche Posts voraussichtlich Live-Modus mit Nutzungsbedingungen-URL.
- **Beschränkungen:** Posts sind sofort öffentlich; 50 bzw. 100 Posts je 24 h ⚠️ (der Code fragt das Limit vor jedem Post ab). Keine lizenzierte Instagram-Musik über die API.

### 4.5 Facebook

- **Kontotyp:** nur **Seiten**, keine Profile. Deine Rolle auf der Seite muss Inhalte erstellen dürfen.
- **Beschränkungen:** 30 Reels je Seite in 24 h, 3–90 s, 9:16, sofort öffentlich.

### 4.6 X / Twitter (neu geprüft am 15.11.2026)

- **Preismodell:** nur noch Abrechnung nach Nutzung mit **vorab gekauftem Guthaben** in der Developer Console; keine Abos für Neukunden. Die alten Stufen Free, Basic (200 $/Monat) und Pro (5.000 $/Monat) gibt es laut einer Zweitquelle nur noch für Bestandskunden ⚠️.
- **Kosten je Post** (offizielle Preisseite): „Post: Create“ 0,015 $, **mit Link 0,20 $**. Ein Preis für den Medien-Upload steht dort nicht ⚠️.
- **Beispiel:** 2 Posts/Tag ohne Link ≈ 60 Posts/Monat ≈ 0,90 $. Mit Link in jedem Post ≈ 12 $/Monat. Links im Post vermeiden.
- **Weiteres:** Lesen kostet 0,005 $ je Post (Kennzahlen abrufen kostet also auch). Ist das Guthaben verbraucht, werden Anfragen blockiert. Ausgabenlimit je Abrechnungszeitraum einstellbar.
- **Kontotyp:** normales X-Konto; Entwicklerkonto mit Projekt und App, OAuth 2.0 mit PKCE, https-Rückleitung.
- **Bewertung:** technisch machbar und günstig, aber nicht im Code (B24) und kostenpflichtig ab dem ersten Post. Empfehlung: erst nach YouTube, Instagram und Facebook angehen.

### 4.7 Für alle Plattformen

- Eigene, lizenzierte Inhalte; mehrere Konten mit identischen Inhalten werden als Spam gewertet (Varianten A–D sind vorhanden).
- KI-Stimme und KI-Texte kennzeichnen, wo die Plattform es verlangt (B26).
- Erste Veröffentlichung je Plattform nur privat bzw. nach ausdrücklicher Freigabe.

---

## 5. KI-Dienste

**Was heute läuft:** Texte aus regelbasierten Vorlagen, stille Test-Stimme, Untertitel aus dem Skripttext, Szenenanalyse mit FFmpeg (Bewegung, Lautstärke, Schnitte). Nichts davon braucht eine KI-API. Das System läuft damit bereits 24/7, nur ohne echte Stimme und mit einfachen Texten.

| Aufgabe | Wird tatsächlich gebraucht? | Empfehlung | Kosten |
|---|---|---|---|
| **Texterstellung** (Hooks, Skripte, Titel, Beschreibungen, DE/EN) | ja, für bessere Texte | ein Sprachmodell-Anbieter, kleines günstiges Modell für Varianten, Kostenzählung im Code vorhanden | 💶 nach Tokens; Monatslimit setzen |
| **Sprachausgabe (TTS)** | ja, sonst keine Stimme | Anbieter, der **kommerzielle Nutzung** erlaubt (Spec-Vorgabe). OpenAI verlangt, dass Hörer auf die KI-Stimme hingewiesen werden; die älteren OpenAI-TTS-Modelle sollen laut OpenAI am 06.01.2027 abgeschaltet werden ⚠️ → aktuelles Modell wählen | 💶 nach Zeichen/Minuten |
| **Transkription** | nur, wenn Originalton aus dem Gameplay ausgewertet werden soll | **lokal** mit faster-whisper auf dem Server (keine API-Kosten, langsamer) | 0 € |
| **Untertitel** | ja | schon gebaut (SRT, WebVTT, eingebrannt); bleiben aus dem Skript | 0 € |
| **Videoanalyse** | ja | FFmpeg-Analyse ist gebaut; ein Bildmodell (Vision) nur für spätere Funktionen wie Szenenbeschreibung | 💶 optional |
| **Gesichts-/Webcam-Erkennung** (Roadmap C4) | für fremdes Material ja | lokal mit OpenCV/MediaPipe | 0 € |

**Einzurichten, sobald entschieden (A19, A20):**

- `LLM_PROVIDER`, `LLM_API_KEY`, `TTS_PROVIDER`, `TTS_API_KEY` in `.env` auf dem Server (nur dort).
- `PAID_API_CALLS_ENABLED=true` erst nach Freigabe; `MONTHLY_BUDGET_EUR` und die Budgetstufen sind im Code vorhanden und stoppen kostenpflichtige Aufrufe bei Erreichen der Grenze.
- Beim Anbieter zusätzlich ein **hartes** Monatslimit für das Projekt (bei OpenAI „Enforce a hard limit“; ohne diese Option blockiert das Limit nicht).
- Konkrete Modellnamen und Preise am Tag der Einrichtung auf der Preisseite des Anbieters prüfen; sie ändern sich häufig.

---

## 6. Cloud-Infrastruktur

| Baustein | Was ist zu tun? | Stand |
|---|---|---|
| **Hetzner Cloud** | Konto (A7), Projekt, SSH-Key (A9), Server CX33 mit Ubuntu 24.04 in Deutschland (A8), Cloud Firewall (C1), Server-Backups (C2). CX33 hat 80 GB SSD: reicht für Betrieb und Zwischenablage, **nicht** für ein Videoarchiv → fertige Medien nach R2 (B14) | Skripte ✅, Server ⬜ |
| **Cloudflare R2** | Konto, Zahlungsart, Buckets `media` und `backups`, Tokens mit minimalen Rechten, Lebenszyklus-Regeln (C11) | Code ⬜ (B14, B15) |
| **Hetzner Storage Box** | nur nötig, wenn ein großes Archiv (ab ca. 250 GB) mit Festpreis gewünscht ist. Für die Datenbanksicherungen ist R2 empfohlen (anderer Anbieter als der Server) | optional |
| **Domain und DNS** | Domain (A6) mit Cloudflare-Nameservern (C3); Hostname für das Dashboard über den Tunnel | ⬜ |
| **Cloudflare Tunnel + Access** | privater Zugang ohne offene Web-Ports, Anmeldung nur für deine E-Mail-Adresse ([PRIVATE_ACCESS.md](PRIVATE_ACCESS.md)) | Code ✅, Einrichtung ⬜ (A29) |
| **SSL-Zertifikate** | Browser ↔ Cloudflare: Zertifikat von Cloudflare, automatisch. Cloudflare ↔ Server: verschlüsselter Tunnel. Kein Let’s Encrypt und keine offenen Ports 80/443 nötig (alter Weg mit Caddy bleibt möglich) | ✅ im Code |
| **Backup-Konzept** | 1. tägliche verschlüsselte DB-Sicherung mit Wiederherstellungstest (✅) · 2. Kopie nach R2, nicht löschbar vom Server aus (B15) · 3. Hetzner-Server-Backups für das ganze System (C2) · 4. Schlüssel `BACKUP_PASSPHRASE` und `CREDENTIALS_ENCRYPTION_KEY` im Passwortmanager · 5. Wiederherstellung einmal üben (C12) | teilweise |

---

## 7. Daten und Speicherung

| Daten | Ort | Begründung |
|---|---|---|
| PostgreSQL (Trends, Lizenzen, Skripte, Strategien, Kennzahlen, verschlüsselte Tokens), Redis (Warteschlangen) | Server (Docker-Volumes) | braucht schnellen Zugriff |
| `.env` mit allen Schlüsseln | nur Server (Rechte 600) + Passwortmanager | nie in Git, nie in R2 |
| Arbeitsdateien beim Rendern (`media/tmp`) | Server | werden nach jedem Auftrag gelöscht (✅); Reste nach Abstürzen räumt B16 auf |
| Hochgeladenes Rohmaterial (Gameplay) | Server, bis Analyse und Schnitt fertig; danach R2 | groß, wird später nur selten gebraucht |
| Fertige Clips, Untertitel, Lizenznachweise | R2-Bucket `media` | dauerhaft, außerhalb des Servers, kein Abruf-Datenverkehr |
| Verschlüsselte DB-Sicherungen | Server (14 Tage) + R2-Bucket `backups` (z. B. 30 Tage per Lebenszyklus) | Offsite, anderer Anbieter |
| Hetzner Storage Box | nur bei Entscheidung für ein großes Archiv | optional |

**Automatisches Löschen temporärer Dateien und Schutz vor vollem Speicher**

- ✅ Schon vorhanden: Render-, Stimm- und Untertitel-Arbeitsdateien werden nach jedem Auftrag gelöscht; abgelehnte Uploads sofort. Docker-Logs rotieren (10 MB × 5). Datenbanksicherungen älter als 14 Tage werden gelöscht. Warnung ab 80 % belegtem Speicher, kritisch ab 90 % (Seite „System“ und Uptime Kuma).
- ⬜ Fehlt (B16), Vorschlag:
  - Dateien in `media/tmp`, die älter als 6 Stunden sind, regelmäßig löschen (Reste nach Absturz).
  - Lokale Kopien von Clips löschen, sobald sie in R2 liegen und veröffentlicht sind.
  - Rohmaterial lokal nach 7 Tagen löschen, wenn es in R2 liegt.
  - Ab 85 % Speicher keine neuen Uploads und Render-Jobs annehmen; ab 90 % Not-Aus für die Produktion (Veröffentlichung läuft weiter).
  - Wöchentlich `docker image prune` und `docker builder prune` für alte Images (in `deploy.sh` ergänzen).
- R2-Lebenszyklus-Regeln begrenzen die Kosten (z. B. Rohmaterial nach 90 Tagen löschen, Sicherungen nach 30 Tagen).

---

## 8. Technische Projektvorbereitung

| Punkt | Stand | Was fehlt noch |
|---|---|---|
| Dockerfile | ✅ Backend und Dashboard | – |
| Docker Compose | ✅ alle Dienste, Profile `proxy`, `monitoring`, `workflow` (n8n) | n8n wird nicht gebraucht; Profil `workflow` auf dem Server nicht starten, außer es wird später genutzt |
| .env.example | ✅ vollständig, ohne Werte | X-Variablen kommen mit B24 |
| Datenbank | ✅ PostgreSQL 16 mit Alembic-Migrationen im Dienst `migrate` | – |
| Redis / Warteschlangen | ✅ mit Passwort, nur intern erreichbar | – |
| FFmpeg | ✅ im Backend-Image, ohne Shell, mit Zeitlimit | – |
| Logging | ✅ JSON, maskiert, rotiert | optional später zentrale Ablage |
| Monitoring | ✅ Systemprüfung, Uptime Kuma | Einrichtung auf dem Server (C10) |
| Fehlerbehandlung | ✅ Wiederholungen, Gates, Not-Aus, Benachrichtigungen | – |
| Automatische Neustarts | ✅ `restart: unless-stopped`, Healthchecks; Docker startet beim Booten | – |
| GitHub Actions für Deployment | ⬜ nur CI vorhanden, Deployment heute per `deploy.sh` von Hand | B13 + C9 |

---

## 9. Sicherheit

| Punkt | Stand | Was ist zu tun? |
|---|---|---|
| Sichere Speicherung von API-Schlüsseln | ✅ nur Umgebungsvariablen, OAuth-Tokens verschlüsselt, Schlüsselwechsel möglich | YouTube-Key und Twitch-Secret **erneuern** (A1, A2), weil sie mehrfach in `.env.example` eingecheckt waren. Nie wieder echte Werte in `.env.example` |
| SSH-Zugänge | ✅ `harden.sh`: nur Schlüssel, kein Passwort | Ed25519-Schlüssel mit Passphrase (A9); getrennter Schlüssel nur für Deployment (C9) |
| Firewall | ✅ ufw; mit `harden.sh --tunnel` nur noch 22 | zusätzlich Hetzner Cloud Firewall nur Port 22 (C1) |
| Benutzerrechte | ✅ Rollen im Dashboard; Dienste nur intern; ✅ Einzelbenutzer-Modus (`SINGLE_USER_MODE=true`) sperrt weitere Konten | auf dem Server eigener Benutzer statt root, Deploy-Benutzer nur mit Docker-Rechten (C4, C5) |
| GitHub Secrets | – | nur SSH-Zugang für das Deployment, in einem Environment mit Bestätigung. Anwendungsschlüssel bleiben auf dem Server. Branch-Schutz für `main` (CI muss grün sein). Secret Scanning/Push Protection einschalten, soweit für private Repos im Plan verfügbar ⚠️ |
| Schutz vor unbefugten Zugriffen | ✅ Cloudflare Access vor allem, Prüfung des Access-Tokens im Backend (`ACCESS_GUARD=cloudflare`), dazu Anmeldung, CSRF, Login-Sperre, kurze Sitzungen, Sicherheitsheader; keine öffentliche Registrierung | Access einrichten (A29), TOTP als weitere Schicht (B17); 2FA auf allen Anbieter-Konten (A4); Uptime Kuma und Datenbank nur per SSH-Tunnel |
| Backup und Wiederherstellung | ✅ verschlüsselt, getestet | Offsite-Kopie (B15), Wiederherstellung üben (C12), Schlüssel außerhalb des Servers aufbewahren |
| Notfall | ✅ Not-Aus im Dashboard und in `.env` | Notfallplan aufschreiben: wer schaltet ab, wie werden Plattform-Tokens widerrufen (in den Kontoeinstellungen jeder Plattform) |

---

## 10. Kosten im Überblick (Richtwerte 15.11.2026, ohne Gewähr)

| Posten | Monatlich | Bemerkung |
|---|---|---|
| Hetzner CX33 (4 vCPU, 8 GB, 80 GB) | 8,49 € netto + 0,50 € IPv4 ≈ **10,70 € brutto** | Preise seit 15.06.2026 erhöht. Auf der Hetzner-Seite war CX33 am 15.11. als „derzeit nicht verfügbar“ markiert ⚠️; Ausweichen auf anderen Standort oder CX43 (15,99 € netto + IPv4) |
| Hetzner Server-Backups | ≈ 1,70 € netto | 20 % des Serverpreises ⚠️ |
| Domain | ≈ 0,50–1,50 € | je nach Endung, jährlich bezahlt |
| Cloudflare R2 | 0 € bis ca. 3 € | 10 GB frei, danach 0,015 $/GB; kein Abrufentgelt |
| Hetzner Storage Box BX11 | (3,20 € netto) | nur falls statt R2 gewählt |
| KI-Texte und Stimme | nach Verbrauch | festes Limit setzen, z. B. 15–25 € |
| X/Twitter | ≈ 1 $ (ohne Links) | nur falls gewählt |
| **Summe ohne KI** | **ca. 12–17 €** | Budget ca. 50 €/Monat |

Kostenlos: Entwicklerkonten Google, Meta, Twitch, GitHub; Cloudflare Tunnel und Access (Gratistarif bis 50 Nutzer ⚠️); Uptime Kuma; lokale Transkription und Gesichtserkennung.

Die Kostenübersicht im Dashboard rechnet mit `SERVER_MONTHLY_EUR`, `OTHER_FIXED_MONTHLY_EUR` und `STORAGE_EUR_PER_GB_MONTH`. Diese Werte nach der Bestellung mit den echten Preisen füllen.

---

## 11. Rechtliche und organisatorische Voraussetzungen

Keine Rechtsberatung. Vor der Monetarisierung der Kanäle von einer fachkundigen Stelle prüfen lassen.

| Thema | Was ist zu tun? | Prio |
|---|---|---|
| **Impressum** | **Server/Dashboard: nicht nötig.** § 5 DDG gilt für „geschäftsmäßige, in der Regel gegen Entgelt angebotene digitale Dienste“; ein Dashboard nur für dich bietet niemandem etwas an. **Social-Media-Profile:** sobald monetarisiert oder geschäftlich, Impressum bzw. Link im Profil (§ 5 DDG, § 18 MStV ⚠️) | P3 |
| **Datenschutzerklärung** | Keine für Besucher nötig, weil es keine gibt. Aber Pflicht-URL für Google („In production“ und YouTube-Richtlinie III.A.2) und voraussichtlich Meta-Live-Modus. Twitch verlangt keine; TikTok entfällt (halbautomatisch). Inhalt kurz: wer, welche Plattformdaten, Hosting Hetzner/Cloudflare, Speicherdauer, Kontakt | P2 |
| **Datenschutz (DSGVO)** | Server in Deutschland; AVV mit Hetzner, Cloudflare und dem KI-Anbieter (A22). Personenbezogene Daten im System sind wenig (Dashboard-Nutzer, Plattform-Kennzahlen). Keine Gesichter Dritter in Videos (Roadmap C4) | P2 |
| **Urheberrechte am Gameplay** | Nur eigene Aufnahmen oder Material mit nachgewiesener Erlaubnis. Video-Richtlinien der Publisher je Spiel prüfen (viele erlauben Monetarisierung eigener Aufnahmen, einige nicht). Nachweis im Dashboard hinterlegen; die Rechteprüfung mit 12 Kriterien ist gebaut | P2 |
| **Fremde Streams und Clips** | Nicht automatisch nutzbar, auch wenn öffentlich. Nur mit schriftlicher Erlaubnis | P2 |
| **Musik und Bildmaterial** | Nur mit Lizenz für kommerzielle Nutzung auf allen Zielplattformen. Spielmusik im Gameplay ist oft gesondert geschützt (Content-ID-Ansprüche möglich) | P2 |
| **KI-Kennzeichnung** | Plattformregeln verlangen bei realistisch wirkenden KI-Inhalten eine Kennzeichnung; KI-Stimme laut OpenAI kenntlich machen. Die Transparenzpflichten der EU-KI-Verordnung (Art. 50) für KI-erzeugte Inhalte beachten ⚠️ | P2 |
| **Plattformrichtlinien** | Community-Richtlinien und Spam-Regeln jeder Plattform; YouTube-Regeln zu „wiederverwendeten Inhalten“ für die Monetarisierung; keine identischen Posts auf vielen Konten | P2 |
| **Werbung / Kooperationen** | Kennzeichnung bezahlter Inhalte (Plattformschalter + „Werbung“) | P3 |
| **Gewerbe und Steuern** | Sobald Einnahmen entstehen (YouTube-Partnerprogramm, Kooperationen): Gewerbeanmeldung, Steuerfragen (ggf. Kleinunternehmerregelung) | P3 |
| **Jugendschutz / Altersfreigabe** | Spiele mit USK 18 nur entsprechend gekennzeichnet bzw. mit Altersbeschränkung veröffentlichen ⚠️ | P2 |

---

## 12. Fehlende Voraussetzungen, an die man leicht nicht denkt

1. **Eine Datenschutz-URL trotz privater Nutzung.** Google verlangt sie für „In production“ (ohne die nach 7 Tagen getrennte YouTube-Verbindung), Meta voraussichtlich für den Live-Modus. Eine einzige statische Textseite reicht (A30, B29).
2. **Google-Refresh-Token im Testmodus nur 7 Tage gültig** ⚠️. Ohne Umstellung auf „In Produktion“ bricht der YouTube-Upload nach einer Woche ab.
3. **Speicherplatz:** 80 GB auf dem CX33 laufen bei Gameplay-Rohmaterial schnell voll. Ohne R2-Anbindung (B14) und Aufräumregeln (B16) steht die Produktion irgendwann still.
4. **Server-Verfügbarkeit:** CX33 war am 15.11. als nicht verfügbar markiert ⚠️. Alternative Standorte oder Modelle vorher festlegen.
5. **Deploy-Key für das private Repository**, sonst kann der Server den Code nicht holen (C6).
6. **Schlüssel für Sicherungen außerhalb des Servers aufbewahren.** Ohne `BACKUP_PASSPHRASE` sind alle Sicherungen wertlos; ohne `CREDENTIALS_ENCRYPTION_KEY` müssen alle Kanäle neu verbunden werden.
7. **Alarm muss jemanden erreichen.** Uptime Kuma braucht einen eingerichteten Kanal (A26), sonst merkt niemand einen Ausfall.
8. **Kanäle starten pausiert.** Ohne Entpausieren plant die Strategie nichts (C15).
9. **Tageslimit Produktionsaufträge:** Standard jetzt 50 (PR #18); eine Warnung bei Erreichen fehlt (B25).
10. **Telefonbestätigung der YouTube-Kanäle** und **Profikonto bei Instagram** vor dem Verbinden.
11. **Eigene Material-Pipeline:** Das System sucht kein Material im Netz. Für 24/7-Betrieb braucht es laufend neues lizenziertes Gameplay (eigene Aufnahmen oder Verträge). Das ist der eigentliche Engpass, nicht die Technik.
12. **E-Mail-Adresse für das Projekt** (Support-Adresse in den Apps, ACME, Alarme), getrennt von der privaten.
13. **Uhrzeit und Zeitzone:** `TZ=Europe/Berlin` in `.env`, damit Backup-Zeit und Planung stimmen.
14. **Hetzner-Abuse-Kontakt:** Hetzner meldet Beschwerden per E-Mail an den Kontoinhaber und erwartet zügige Antwort; die Kontakt-E-Mail muss gelesen werden.
15. **Uploads über 100 MB** scheitern hinter Cloudflare ohne Upload in Teilstücken (B28) ⚠️.
16. **Externe Überwachung** der öffentlichen Adresse wird von Access blockiert; Uptime Kuma prüft intern und per Push (C10).

---

## 13. Schritt-für-Schritt-Plan bis zum produktiven Start

Jeder Schritt mit 💶 wird erst nach deiner ausdrücklichen Freigabe ausgeführt.

### Schritt 1 – Aufräumen und absichern (diese Woche, 0 €)
1. YouTube-API-Key und Twitch-Secret erneuern, neue Werte nur in Passwortmanager und Cloud-Umgebung (A1–A3).
2. 2FA auf allen Konten, Passwortmanager einrichten (A4, A5).
3. PR #18 mergen (A28).
4. Entscheidungen treffen: Backup-Ziel (A11), TikTok-Weg (A17), KI-Anbieter (A19), X ja/nein (A18).

### Schritt 2 – Code für den Betrieb fertigstellen (Agent, 0 €)
5. R2-Speicher, Offsite-Backup, Aufräumregeln (B14–B16).
6. Zugangsschutz für private Nutzung (B18, ✅ vorbereitet), Upload in Teilstücken (B28), TOTP (B17).
7. Deploy-Workflow für GitHub Actions (B13), Doku (B27).
8. Abnahmetest und CI grün halten.

### Schritt 3 – Konten und Rechtliches (du, überwiegend 0 €)
9. Kurze Datenschutzerklärung und Nutzungsbedingungen für Google/Meta (A21, A30), Projekt-E-Mail anlegen.
10. Domain registrieren 💶 (A6).
11. Hetzner-Konto mit Identitätsprüfung (A7), Cloudflare-Konto (A10, noch ohne R2-Aktivierung).
12. Rechte für das erste Gameplay klären und erfassen (A23), Musikquelle festlegen (A24).

### Schritt 4 – Server einrichten (💶 nach Freigabe)
13. Server bestellen, Firewall, Backups (A8, C1, C2).
14. Domain zu Cloudflare (C3), Zero Trust, Tunnel und Access-Anwendung gemeinsam einrichten (A29), Härtung mit `--tunnel` (C4), Docker (C5), Deploy-Key (C6).
15. `.env` füllen (C7), `deploy.sh`, Admin anlegen (C8). Zugang prüfen (C17): nur nach Cloudflare-Anmeldung, von PC und Handy, Server-IP direkt nicht erreichbar.
16. R2 aktivieren und Buckets anlegen 💶 (C11). Uptime Kuma mit Alarmkanal (C10).
17. Sicherung und Rücksicherung testen (C12).
18. GitHub-Environment und Secrets für das automatische Deployment (C9), einmal testweise deployen.

### Schritt 5 – Echte Daten, noch ohne Veröffentlichung (0 €)
19. Trendquellen live schalten, Twitch-Helix prüfen (C13).
20. Einige Tage im Mock-Publishing laufen lassen: Speicher, Warteschlangen, Fehlerquote auf der Seite „System“ beobachten.
21. KI-Anbieter mit hartem Limit einrichten und `PAID_API_CALLS_ENABLED=true` 💶 (A20), Texte und Stimme prüfen.

### Schritt 6 – Plattformen anbinden (0 €, X 💶)
22. Google-OAuth-Client und Meta-App anlegen, Rückleitungs-URLs mit der Domain (A12, A14, C14). TikTok halbautomatisch (A17).
23. Je Plattform einen Testkanal verbinden und entpausieren (C15).
24. Je Plattform **ein** privater Testpost nach einzelner Freigabe (C16). Bei Instagram und Facebook gibt es kein privat: dafür eine Testseite bzw. ein Testkonto nutzen.

### Schritt 7 – Schrittweise live
25. `PUBLISHING_MODE=live`, Freigabemodus „mit Freigabe“: jeder Post wird im Dashboard bestätigt.
26. Nach zwei Wochen ohne Probleme `AUTO_PUBLISH_ENABLED=true` nur für ausdrücklich freigegebene Kanäle.
27. Ab 8 echten Videos an 3 Tagen lernt der Learning Agent; die Veröffentlichungsmenge bestimmt weiter der Publishing Strategy Agent je Kanal.
28. Monatlich: Kosten im Dashboard mit den Rechnungen abgleichen, Rücksicherung testen, Updates per Deploy einspielen.

---

## 14. Quellen (gelesen am 15.11.2026)

- Plattformen, R2 und Storage Box: Quellenliste in `docs/PLATFORM_PUBLISHING_REVIEW.md` (PR #17)
- X API: [Preisseite](https://docs.x.com/x-api/getting-started/pricing); Zweitquelle zu den alten Stufen: [Postproxy, X API Pricing 2026](https://postproxy.dev/blog/x-api-pricing-2026/)
- Hetzner: [Preisanpassung 2026](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [Cost-Optimized Cloud](https://www.hetzner.com/cloud/cost-optimized), [Storage Box](https://www.hetzner.com/storage/storage-box/)
- OpenAI: [Preise](https://developers.openai.com/api/docs/pricing), [Ausgabenlimits](https://developers.openai.com/api/docs/guides/spend-limits), [Text-to-Speech](https://developers.openai.com/api/docs/guides/text-to-speech)
