# Externe Schnittstellen

> **Verbindlicher Hinweis:** Dieses Dokument ist ein Planungsstand (Phase 1). Kein Endpunkt, keine Quote und keine Berechtigung darf ohne Prüfung gegen die **aktuelle offizielle Dokumentation** des Anbieters implementiert werden. Angaben mit ⚠️ sind ausdrücklich zu verifizieren. Es werden keine API-Funktionen erfunden; fehlt eine Funktion in der offiziellen Doku, wird sie nicht gebaut.

## Grundsätze

1. Jeder Dienst hat ein **Adapter-Interface** mit `MockAdapter` (Standard) und `LiveAdapter`.
2. `LiveAdapter` ist nur aktiv, wenn Zugangsdaten vorhanden sind **und** der Betreiber den Dienst freigeschaltet hat.
3. Kostenpflichtige Adapter prüfen vor jedem Aufruf `PAID_API_CALLS_ENABLED` und das Budget.
4. Quoten und Rate-Limits werden pro Dienst gezählt; bei Erschöpfung wird pausiert, nicht wiederholt.
5. **Autorisierungsstatus je Kanal** wird gespeichert (`not_connected`, `connected_restricted`, `authorized`, `expired`). Nur `authorized` erlaubt eine Veröffentlichung, sonst bleibt das Video `READY_TO_PUBLISH`.

---

## Trendquellen (Phase 5)

| Dienst | Zweck | Zugang | Kosten | Hinweise |
|---|---|---|---|---|
| YouTube Data API v3 | Trend- und Suchdaten zu Gaming-Videos | API-Schlüssel | kostenlos, Tagesquote | Quote in Einheiten pro Tag; Suchaufrufe sind teuer im Quotenverbrauch ⚠️ |
| Twitch Helix API | Top-Spiele, Zuschauerzahlen | App-Access-Token (Client Credentials) | kostenlos | Rate-Limit pro Token ⚠️ |
| Steam Web API | Aktuelle Spielerzahlen je App | Web-API-Schlüssel | kostenlos | Store-Daten (Details, Neuerscheinungen) teils nur über inoffizielle Endpunkte – Nutzung prüfen ⚠️ |
| Offizielle Spiele-/Entwicklerkanäle | Ankündigungen, Releases | je nach Quelle (RSS, API) | kostenlos | nur zulässige Quellen |
| Eigene Performance-Daten | Rückkopplung | intern | – | aus `metrics` |

### Umsetzung in Phase 5

Standard ist `TREND_SOURCES_MODE=mock`: erfundene Testspiele mit festen, datumsabhängigen Werten, kein Netzwerkzugriff. Der Live-Modus nutzt ausschließlich diese Endpunkte (Code: `backend/services/sources/live.py`, Tests mit simuliertem HTTP):

| Quelle | Endpunkt | Zugang | Grenze im Code |
|---|---|---|---|
| Twitch | `POST https://id.twitch.tv/oauth2/token` (Client Credentials), `GET https://api.twitch.tv/helix/games/top`, `GET https://api.twitch.tv/helix/streams?game_id=…&first=100` | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | `TWITCH_MAX_REQUESTS_PER_RUN` (20) |
| Steam | `GET https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid=…` | kein Schlüssel nötig | `STEAM_MAX_REQUESTS_PER_RUN` (30), nur Spiele mit bekannter App-ID |
| YouTube | `GET https://www.googleapis.com/youtube/v3/videos?chart=mostPopular&videoCategoryId=20&regionCode=DE/US` (1 Quoteneinheit) | `YOUTUBE_API_KEY` | `YOUTUBE_DAILY_QUOTA_UNITS` (2000/Tag) |

- Alle Aufrufe werden vorab in Redis gezählt (`quota:<quelle>:<tag>`); bei Erschöpfung bricht die Quelle ab, statt zu wiederholen.
- Fehlende Schlüssel: die Quelle wird mit Begründung übersprungen, keine Fehlermeldung, kein Aufruf.
- Der YouTube-Schlüssel steht in der URL; er wird deshalb nie in Fehlermeldungen oder Logs übernommen.
- Twitch-Zuschauer stammen aus einer Stichprobe der 100 größten Streams je Spiel; YouTube-Aufrufe werden über Spielnamen in Titel und Tags beliebter Gaming-Videos zugeordnet.
- ⚠️ Vor dem Einschalten prüfen: aktuelle Twitch-Rate-Limits, ob Kategorie 20 (Gaming) für `mostPopular` in DE und US geliefert wird, Steam-Nutzungsbedingungen.
- Spieldetails aus dem Steam-Store (inoffizielle Endpunkte) werden bewusst **nicht** genutzt.

### Live-Anbindung einrichten (ergänzt am 14.11.2026)

**Zugangsdaten eintragen.** Nur als Umgebungsvariablen, nie im Code oder in Git:

| Variable | Wofür |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3, API-Schlüssel (in der Google Cloud Console auf „YouTube Data API v3“ beschränken) |
| `TWITCH_CLIENT_ID` | Twitch-App, Client-ID |
| `TWITCH_CLIENT_SECRET` | Twitch-App, Client-Secret |

- Betrieb mit Docker: Datei `.env` im Hauptordner des Repos (Kopie von `.env.example`, durch `.gitignore` ausgeschlossen). Jede Variable steht dort genau einmal im Abschnitt „Trendquellen“.
- Lokaler Start aus `backend/`: Es werden `../.env` und `backend/.env` gelesen. Leere Werte gelten als „nicht gesetzt“; eine leere Zeile überschreibt also nie einen echten Wert.
- Danach erst `TREND_SOURCES_MODE=live` setzen. Mit `mock` laufen weiter Testdaten. Das ist auch der Rückfall, falls eine Quelle ausfällt.

**Nur lesend.** Twitch nutzt ein App-Access-Token (Client Credentials) ohne Benutzerrechte, YouTube nur `videos.list` mit API-Schlüssel, Steam nur die öffentliche Spielerzahl. Es gibt keine schreibenden Aufrufe und keine kostenpflichtigen Dienste.

**Quoten und Rate Limits.**
- Jeder Aufruf wird vorab gegen eine eigene Tagesgrenze in Redis gezählt (YouTube `YOUTUBE_DAILY_QUOTA_UNITS`, Twitch und Steam je 2000 Anfragen pro Tag) und pro Lauf zusätzlich begrenzt.
- Das Twitch-Token wird bis kurz vor Ablauf wiederverwendet (Redis, mit TTL) statt bei jedem Lauf neu angefordert. Bei HTTP 401 wird es verworfen.
- HTTP 429 (Rate Limit) beendet den Twitch-Lauf sofort statt zu wiederholen. Bei YouTube beenden 400/401/403/429 den Lauf nach dem ersten Fehler, weil die zweite Sprache gleich scheitern würde.

**Status im Dashboard** (Einstellungen, „Trendquellen“): Modus, ob die Zugangsdaten hinterlegt sind (nur ja/nein, nie der Wert), Status des letzten Laufs oder Tests, verbrauchte Quote heute und Fehlertexte. Fehlertexte enthalten nur HTTP-Status und den Fehlergrund des Anbieters (z. B. `HTTP 403 Zugriff verweigert (quotaExceeded)`), nie URLs oder Schlüssel. Ein Lauf mit Testdaten wird als „Testdaten, keine Verbindung“ angezeigt, nie als „Verbunden“.

**Verbindungstest** (nur Admin, `POST /api/trends/sources/{youtube|twitch|steam}/test`): genau eine lesende Anfrage, auch im Mock-Modus, damit die Schlüssel vor dem Umschalten geprüft werden können. Verbrauch: YouTube 1 Einheit, Twitch 1 Anfrage (plus Token, falls keines gespeichert ist), Steam 1 Anfrage. Jeder Test steht im Audit-Log.

**Auswertung.** Je Spiel und Sprache speichert jeder Trendlauf Score, Aufrufe (YouTube), Zuschauer (Twitch), Spieler (Steam) und das Wachstum. `GET /api/games/{id}/history` liefert den Verlauf; das Dashboard zeigt ihn beim Aufklappen eines Spiels als Kurve mit Tabelle.

## Publishing-Plattformen (Phase 12/13)

### YouTube (Shorts)

Geprüft am 14.11.2026 gegen die offizielle Dokumentation (Seiten „videos.insert“, „Quota Calculator“, „Resumable Uploads“, Stand 12.11.2026; „OAuth 2.0 for Web Server Applications“):

- **Upload:** `POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`. Header `X-Upload-Content-Length`, `X-Upload-Content-Type` (`video/*`), Body = Video-Ressource als JSON. Antwort 200 mit `Location` (Upload-URL). Danach `PUT` der Datei; 201 = fertig. 500/502/503/504 oder Verbindungsabbruch: Stand mit `Content-Range: bytes */GRÖSSE` abfragen (308 + `Range`) und ab dem nächsten Byte fortsetzen, mit exponentiellem Backoff; 404 = Sitzung abgelaufen, neu beginnen; andere 4xx = dauerhafter Fehler. Höchstens 256 GB, MIME `video/*` oder `application/octet-stream`.
- **Felder:** `snippet.title`, `snippet.description`, `snippet.tags`, `snippet.categoryId` (20 = Gaming), `snippet.defaultLanguage`; `status.privacyStatus` (ohne Angabe **öffentlich** – wir setzen es deshalb immer ausdrücklich), `status.selfDeclaredMadeForKids`, `status.containsSyntheticMedia` (KI-Stimme). `notifySubscribers` ist standardmäßig `true`.
- **OAuth:** `https://accounts.google.com/o/oauth2/v2/auth` mit `access_type=offline`, `prompt=consent`, Scope `https://www.googleapis.com/auth/youtube.upload` (zum Lesen des Kanals zusätzlich `youtube.readonly`); Token: `https://oauth2.googleapis.com/token` (`authorization_code`, `refresh_token`); Widerruf: `https://oauth2.googleapis.com/revoke` (laut Codebeispielen). Refresh-Tokens gelten bis zum Widerruf; `invalid_grant` = neu verbinden. Je Kanal eine eigene Verbindung.
- **Quote:** `videos.insert` hat ein eigenes Kontingent von **100 Aufrufen pro Tag** (je 1 Einheit), alle anderen Endpunkte zusammen 10.000 Einheiten/Tag; `channels.list` und `videos.list` je 1. Rücksetzung um Mitternacht Pacific Time. Auch fehlerhafte Aufrufe kosten mindestens 1 Einheit.
- **Nicht geprüfte Projekte:** Die aktuelle videos.insert-Seite sagt: „Videos uploaded from unverified API projects are not restricted to private viewing mode.“ Die frühere Einschränkung auf „privat“ ist damit laut Doku aufgehoben ⚠️ (vor dem ersten echten Upload im Revisionsverlauf bestätigen).
- **Metriken:** YouTube Analytics API (Phase 14).
- **Shorts:** Hochformat bis 3 Minuten (YouTube-Hilfe); es gibt keinen eigenen Shorts-Parameter.

#### Umsetzung in Phase 12 und Einrichtung

- **Code:** `services/youtube.py` (OAuth, Token-Erneuerung, fortsetzbarer Upload), `services/publishers.py` (Mock- und YouTube-Publisher), `agents/publishing.py`, `api/channels.py` (`POST /api/channels/{id}/connect`, `POST /api/channels/{id}/disconnect`, `GET /api/oauth/youtube/callback`).
- **Tokens:** verschlüsselt (Fernet, Schlüssel aus `CREDENTIALS_ENCRYPTION_KEY`) in `channel_credentials`, nie im Dashboard, nie in Logs. Trennen widerruft das Token bei Google und löscht es.
- **Sichtbarkeit:** Uploads standardmäßig **privat** (`YOUTUBE_UPLOAD_PRIVACY=private`), immer ausdrücklich gesetzt.
- **Quote:** eigene Obergrenze `YOUTUBE_DAILY_UPLOAD_LIMIT` (Standard 100); bei `quotaExceeded` wartet der Auftrag und wird später erneut versucht.
- **Einrichtung durch den Betreiber** (erst wenn ein echter Test-Upload freigegeben ist):
  1. In der Google Cloud Console ein Projekt mit aktivierter „YouTube Data API v3“ anlegen, OAuth-Zustimmungsbildschirm einrichten (Testmodus, eigenes Google-Konto als Testnutzer).
  2. OAuth-Client vom Typ „Webanwendung“ anlegen, Weiterleitungs-URI exakt wie `YOUTUBE_OAUTH_REDIRECT_URI` (lokal `http://localhost:3000/api/oauth/youtube/callback`, auf dem Server die Dashboard-Domain).
  3. `YOUTUBE_OAUTH_CLIENT_ID` und `YOUTUBE_OAUTH_CLIENT_SECRET` als Umgebungsvariablen auf dem Server setzen (nicht in Git, nicht im Chat).
  4. Im Dashboard unter Einstellungen → Kanäle „Mit YouTube verbinden“ (nur Admin) und mit einem **privaten Testkanal** anmelden.
  5. Echte Uploads erst, wenn zusätzlich `PUBLISHING_MODE=live`, `AUTO_PUBLISH_ENABLED=true`, der Schalter im Dashboard und die ausdrückliche Freigabe des Betreibers vorliegen.

### TikTok

- **API:** TikTok Content Posting API (Direct Post bzw. Upload als Entwurf), OAuth mit Login Kit.
- **Metriken:** TikTok Display API liefert Basiszahlen pro Video (z. B. Aufrufe, Likes, Kommentare, Shares) ⚠️; Zuschauerbindung ist voraussichtlich nicht verfügbar.
- **Einschränkungen:** Nicht geprüfte (unaudited) Apps dürfen laut Spezifikation und TikTok-Doku nur eingeschränkt, typischerweise nicht öffentlich, posten ⚠️. Die Engine erkennt diesen Status und hält Videos in `READY_TO_PUBLISH`.

### Instagram (Reels)

- **API:** Instagram Graph API (Content Publishing) für Professional-Konten, die mit einer Facebook-Seite verknüpft sind. Ablauf: Medien-Container mit Typ Reels anlegen, Verarbeitung abwarten, veröffentlichen ⚠️.
- **Metriken:** Insights-Endpunkte (Reichweite, Wiedergaben, Interaktionen) ⚠️.
- **Einschränkungen:** Tageslimit für per API veröffentlichte Beiträge ⚠️; Video muss über eine öffentlich erreichbare URL bereitgestellt werden (R2 mit signierter URL) ⚠️; App-Review für Berechtigungen erforderlich.

### Facebook (Reels)

- **API:** Facebook Graph API, Reels-Veröffentlichung auf Seiten (mehrstufiger Upload: Start, Upload, Abschluss) mit Page-Access-Token ⚠️.
- **Metriken:** Video-/Reels-Insights der Seite ⚠️.
- **Einschränkungen:** App-Review und Seitenberechtigungen erforderlich.

## Verfügbarkeit der Kennzahlen je Plattform (vorläufig)

Der Publishing Strategy Agent nutzt nur tatsächlich verfügbare Kennzahlen. Vorläufige Einschätzung, in Phase 12–14 zu bestätigen:

| Kennzahl | YouTube | TikTok | Instagram | Facebook |
|---|---|---|---|---|
| Aufrufe | ✅ | ✅ | ✅ | ✅ |
| Wiedergabezeit / Ø-Dauer | ✅ | ⚠️ | ⚠️ | ⚠️ |
| Zuschauerbindung | ✅ | ❓ | ❓ | ⚠️ |
| Likes / Kommentare / Shares | ✅ | ✅ | ✅ | ✅ |
| Gespeichert | ❓ | ❓ | ⚠️ | ❓ |
| Follower-Zuwachs | ✅ | ⚠️ | ⚠️ | ⚠️ |

✅ wahrscheinlich verfügbar · ⚠️ teilweise/zu prüfen · ❓ vermutlich nicht verfügbar

## KI- und Medienverarbeitung (Phase 7–9)

| Bereich | Bevorzugt | Alternative (kostenpflichtig, budgetgeprüft) |
|---|---|---|
| Szenenerkennung | PySceneDetect, OpenCV (lokal) | – |
| Schnitt/Export | FFmpeg (lokal) | – |
| Transkription | lokales Whisper-Modell, falls CPU-Leistung reicht | externer Dienst |
| Texte/Hooks/Lokalisierung | – | LLM-API (Anbieter offen) |
| Sprachausgabe (TTS) | lokales TTS mit kommerzieller Lizenz, falls Qualität reicht | TTS-API mit kommerziellen Nutzungsrechten |

Auswahl der Anbieter erfolgt erst nach Preisprüfung zum Zeitpunkt der Einrichtung (Spezifikation Abschnitt 13) und Freigabe durch den Betreiber.

## Speicher

- **Cloudflare R2** (S3-kompatibel) über boto3/S3-Client. Mock: lokales Verzeichnis. Preis- und Freikontingent vor Einrichtung prüfen ⚠️.

## Offene Punkte

- Entwickler-Apps bei Google, TikTok und Meta müssen vom Betreiber angelegt werden; Audits/App-Reviews können Wochen dauern.
- Klären, ob deutsche und englische Kanäle getrennte OAuth-Verbindungen benötigen (bei YouTube je Kanal, bei Meta je Seite/Konto).
