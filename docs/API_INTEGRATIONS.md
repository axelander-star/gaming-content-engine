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

Geprüft am 14.11.2026 gegen die offizielle Dokumentation (developers.tiktok.com: „Content Posting API – Get Started“, „Direct Post“, „Query Creator Info“, „Get Post Status“, „Media Transfer Guide“, „OAuth User Access Token Management“, „Login Kit for Web“, „Rate Limits“, „Error Handling“):

- **OAuth:** `https://www.tiktok.com/v2/auth/authorize/` mit `client_key`, `scope=video.publish`, `response_type=code`, `redirect_uri` (nur https, exakt registriert), `state`. Token und Erneuerung: `POST https://open.tiktokapis.com/v2/oauth/token/` (Formular). Access-Token 24 h, Refresh-Token 365 Tage; der Refresh-Token kann sich bei jeder Erneuerung ändern, es wird immer der neueste gespeichert. Widerruf: `POST /v2/oauth/revoke/`.
- **Ablauf Direct Post:** `POST /v2/post/publish/creator_info/query/` (erlaubte Sichtbarkeiten, Duett/Stitch/Kommentare) → `POST /v2/post/publish/video/init/` mit `post_info` (`privacy_level` muss aus `privacy_level_options` stammen, `title` ≤ 2200, `disable_*`, `brand_content_toggle`, `is_aigc`) und `source_info` (`FILE_UPLOAD`, `video_size`, `chunk_size`, `total_chunk_count`) → `PUT` der Datei an `upload_url` (1 h gültig) mit `Content-Range` → `POST /v2/post/publish/status/fetch/` bis `PUBLISH_COMPLETE` oder `FAILED`.
- **Chunks:** Dateien bis 64 MB in einem Stück; größere in 10-MB-Stücken, das letzte Stück nimmt den Rest auf (je Stück 5–64 MB, das letzte bis 128 MB, höchstens 1000 Stücke, nacheinander).
- **Post-ID:** `publicaly_available_post_id` (Schreibweise der API) gibt es nur für öffentliche Posts nach der Moderation. Für private Posts speichern wir die `publish_id`.
- **Nicht geprüfte Apps:** „All content posted by unaudited clients will be restricted to private viewing mode.“ `init` liefert sonst `unaudited_client_can_only_post_to_private_accounts`. Kanäle bleiben deshalb `connected_restricted`, bis `TIKTOK_APP_AUDITED=true` gesetzt ist; die Sichtbarkeit ist standardmäßig `SELF_ONLY`.
- **Limits:** `init` 6/min, `creator_info` 20/min, `status/fetch` 30/min je Token. Eine feste Tageszahl nennt TikTok nicht (`spam_risk_too_many_posts` je Nutzer, `reached_active_user_cap` je App; beide werden als „später erneut“ behandelt). Eigene Obergrenze: `TIKTOK_DAILY_POST_LIMIT` (Standard 5 je Kanal und Tag).
- **Fehler:** `access_token_invalid`/`scope_not_authorized` → neu verbinden; `rate_limit_exceeded`, Spam-Grenzen, 5xx → später; manche Fehler kommen mit HTTP 200, entscheidend ist `error.code`.
- **Metriken:** Display API (Phase 14) ⚠️.

### Instagram (Reels) und Facebook (Reels)

Geprüft am 14.11.2026 gegen die offizielle Meta-Dokumentation (Graph API **v25.0**: „Content Publishing“, „IG User Media“, „IG User Media Publish“, „IG Container“, „Content Publishing Limit“, „Reels Publishing“, „Long-Lived Access Tokens“, „Pages API Overview“, „Manual Login Flow“). Die Seite „Business Login for Instagram“ war nicht abrufbar; wir verwenden deshalb **Facebook Login for Business** für beide Plattformen.

- **Anmeldung:** `https://www.facebook.com/v25.0/dialog/oauth` (`client_id`, `redirect_uri`, `state`, `scope`). Code → Token: `GET /v25.0/oauth/access_token`; Langzeit-Token (ca. 60 Tage): `grant_type=fb_exchange_token`; Seiten mit Seiten-Token: `GET /{user-id}/accounts` (nur Seiten mit Aufgabe `CREATE_CONTENT`). Seiten-Tokens aus einem Langzeit-Token laufen laut Doku nicht regulär ab (die Pages-Übersicht spricht dagegen von einer Ablaufzeit ⚠️); Fehlercode 190 setzt den Kanal auf „abgelaufen“.
- **Berechtigungen:** Facebook `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`; Instagram zusätzlich `instagram_basic`, `instagram_content_publish` (Instagram-Profikonto, mit einer Facebook-Seite verknüpft). Erteilte Rechte werden über `GET /me/permissions` gelesen.
- **Eine Seite je Kanal:** Gibt der Betreiber beim Anmelden mehrere passende Seiten frei, wird nicht geraten, sondern abgebrochen („bitte nur die Seite dieses Kanals auswählen“).
- **Instagram:** `GET /{ig-user-id}/content_publishing_limit` (aktuell 50 Posts je 24 h; ein Abschnitt der Doku nennt noch 100 ⚠️) → `POST /{ig-user-id}/media` mit `media_type=REELS`, `upload_type=resumable`, `caption` (≤ 2200 Zeichen) → Upload an `rupload.facebook.com/ig-api-upload/v25.0/{container}` mit `Authorization: OAuth …`, `offset`, `file_size` → `GET /{container}?fields=status_code` bis `FINISHED` (`ERROR`/`EXPIRED` = Fehler; Container verfallen nach 24 h) → `POST /{ig-user-id}/media_publish?creation_id=…`. Spezifikation: MP4/MOV, H.264/HEVC, 3 s–15 min, ≤ 300 MB.
- **Facebook:** `POST /{page-id}/video_reels` `upload_phase=start` → `video_id` → Upload an `rupload.facebook.com/video-upload/v25.0/{video-id}` (Fortsetzung über `status.uploading_phase.bytes_transfered`) → `upload_phase=finish`, `video_state=PUBLISHED`, `description`, `title` → `GET /{video-id}?fields=status`. Spezifikation: 9:16, mind. 540×960, 24–60 fps, **3–90 s**. Limit: 30 Reels je Seite in 24 h.
- **Sichtbarkeit:** Reels auf Seiten und Instagram sind immer öffentlich, es gibt keinen privaten Testmodus. Echte Tests deshalb nur mit einer Testseite bzw. einem Testkonto und nach ausdrücklicher Freigabe.
- **Trennen:** Der gespeicherte Seiten-Token wird gelöscht. Einen Widerrufsaufruf verwenden wir nicht, weil er auf den geprüften Seiten nicht dokumentiert ist; die App kann der Betreiber in den Facebook-Einstellungen entfernen.
- **Fehler:** Code 190 → neu verbinden; 4, 17, 32, 613 (Drosselung) und 5xx → später ⚠️ (Codes aus der allgemeinen Graph-Fehlerdoku, nicht erneut geprüft).
- **Metriken:** Insights-Endpunkte (Phase 14) ⚠️.

#### Umsetzung in Phase 13 und Einrichtung

- **Code:** `services/tiktok.py`, `services/meta.py`, `services/platform.py` (gemeinsame Fehlerklassen und Anmeldestatus), `services/publishers.py`; Rückleitung `GET /api/oauth/{youtube|tiktok|meta}/callback`.
- **TikTok einrichten:** App unter developers.tiktok.com anlegen, Produkte „Login Kit“ und „Content Posting API“ (Direct Post) hinzufügen, Scope `video.publish`, Weiterleitungs-URI `https://<Dashboard-Domain>/api/oauth/tiktok/callback` (TikTok verlangt https). `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_OAUTH_REDIRECT_URI` als Umgebungsvariablen setzen. `TIKTOK_APP_AUDITED=true` erst nach bestandenem TikTok-Audit.
- **Meta einrichten:** App vom Typ „Business“ unter developers.facebook.com mit „Facebook Login for Business“, gültige OAuth-Weiterleitungs-URI `https://<Dashboard-Domain>/api/oauth/meta/callback`, die genannten Berechtigungen (für fremde Konten ist App-Review nötig). `META_APP_ID`, `META_APP_SECRET`, `META_OAUTH_REDIRECT_URI` als Umgebungsvariablen setzen.
- Danach im Dashboard je Kanal „Mit TikTok/Instagram/Facebook verbinden“ (nur Admin). Veröffentlicht wird erst mit `PUBLISHING_MODE=live`, `AUTO_PUBLISH_ENABLED=true`, Dashboard-Freigabe, autorisiertem Kanal und ausdrücklicher Freigabe des Betreibers.

## Kennzahlen je Plattform (Phase 14)

Geprüft am 14.11.2026 gegen die offizielle Dokumentation („videos.list“, „YouTube Analytics reports.query“ und „Metrics“, TikTok „Query Videos“ und „Scopes“, Instagram „Media Insights“, Facebook „Video Insights“). Umsetzung: `services/metrics.py`, Agent `analytics`.

| Kennzahl | YouTube | TikTok | Instagram | Facebook |
|---|---|---|---|---|
| Aufrufe | `viewCount` | `view_count` | `views` | `fb_reels_total_plays` |
| Likes / Kommentare | `likeCount`, `commentCount` | `like_count`, `comment_count` | `likes`, `comments` | – (nur `post_video_social_actions`) |
| Shares | `shares` (Analytics) | `share_count` | `shares` | – |
| Gespeichert | – | – | `saved` | – |
| Ø Wiedergabedauer | `averageViewDuration` (Analytics) | – | `ig_reels_avg_watch_time` (ms) | `post_video_avg_time_watched` (ms) |
| Zuschauerbindung | `averageViewPercentage` (Analytics) | – | – | – |
| Follower-Zuwachs | `subscribersGained` (Analytics) | – | – | `post_video_followers` |

- **YouTube:** `GET /youtube/v3/videos?part=statistics&id=…` (1 Einheit). Zusätzlich `GET https://youtubeanalytics.googleapis.com/v2/reports` mit `ids=channel==MINE`, `filters=video==ID`; Scope `yt-analytics.readonly` (die Doku verlangt inzwischen zusätzlich `youtube.readonly`, beide werden angefragt). Analytics-Daten kommen mit Verzögerung; fehlen sie, bleiben die Felder leer. Bereits verbundene Kanäle müssen für die Analytics-Werte einmal neu verbunden werden.
- **TikTok:** `POST /v2/video/query/?fields=id,view_count,like_count,comment_count,share_count` mit `filters.video_ids` (bis 20), Scope `video.list`. Nur öffentliche Posts haben eine Post-ID; private Testposts liefern deshalb keine Zahlen.
- **Instagram:** `GET /{media-id}/insights?metric=views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time`, Berechtigung `instagram_manage_insights`. Daten können bis zu 48 h verzögert sein; nicht verfügbare Werte fehlen statt 0. `plays` und `ig_reels_aggregated_all_plays_count` sind abgekündigt und werden nicht verwendet.
- **Facebook:** `GET /{video-id}/video_insights` mit `fb_reels_total_plays`, `post_video_avg_time_watched`, `post_video_social_actions`, `post_video_followers`, `post_impressions_unique`; laut Doku `read_insights` und `pages_manage_engagement` sowie die Seitenaufgabe `ANALYZE`. Beide Berechtigungen werden beim Verbinden angefragt. Die genaue Antwortform je Kennzahl ist auf der Seite nicht gezeigt ⚠️; gelesen wird `data[].values[0].value`.
- Fehlt eine Berechtigung, speichert der Agent **keine** Zahlen (nichts wird geschätzt) und vermerkt den Grund im Lauf.
- **Testposts (Mock)** bekommen gleichbleibende synthetische Zahlen (`raw.mock`). Im Live-Modus werden sie von Strategie, Learning und Analytics nicht berücksichtigt.

## KI- und Medienverarbeitung (Phase 7–9)

| Bereich | Bevorzugt | Alternative (kostenpflichtig, budgetgeprüft) |
|---|---|---|
| Szenenerkennung | PySceneDetect, OpenCV (lokal) | – |
| Schnitt/Export | FFmpeg (lokal) | – |
| Transkription | lokales Whisper-Modell, falls CPU-Leistung reicht | externer Dienst |
| Texte/Hooks/Lokalisierung | Vorlagen (lokal) | Claude über die KI-Schicht (siehe unten) |
| Sprachausgabe (TTS) | lokales TTS mit kommerzieller Lizenz, falls Qualität reicht | TTS-API mit kommerziellen Nutzungsrechten |

Auswahl der Anbieter erfolgt erst nach Preisprüfung zum Zeitpunkt der Einrichtung (Spezifikation Abschnitt 13) und Freigabe durch den Betreiber.

## KI-Schicht: Claude (Erweiterung E3)

Entscheidung des Betreibers (15.11.2026): Claude, harte Obergrenze 20 $ je Monat.

- **Schnittstelle:** Claude Messages API über das offizielle Python-SDK `anthropic` (≥ 2.8). Kein Browser, keine inoffiziellen Wege.
- **Modelle:** `claude-haiku-5-5` für kurze Texte (0,10 $ / 0,50 $ je 1 Mio. Ein-/Ausgabe-Tokens, über 100.000 Prompt-Tokens 0,50 $ / 2,50 $), `claude-sonnet-5-5` für Chat, Ideen und Planung (2 $ / 10 $). Preise Stand 03.11.2026; vor der Freischaltung gegen die aktuelle Preisliste prüfen ⚠️.
- **Sonnet-Absicherung:** Lehnt Sonnet 5.5 eine Anfrage aus Sicherheitsgründen ab, wiederholt die API sie im selben Aufruf mit `claude-sonnet-5` (Beta `server-side-fallback-2026-07-01`, gleicher Preis). Haiku hat keine solche Absicherung; eine Ablehnung wird als „abgelehnt“ gemeldet und gebucht.
- **Aufwand:** `output_config.effort = low` als Standard (kurze Antworten, wenig Denkzeit), je Aufruf erhöhbar.
- **Kostenkontrolle:** Vor jedem echten Aufruf wird der ungünstigste Fall (geschätzter Prompt plus alle erlaubten Ausgabe-Tokens) unter einer PostgreSQL-Sperre gegen die Monatsgrenze reserviert; danach ersetzt der echte Verbrauch die Reservierung und wird in Euro ins Budget gebucht. Jeder Aufruf steht in `ai_calls`.
- **Freischaltung (alles nötig):** `ANTHROPIC_API_KEY` auf dem Server, `PAID_API_CALLS_ENABLED=true`, Anbieter „Claude“ in den Einstellungen, kein Not-Aus, Euro-Budget nicht erschöpft. Fehlt etwas, wird der Aufruf blockiert und protokolliert, nie still durch Testdaten ersetzt.
- **Offen:** API-Schlüssel in der Anthropic-Konsole anlegen, dort zusätzlich ein Ausgabenlimit setzen (zweite Sicherung), Freigabe durch den Betreiber.

## Speicher

- **Cloudflare R2** (S3-kompatibel) über boto3/S3-Client. Mock: lokales Verzeichnis. Preis- und Freikontingent vor Einrichtung prüfen ⚠️.

## Offene Punkte

- Entwickler-Apps bei Google, TikTok und Meta müssen vom Betreiber angelegt werden; Audits/App-Reviews können Wochen dauern.
- Klären, ob deutsche und englische Kanäle getrennte OAuth-Verbindungen benötigen (bei YouTube je Kanal, bei Meta je Seite/Konto).
- Prüfung der echten Veröffentlichungswege, Mehrfach-Konten und Backup-Kosten (15.11.2026): siehe `docs/PLATFORM_PUBLISHING_REVIEW.md`. Wichtigster Punkt: TikTok schließt Upload-Werkzeuge für eigene Konten vom Audit aus; ohne Audit nur private Posts für höchstens 5 Konten.
