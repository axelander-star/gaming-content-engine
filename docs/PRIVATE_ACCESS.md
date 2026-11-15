# Private Nutzung: Zugang nur für den Betreiber

**Stand:** 15.11.2026 · **Entscheidung des Betreibers vom 15.11.2026:** Die Gaming Content Engine ist ausschließlich für die persönliche Nutzung bestimmt. Sie wird kein öffentliches Produkt und keine Plattform für andere Nutzer.

Dieses Dokument ist der Umsetzungsvorschlag. Der Code dafür ist vorbereitet und getestet, aber **nichts ist eingerichtet oder deployt**. Die Einrichtung auf Server und Cloudflare folgt erst nach Prüfung durch den Betreiber.

Angaben mit ⚠️ standen nicht auf den gelesenen Anbieterseiten oder sind dort nicht eindeutig. Sie müssen bei der Einrichtung im jeweiligen Portal bestätigt werden.

## 1. Anforderungen und Umsetzung

| # | Anforderung | Umsetzung | Stand |
|---|---|---|---|
| 1 | Anwendung nur für den Betreiber erreichbar | Cloudflare Access vor der ganzen Domain; Server ohne offene Web-Ports (Cloudflare Tunnel) | vorbereitet |
| 2 | Sicherer Zugang über Cloudflare Access | Access-Anwendung mit Regel „nur meine E-Mail-Adresse“, Anmeldung per Einmal-Code oder Google/GitHub-Konto. Das Backend prüft das Access-Token zusätzlich selbst (`ACCESS_GUARD=cloudflare`) | Code ✅, Einrichtung offen |
| 3 | Keine öffentliche Registrierung, keine weiteren Konten | Eine Registrierung gab es nie: Konten legt nur ein Admin an. Neu: `SINGLE_USER_MODE=true` sperrt das Anlegen weiterer Konten im Dashboard **und** per Kommandozeile | Code ✅ |
| 4 | HTTPS für alle Verbindungen | Browser ↔ Cloudflare: HTTPS mit Zertifikat von Cloudflare. Cloudflare ↔ Server: verschlüsselter Tunnel, vom Server aus aufgebaut. Intern im Docker-Netz: unverschlüsselt, aber nicht von außen erreichbar | vorbereitet |
| 5 | Dashboard und API nicht ohne Authentifizierung | Zwei Schichten: Cloudflare Access (vor allem) und die bestehende Anmeldung im Dashboard (Passwort, Sitzung, CSRF, Login-Sperre). Ausnahme nur `/api/health` für Container-Healthchecks, und das nur intern | Code ✅ |
| 6 | API-Schlüssel und OAuth-Secrets nur serverseitig | War schon so: Schlüssel nur in `.env` auf dem Server, Plattform-Tokens verschlüsselt in der Datenbank. Neu geprüft: das Dashboard enthält keine Umgebungsvariablen mit Geheimnissen (keine `NEXT_PUBLIC_*`), es spricht nur mit der eigenen API | ✅ geprüft |
| 7 | Keine Secrets im Repository oder Frontend | `.env` ist ausgeschlossen, CI prüft auf eingecheckte Schlüssel. Neue Werte (`CLOUDFLARE_TUNNEL_TOKEN`) stehen in `.env.example` nur leer | ✅ |
| 8 | Datenschutz-URLs der Plattformen bei privater Nutzung | Abschnitt 4 | geprüft |
| 9 | Impressum bei privatem Betrieb | Abschnitt 5 | geprüft |

## 2. Empfohlene Architektur: Cloudflare Tunnel + Cloudflare Access

```
 Du (PC, Handy)                  Cloudflare                         Hetzner-Server
 ─────────────                   ──────────                         ──────────────
 Browser ──HTTPS──▶  gce.deine-domain.de                           Firewall: eingehend nur SSH
                     │ 1. Access: Anmeldung (E-Mail-Code)          (keine Web-Ports offen)
                     │    nur deine Adresse erlaubt
                     │ 2. signiertes Token (JWT) anhängen
                     ▼                                              cloudflared ──baut Verbindung
                     Tunnel ◀═════════ verschlüsselt ═══════════════  nach außen auf
                                                                     │
                                                                     ▼ http://caddy:8080
                                                                   Caddy (Sicherheitsheader)
                                                                     ├─ /api/* → Backend
                                                                     │   prüft Access-Token
                                                                     │   + eigene Anmeldung
                                                                     └─ Rest   → Dashboard
```

**Warum Tunnel statt offener Ports mit Caddy-Zertifikat?**

1. **Keine offene Angriffsfläche:** Der Server nimmt aus dem Internet nur SSH an. Wer die Server-IP kennt, erreicht das Dashboard trotzdem nicht. Bei offenen Ports 80/443 könnte man Cloudflare Access umgehen, wenn man die IP kennt.
2. **Keine Zertifikatsverwaltung auf dem Server:** HTTPS übernimmt Cloudflare.
3. **Zugriff von überall:** PC, Handy, Tablet, ohne VPN-App. Anmeldung im Browser mit einem Code per E-Mail.
4. **Kosten:** Tunnel und Access sind im kostenlosen Zero-Trust-Tarif enthalten (bis 50 Nutzer ⚠️). Cloudflare verlangt beim Aktivieren von Zero Trust möglicherweise eine Zahlungsart, auch für den Gratistarif ⚠️.

**Voraussetzung:** Die Domain muss ihre DNS-Verwaltung bei Cloudflare haben (Nameserver auf Cloudflare umstellen) ⚠️. Das kostet nichts. Wer die Domain noch nicht hat, kann sie direkt bei Cloudflare registrieren.

**Verworfene Alternativen**

| Alternative | Warum nicht |
|---|---|
| Offene Ports 80/443 + Caddy + Cloudflare Access (Proxy) | Ohne zusätzliche Sperre auf Cloudflare-IPs ist der Server über die IP direkt erreichbar. Mehr Aufwand, mehr Angriffsfläche |
| Nur VPN (WireGuard/Tailscale) | Sehr sicher, aber auf jedem Gerät ist eine App nötig. Gute Ergänzung für SSH, aber für das Dashboard unbequemer |
| Nur die bestehende Anmeldung des Dashboards | Die Anwendung wäre öffentlich erreichbar; jede Schwachstelle im Login wäre aus dem Internet angreifbar |

## 3. Was im Code geändert wurde

| Datei | Änderung |
|---|---|
| `backend/core/access_guard.py` (neu) | Prüft das Cloudflare-Access-Token (`Cf-Access-Jwt-Assertion` bzw. Cookie `CF_Authorization`): Signatur RS256 gegen die öffentlichen Schlüssel der Team-Domain (`https://<team>/cdn-cgi/access/certs`), Zielgruppe (AUD), Aussteller, Ablaufzeit, optional E-Mail-Liste |
| `backend/app/main.py` | Bei `ACCESS_GUARD=cloudflare` lehnt die API jede Anfrage ohne gültiges Token mit 403 ab, auch Login und OAuth-Rückleitungen. Ausnahme: `/api/health` (Healthchecks im Docker-Netz) |
| `backend/core/config.py` | Neue Einstellungen `SINGLE_USER_MODE`, `ACCESS_GUARD`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`, `CF_ACCESS_ALLOWED_EMAILS`; Start verweigert, wenn `ACCESS_GUARD=cloudflare` ohne Team-Domain oder AUD gesetzt ist |
| `backend/api/users.py`, `backend/app/create_admin.py` | Einzelbenutzer-Modus: kein weiteres Konto über Dashboard oder Kommandozeile; Passwort des bestehenden Kontos zurücksetzen geht weiter |
| `backend/tests/integration/test_private_access.py` (neu) | 13 Tests: ohne Token, falsche Signatur, falsche Zielgruppe, falscher Aussteller, abgelaufen, fremde E-Mail, kaputtes Token, gültiges Token, Cookie, Healthcheck, Konfigurationsprüfung, Einzelbenutzer im Dashboard und per CLI |
| `infrastructure/caddy/Caddyfile` | Routen und Sicherheitsheader als gemeinsamer Block; zusätzlicher interner Eingang `http://:8080` nur für den Tunnel |
| `docker-compose.yml` | Neuer Dienst `cloudflared` (Profil `tunnel`, Version fest 2026.10.5); Caddy-Ports über `CADDY_BIND` an `127.0.0.1` bindbar |
| `infrastructure/server/harden.sh` | Option `--tunnel`: Firewall öffnet nur SSH, nicht 80/443 |
| `scripts/deploy.sh` | startet den Tunnel, wenn `CLOUDFLARE_TUNNEL_TOKEN` gesetzt ist; warnt, wenn der Zugangsschutz fehlt, Ports offen wären oder der Einzelbenutzer-Modus aus ist |
| `.env.example` | neue Variablen, alle leer bzw. auf dem bisherigen Verhalten |

**Bestehende Funktionen bleiben unverändert:** Alle neuen Schalter stehen standardmäßig auf dem bisherigen Verhalten (`ACCESS_GUARD=none`, `SINGLE_USER_MODE=false`, `CADDY_BIND=0.0.0.0`). Ohne Tunnel funktioniert der bisherige Weg mit Caddy und Let’s Encrypt weiter.

**Auswirkungen im Betrieb**

- **OAuth-Rückleitungen** (YouTube, TikTok, Meta) laufen über deinen Browser, der bei Access angemeldet ist. Sie funktionieren deshalb hinter Access ohne Ausnahme-Regel.
- **Uptime Kuma** prüft das Backend intern (`http://backend:8000/api/health/ready`) und bekommt Push-Meldungen; das bleibt. Der externe Monitor auf `https://<domain>/healthz` wird von Access blockiert. Entweder weglassen oder mit einem Access-Service-Token versehen ⚠️.
- **Große Uploads:** Cloudflare begrenzt im kostenlosen Tarif den Umfang einer Anfrage auf 100 MB ⚠️. Gameplay-Dateien bis 4 GB können deshalb **nicht** in einem Stück über das Dashboard hochgeladen werden. **Umgesetzt:** Das Dashboard lädt in Teilstücken von 16 MiB hoch und setzt nach einem Verbindungsabbruch an der letzten Stelle fort (0 €, Details: [UPLOADS.md](UPLOADS.md)).

## 4. Datenschutz-URLs bei rein privater Nutzung (geprüft am 15.11.2026)

| Plattform | Verlangt eine Datenschutz-URL? | Was heißt das für dich? |
|---|---|---|
| **Google / YouTube** | **Zustimmungsbildschirm im Status „Testing“:** Links nicht verpflichtend. Aber: Refresh-Tokens verfallen nach **7 Tagen** („is issued a refresh token expiring in 7 days“), weil `youtube.upload` kein Basis-Scope ist. **Status „In production“:** Datenschutz- und Startseiten-Link „are required for all external production apps“. Prüfung durch Google ist bei persönlicher Nutzung **nicht** nötig („Personal Use apps … fewer than 100 users … without going through verification“), man klickt nur die Warnung „nicht verifizierte App“ weg. Zusätzlich verlangen die YouTube-Entwicklerrichtlinien (III.A.2) von jedem API-Client eine Datenschutzerklärung, ohne Ausnahme für Einzelnutzer | Für 24/7-Betrieb ist „In production“ nötig, sonst muss YouTube jede Woche neu verbunden werden. Dafür braucht es **eine** öffentlich abrufbare Datenschutzerklärung (siehe Empfehlung unten) |
| **YouTube Uploads** | – | Neu: Die aktuelle `videos.insert`-Seite sagt ausdrücklich „Videos uploaded from unverified API projects are not restricted to private viewing mode“. Ohne Angabe ist ein Upload **öffentlich**. Der Code setzt die Sichtbarkeit immer ausdrücklich (`YOUTUBE_UPLOAD_PRIVACY=private`) |
| **Twitch** | **Nein.** Anmeldung der App braucht nur Name, Rückleitungs-URL, Kategorie und 2FA am Konto | nichts zu tun |
| **TikTok** | Für die Produktivprüfung ja: öffentliche Website mit sichtbarer Datenschutzerklärung und Nutzungsbedingungen. **Aber:** „Apps must not be for private or personal use.“ Eine private App besteht die Prüfung also grundsätzlich nicht. Ohne Prüfung bleibt nur der Sandbox-Modus: bis zu 10 eigene Konten, keine öffentlichen Videos | Für TikTok **keine** App und **keine** Datenschutzseite. Empfehlung: halbautomatisch (Option B aus der Plattform-Recherche): System erstellt Video und Text, du lädst in der TikTok-App hoch |
| **Meta (Instagram, Facebook)** | Laut Einstellungsseite ist für den Live-Modus u. a. eine **Nutzungsbedingungen-URL** Pflicht; die Datenschutz-URL ist dort nicht als Pflicht markiert ⚠️. Im Entwicklungsmodus dürfen nur Personen mit Rolle in der App die Berechtigungen nutzen. **Wichtig:** „Any data generated while an app is in Development mode, such as test posts, can only be seen by role users.“ ⚠️ | Für echte, öffentlich sichtbare Posts ist voraussichtlich der Live-Modus nötig, also eine öffentliche Seite mit Nutzungsbedingungen (und sinnvollerweise Datenschutz). Vor der Einrichtung im Meta-Dashboard bestätigen |

**Empfehlung für die nötigen Rechtstexte ohne öffentliche Website:**

Google (und voraussichtlich Meta) brauchen je eine erreichbare Adresse für Datenschutzerklärung bzw. Nutzungsbedingungen. Dafür reicht **eine einzelne statische Textseite**, keine Website mit Besuchern:

- **Variante 1 (umgesetzt, Entscheidung vom 15.11.):** Eine einzige statische Seite auf einem **eigenen Hostnamen**, z. B. `https://rechtliches.<domain>`, mit Datenschutzerklärung, Nutzungsbedingungen und englischer Kurzfassung. Caddy liefert sie über einen eigenen Eingang (`:8081`) aus, der **keine Route zur Anwendung** hat: Nur `GET`/`HEAD` auf `/`, `/datenschutz`, `/nutzungsbedingungen`, `/privacy` und `/terms` antworten, alles andere (auch `/api`, `/login`) ergibt `404`. Kein Link zum Dashboard, keine Cookies, keine fremden Inhalte, strenge Content-Security-Policy, `noindex`. Name, Kontakt-E-Mail und Stand kommen aus der `.env` des Servers (`LEGAL_OPERATOR_NAME`, `LEGAL_CONTACT_EMAIL`, `LEGAL_UPDATED`) und stehen nicht im Repository. Text: `infrastructure/legal/index.html`.
- Warum ein eigener Hostname statt eines freigegebenen Pfads: Der Hostname des Dashboards bleibt vollständig hinter Access, ohne Ausnahmeregel. Der Rechtstext-Hostname bekommt **keine** Access-Anwendung, zeigt im Tunnel aber nur auf `caddy:8081` und erreicht die Anwendung damit gar nicht.
- **Variante 2** (Text extern, z. B. GitHub Pages) bleibt möglich, Google verlangt für die Links aber in der Regel eine autorisierte, eigene Domain ⚠️.

Vor der Nutzung: Texte einmal lesen und bei Bedarf rechtlich prüfen lassen (keine Rechtsberatung).

## 5. Impressum

- **Für den Server:** Die Impressumspflicht nach § 5 DDG gilt für „geschäftsmäßige, in der Regel gegen Entgelt angebotene digitale Dienste“. Ein Dashboard, das nur du selbst nach Anmeldung erreichst, bietet niemandem einen Dienst an. Ein Impressum dafür ist nach dem Gesetzeswortlaut **nicht nötig**. Auch die Textseite aus Abschnitt 4 ist kein Angebot an Besucher; ein kurzer Anbieterhinweis (Name, Kontakt-E-Mail) darauf schadet trotzdem nicht.
- **Für die Social-Media-Kanäle:** Werden die Kanäle mit Werbung, Partnerprogrammen oder Kooperationen betrieben, gelten sie in der Regel als geschäftsmäßig. Dann braucht jedes Profil ein Impressum bzw. einen Link darauf (§ 5 DDG, § 18 Medienstaatsvertrag). Das hängt nicht am Server, sondern an den Kanälen. Der Text des § 18 MStV konnte nicht abgerufen werden ⚠️.
- Keine Rechtsberatung. Vor der Monetarisierung prüfen lassen.

## 6. Einrichtung (erst nach Prüfung durch den Betreiber)

Kurzfassung; Schritt für Schritt erklärt, wenn wir es gemeinsam einrichten.

1. Domain bei Cloudflare (Nameserver umstellen oder dort registrieren).
2. Zero Trust aktivieren (Gratistarif), Team-Domain festlegen, Anmeldung per Einmal-Code (E-Mail) einschalten.
3. Tunnel anlegen („cloudflared“, Docker). Token nur in `.env` auf dem Server als `CLOUDFLARE_TUNNEL_TOKEN`.
4. Im Tunnel einen öffentlichen Hostnamen `gce.<domain>` auf `http://caddy:8080` zeigen lassen und einen zweiten, `rechtliches.<domain>`, auf `http://caddy:8081` (nur die Rechtstext-Seite).
5. Access-Anwendung „Self-hosted“ für `gce.<domain>` anlegen, Regel „Allow“ nur für deine E-Mail-Adresse, Sitzungsdauer z. B. 24 h. AUD-Tag kopieren.
6. `.env` auf dem Server: `ACCESS_GUARD=cloudflare`, `CF_ACCESS_TEAM_DOMAIN=<team>.cloudflareaccess.com`, `CF_ACCESS_AUD=<AUD>`, `CF_ACCESS_ALLOWED_EMAILS=<deine Adresse>`, `SINGLE_USER_MODE=true`, `CADDY_BIND=127.0.0.1`, `DOMAIN=localhost`, `LEGAL_OPERATOR_NAME`, `LEGAL_CONTACT_EMAIL`, `LEGAL_UPDATED`.
7. Server: `harden.sh --tunnel`; Hetzner Cloud Firewall eingehend nur Port 22, am besten nur von deiner IP.
8. `./scripts/deploy.sh`, ersten Admin anlegen.
9. Prüfen: Aufruf ohne Anmeldung zeigt die Cloudflare-Anmeldeseite; `curl http://<server-ip>` erreicht nichts; nach Neustart des Servers läuft alles wieder (`restart: unless-stopped`).
10. Rückleitungs-URLs der Plattformen auf `https://gce.<domain>/api/oauth/<plattform>/callback`; Datenschutz-URL `https://rechtliches.<domain>/datenschutz`, Nutzungsbedingungen `https://rechtliches.<domain>/nutzungsbedingungen`.
11. Prüfen: `https://rechtliches.<domain>/api/health` und `/login` antworten `404`.

## 7. Offene Punkte

| Punkt | Wer | Prio |
|---|---|---|
| ~~Upload in Teilstücken~~ ✅ umgesetzt ([UPLOADS.md](UPLOADS.md)) | – | – |
| ~~Rechtstext-Seite~~ ✅ Variante 1 umgesetzt; Texte vor Nutzung lesen und Werte in `.env` setzen | Betreiber | vor YouTube „In production“ |
| Meta: Live-Modus und Sichtbarkeit von Posts im Entwicklungsmodus im Dashboard bestätigen | Betreiber mit Agent | vor Instagram/Facebook |
| Externe Überwachung hinter Access (Service-Token oder nur Push-Monitor) | bei Einrichtung | P2 |
| TOTP für den Admin bleibt sinnvoll (zweite Schicht hinter Access) | Coding-Agent | P2 |
