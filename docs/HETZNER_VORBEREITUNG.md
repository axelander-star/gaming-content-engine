# Vorbereitung Hetzner (Erweiterung E10)

**Stand:** 15.11.2026 · **Wichtig:** Mit dieser Phase wird **nichts bestellt und nichts deployt**. Sie liefert nur Unterlagen und Skripte, damit der Start später in einem Zug klappt.

Ergänzt [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) (was zu tun ist, mit Nummern A…, B…, C…) und [OPERATIONS.md](OPERATIONS.md) (wie der Betrieb läuft). Neu in E10:

| Datei | Zweck |
|---|---|
| `infrastructure/server/preflight.sh` | Prüft einen frisch bestellten Server **ohne etwas zu ändern**: Ubuntu, CPU, RAM, freier Speicher, Swap, Docker, Uhrzeit, offene Ports, `.env` (Pflichtwerte, Rechte 600, sichere Standardwerte, privater Zugang) |
| `python -m app.housekeeping report` | Zeigt, was wo wie viel Platz braucht, und rechnet den Bedarf für ein Jahr hoch |
| `python -m app.housekeeping cleanup` | Findet alte Arbeitsdateien und Dateien, auf die nichts mehr verweist; löscht nur mit `--apply` |
| `scripts/deploy.sh` | räumt nach jedem erfolgreichen Update alte Docker-Bauschichten weg |

---

## 1. Speicherbedarf

### 1.1 Was auf dem Server Platz braucht

| Posten | Größe | Wächst mit |
|---|---|---|
| Ubuntu, Docker, Images (Backend mit FFmpeg, Frontend, PostgreSQL, Redis, Caddy, cloudflared, Uptime Kuma) | ca. 8–12 GB | Updates (alte Schichten räumt `deploy.sh` jetzt weg) |
| PostgreSQL | unter 1 GB im ersten Jahr | Kennzahlen, Protokolle, Chat; Text ist klein |
| Datenbanksicherungen | 14 Tage × Datenbankgröße (verschlüsselt, komprimiert), also wenige GB | Datenbankgröße |
| Docker-Logs | höchstens 50 MB je Dienst (10 MB × 5, rotiert) | – |
| **Mediathek und Videos** (`media_data`) | siehe 1.2 | **der eigentliche Treiber** |

### 1.2 Videos: Richtwerte je Minute

| Art | Richtwert | Herkunft |
|---|---|---|
| Eigenproduktion (Text, Bilder, Untertitel, 1080×1920, CRF 20) | 0,3 MB/min mit Farbflächen, ca. 1–5 MB/min mit Fotos und Stimme | gemessen mit Farbfläche und Text (60 s = 0,33 MB); mit Fotos geschätzt |
| Eigene Handyaufnahme 1080p, 30 fps (Original) | ca. 100–150 MB/min | übliche Datenraten von Smartphones, ⚠️ je Gerät verschieden |
| Eigene Handyaufnahme 4K | ca. 300–400 MB/min | wie oben ⚠️ |
| 9:16-Fassung eines Querformat-Videos (1080×1920, CRF 20) | ca. 30–100 MB/min | je nach Bewegung im Bild; schnelle Spielszenen liegen oben |
| Gameplay-Aufnahme 1080p60 (Gaming-Pipeline) | ca. 100–200 MB/min | ⚠️ je nach Aufnahmeprogramm |

Sobald echte Dateien da sind, ersetzt `python -m app.housekeeping report` diese Richtwerte durch den gemessenen Durchschnitt („im Schnitt … MB je Minute“).

### 1.3 Hochrechnung für ein Jahr

Annahme: zwei Themenbereiche, je Woche zusammen 14 kurze Videos (1 Minute).

| Szenario | je Monat | je Jahr | passt auf CX33 (80 GB)? |
|---|---|---|---|
| **A. Nur Eigenproduktion** (keine eigenen Aufnahmen) | ca. 0,3 GB | ca. 3–4 GB | ja, viele Jahre |
| **B. Eigenproduktion + 30 min eigene 1080p-Aufnahmen je Woche** | ca. 17 GB Originale + bis 13 GB 9:16 | ca. 200–350 GB | **nein**, nach ca. 2 Monaten voll |
| **C. wie B, Originale nach 30 Tagen gelöscht oder ausgelagert** | – | Bestand bleibt bei ca. 20–30 GB | ja, mit Aufräumregel |

**Ergebnis:** Für die Eigenproduktion reicht der CX33 lange. Eigene Videoaufnahmen sind der einzige Posten, der den Server schnell füllt. Dafür braucht es vor dem ersten großen Upload eine Entscheidung (Abschnitt 4).

Für den Server heißt das: nach Ubuntu, Docker und Datenbank bleiben auf dem CX33 etwa **55–60 GB** für Medien. `preflight.sh` verlangt deshalb mindestens 40 GB frei vor dem ersten Start. Das System warnt ab 80 % belegtem Speicher und meldet ab 90 % „kritisch“ (Seite „System“ und Uptime Kuma).

---

## 2. Was schon automatisch aufgeräumt wird

| Was | Wann | Wo im Code |
|---|---|---|
| Arbeitsdateien beim Rendern, Stimme, Untertitel | sofort nach jedem Auftrag | Agenten (`work_dir`) |
| abgebrochene Uploads und ihre Teilstücke | nach Ablauf der Upload-Sitzung | `uploads.purge_expired` (Zeitsteuerung) |
| abgelehnte Uploads | sofort | `services/uploads.py` |
| Datenbanksicherungen | älter als 14 Tage (mindestens 3 bleiben) | `app.backup` |
| Docker-Logs | 10 MB × 5 je Dienst | `docker-compose.yml` |
| alte Docker-Bauschichten | nach jedem erfolgreichen Update | `scripts/deploy.sh` (neu in E10) |

## 3. Aufräumregeln (neu in E10)

`python -m app.housekeeping cleanup` arbeitet nach zwei Regeln:

1. **Arbeitsdateien** in `media/tmp`, die älter als **6 Stunden** sind. Das sind Reste von Render-Aufträgen, die abgestürzt sind. Den Ordner `tmp/uploads` lässt das Skript in Ruhe; den räumt die Upload-Verwaltung selbst auf.
2. **Verwaiste Dateien:** gespeicherte Dateien, auf die **keine einzige Zeile in der Datenbank** mehr verweist, und die älter als **7 Tage** sind. Das Skript liest dafür alle Tabellen, auch JSON-Felder wie den Herkunftsnachweis. Eine Datei, die irgendwo erwähnt wird, bleibt.

**Schutz:**

- Ohne `--apply` wird nichts gelöscht. Das Skript listet dann nur, was es löschen würde.
- Wenn die Datenbank auf gar keine Datei verweist, aber Dateien da sind, fasst das Skript keine verwaiste Datei an. Das schützt vor einer falsch angeschlossenen Datenbank.
- Archivierte Mediathek-Dateien gelten als „verwendet“ und bleiben, damit „Zurückholen“ weiter funktioniert. `report` zeigt, wie viel Platz sie belegen.

**Auf dem Server (Vorschlag, C18):**

```bash
# erst ein paar Tage nur ansehen
docker compose exec -T backend python -m app.housekeeping cleanup
docker compose exec -T backend python -m app.housekeeping report

# danach täglich um 4:30 Uhr (crontab -e des Benutzers deploy)
30 4 * * * cd /opt/gce && docker compose exec -T backend python -m app.housekeeping cleanup --apply >> /var/log/gce-housekeeping.log 2>&1
```

Die Fristen lassen sich anpassen: `--tmp-hours 12`, `--orphan-days 30`.

**Bewusst nicht automatisch** (braucht deine Entscheidung, Abschnitt 4): Originale von eigenen Aufnahmen nach einer Frist löschen oder auslagern, archivierte Dateien endgültig löschen, Annahmestopp für neue Uploads ab einer Füllgrenze.

---

## 4. Entscheidungen vor dem Start

| # | Frage | Möglichkeiten | Empfehlung |
|---|---|---|---|
| S1 | Wohin mit großen Originalen eigener Aufnahmen? | a) auf dem Server lassen und nach Frist löschen · b) nach Cloudflare R2 auslagern (10 GB frei, danach 0,015 $/GB und Monat, kein Abrufentgelt) · c) Hetzner Volume dazubuchen (Preis je GB am Bestelltag prüfen ⚠️) | Start mit a), Originale **30 Tage** nach der letzten Verwendung löschen; wenn du Originale behalten willst, b). Die Auslagerung nach R2 (B14) ist noch nicht gebaut. |
| S2 | Annahmestopp bei vollem Speicher | ab 85 % keine neuen Uploads und Render-Aufträge, Veröffentlichung läuft weiter | einbauen, bevor eigene Aufnahmen hochgeladen werden (B16, Restpunkt) |
| S3 | Server-Größe | CX33 (4 vCPU, 8 GB, 80 GB), Ausweichen auf CX43, falls CX33 nicht verfügbar ⚠️ | CX33 reicht für Szenario A und C |

---

## 5. Checkliste je Plattform-App

Für alle gilt:

- Schlüssel und Geheimnisse **nur** in `.env` auf dem Server (Rechte 600) und im Passwortmanager, nie im Repository, nie im Dashboard.
- Rückleitungs-URL immer `https://<domain>/api/oauth/<plattform>/callback`. Der Wert in `.env` muss genau gleich sein.
- Verbinden im Dashboard: **Einstellungen → Kanäle → „Mit … verbinden“** (nur Admin).
- Bis zu deiner ausdrücklichen Freigabe bleiben `PUBLISHING_MODE=mock` und `AUTO_PUBLISH_ENABLED=false`.

### YouTube (Upload und Kennzahlen)

- [ ] Google-Cloud-Projekt; „YouTube Data API v3“ und „YouTube Analytics API“ aktivieren
- [ ] Zustimmungsbildschirm (Google Auth Platform): Typ „Extern“, eigenes Konto als Nutzer, Datenschutz-URL `https://rechtliches.<domain>/datenschutz`, dann auf **„In production“** stellen (sonst verfällt die Verbindung nach 7 Tagen)
- [ ] OAuth-Client „Webanwendung“ mit der Rückleitung `/api/oauth/youtube/callback`
- [ ] Bereiche, die das System anfragt: `youtube.upload`, `youtube.readonly`, `yt-analytics.readonly`
- [ ] `.env`: `YOUTUBE_OAUTH_CLIENT_ID`, `YOUTUBE_OAUTH_CLIENT_SECRET`, `YOUTUBE_OAUTH_REDIRECT_URI`; für die Trendsuche `YOUTUBE_API_KEY`
- [ ] Je Themenbereich ein Kanal (Brand-Kanal), telefonisch bestätigt
- [ ] Test: Kanal verbinden, im Freigabecenter einen Beitrag mit Sichtbarkeit **privat** freigeben
- Kosten: 0 €. Grenze: 100 Uploads je Tag über die API (`YOUTUBE_DAILY_UPLOAD_LIMIT`).

### Instagram (Instagram-Login, ohne Facebook-Seite)

- [ ] Instagram-Konten je Bereich auf **Profikonto** (Business oder Creator) umstellen
- [ ] Meta-Entwicklerkonto, App vom Typ „Business“, Produkt **„Instagram“ → „API mit Instagram-Login“**
- [ ] Rückleitung `/api/oauth/instagram/callback`, Berechtigungen `instagram_business_basic` und `instagram_business_content_publish`
- [ ] Die drei mit ⚠️ markierten Token-Adressen in [API_INTEGRATIONS.md](API_INTEGRATIONS.md) einmal im Browser bestätigen
- [ ] `.env`: `INSTAGRAM_LOGIN=instagram`, `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_OAUTH_REDIRECT_URI`
- [ ] **R2 ist Pflicht** für diesen Weg (Meta holt das Video selbst ab): privater Bucket, API-Token nur für diesen Bucket, `.env`: `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. Das Video liegt dort nur 15 Minuten unter einer signierten Adresse und wird danach gelöscht.
- [ ] Klären, ob Posts im Entwicklungsmodus der App öffentlich sichtbar sind; sonst Live-Modus mit Nutzungsbedingungen-URL ⚠️
- [ ] Test: Kanal verbinden; erster echter Post erst nach deiner Freigabe (Instagram-Posts sind sofort öffentlich)
- Kosten: 0 € (R2 im Freikontingent). Grenze: 50 API-Posts je 24 h.

### TikTok (Entwurf in die TikTok-App)

- [ ] Entwicklerkonto, App mit „Login Kit“ und „Content Posting API“
- [ ] Bereiche: `video.upload` (Entwurf), `video.publish` (Direct Post) und `video.list` (Kennzahlen); die Verbindung fragt alle drei an
- [ ] Rückleitung `/api/oauth/tiktok/callback` (TikTok verlangt https), Website mit Datenschutz und Nutzungsbedingungen (`rechtliches.<domain>`)
- [ ] `.env`: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_OAUTH_REDIRECT_URI`, `TIKTOK_POST_MODE=inbox`, `TIKTOK_APP_AUDITED=false`
- [ ] Zuerst in der **Sandbox** testen. Ob eine nicht geprüfte App Entwürfe ohne Einschränkung schicken darf, sagt die Doku nicht ausdrücklich ⚠️ (Entscheidung A17)
- [ ] Ohne App: halbautomatisch (Video herunterladen, in der TikTok-App hochladen)
- Kosten: 0 €. Grenze: höchstens 5 offene Entwürfe je 24 h.

### Facebook (nur falls Reels auf einer Seite gewünscht)

- [ ] Facebook-Seite je Bereich; dieselbe Meta-App mit „Facebook Login for Business“
- [ ] `.env`: `META_APP_ID`, `META_APP_SECRET`, `META_OAUTH_REDIRECT_URI` (`/api/oauth/meta/callback`)
- Grenze: 30 Reels je Seite in 24 h, 3–90 s.

### Twitch (nur Datenquelle)

- Twitch hat **keine Upload-Schnittstelle**. Die vorhandene App liefert nur Trenddaten.
- [ ] Client-Secret erneuern (A2), `.env`: `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`

### Claude (KI-Texte, Chat, Planung)

- [ ] Anthropic-Konto, eigener Arbeitsbereich, **Ausgabenlimit 20 $/Monat** in der Konsole
- [ ] `.env`: `ANTHROPIC_API_KEY`; `AI_MONTHLY_CAP_USD_MAX=20` bleibt
- [ ] Live erst nach deiner Freigabe: `PAID_API_CALLS_ENABLED=true` und Anbieter „Claude“ in den Einstellungen
- Kosten: höchstens 20 $/Monat, doppelt begrenzt (Konsole und System).

### Cloudflare (privater Zugang und R2)

- [ ] Domain auf Cloudflare-Nameserver
- [ ] Zero Trust: Tunnel anlegen, Access-Anwendung nur für deine E-Mail-Adresse ([PRIVATE_ACCESS.md](PRIVATE_ACCESS.md))
- [ ] `.env`: `ACCESS_GUARD=cloudflare`, `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`, `CF_ACCESS_ALLOWED_EMAILS`, `CLOUDFLARE_TUNNEL_TOKEN`, `SINGLE_USER_MODE=true`
- [ ] R2 wie oben unter Instagram; für Sicherungen einen eigenen Bucket mit eigenem Token (A11)
- [ ] Statische Rechtstext-Seite auf `rechtliches.<domain>` (A30), ohne Verbindung zur Anwendung

---

## 6. Ablauf am Tag der Bestellung (Kurzform)

1. Freigabe für den Server (A8) und R2 (A10) geben.
2. Server bestellen, Firewall nur Port 22 (C1), Server-Backups (C2).
3. `harden.sh --tunnel --dry-run`, danach ohne `--dry-run` (C4); Docker installieren (C5).
4. Repository holen (C6), `.env` anlegen (C7), **`preflight.sh --env .env`** (C7a), bis alles „OK“ zeigt.
5. `./scripts/deploy.sh`, Admin anlegen (C8), Uptime Kuma (C10).
6. Erste Sicherung und Wiederherstellungstest (C12).
7. Apps je Plattform nach Abschnitt 5, Kanäle verbinden, je Plattform ein privater Test nach einzelner Freigabe (C14–C16).
8. Aufräumen einplanen (C18), nach einer Woche `housekeeping report` ansehen.
