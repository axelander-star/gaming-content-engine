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

### YouTube: mehrere Kanäle (16.11.2026)

- Jeder Kanal im Dashboard hat seine eigene OAuth-Verbindung (`channel_credentials` je Kanal). So lassen sich mehrere YouTube-Kanäle ansteuern, z. B. einer je Themenbereich.
- Die Anmeldung fragt mit `prompt=consent select_account` nach dem Konto bzw. Brand-Kanal, damit beim zweiten Kanal nicht automatisch das erste Konto genommen wird.
- Dasselbe Plattform-Konto (gleiche Kanal- bzw. Konto-ID) kann nur an **einem** Kanal hängen; die Rückleitung lehnt eine zweite Verbindung ab (`?youtube=in_use`). Das gilt für alle Plattformen und verhindert, dass zwei Themenbereiche auf denselben echten Kanal posten.

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

### Erweiterung E8: Freigabecenter und neue Veröffentlichungswege (15.11.2026)

Geprüft am 15.11.2026 gegen die offizielle Dokumentation. Wo eine Seite für automatisches Abrufen gesperrt war, steht ⚠️; diese Punkte vor dem ersten echten Post im Browser nachlesen.

**YouTube (videos.insert, Seiten „videos.insert“ und „Videos resource“, YouTube-Hilfe 15424877)**
- Je Beitrag wählbar: `status.privacyStatus` (`private`, `unlisted`, `public`; Standard im Freigabecenter **privat**), `status.publishAt` (ISO 8601; nur zusammen mit `privacyStatus=private`, das Video wird zu diesem Zeitpunkt öffentlich ⚠️ Regel aus dem zusammengefassten Teil der Seite), `status.selfDeclaredMadeForKids`, `snippet.categoryId` (Standard 22, Gaming-Clips weiter 20), `snippet.tags` aus den Hashtags.
- `status.containsSyntheticMedia` bleibt an die KI-Stimme gebunden.
- **Short oder normales Video:** Die API hat kein Shorts-Feld. Ein quadratisches oder hochformatiges Video bis 3 Minuten wird von YouTube selbst als Short eingeordnet. Die Formatwahl im Freigabecenter steuert deshalb nur die Prüfung (Short: Hochformat, ≤ 3 min) und den Link (`/shorts/` oder `/watch?v=`).
- Quote: die Seite nennt „100 calls per day“ für das Upload-Kontingent ⚠️ (Wortlaut mehrdeutig; vor Live-Betrieb im Quota Calculator nachsehen).

**TikTok als Entwurf (Seiten „Content Posting API – Upload“, „Get Started – Upload Content“, „Get Post Status“)**
- `POST https://open.tiktokapis.com/v2/post/publish/inbox/video/init/` mit `source_info` (`FILE_UPLOAD`, `video_size`, `chunk_size`, `total_chunk_count`), Scope `video.upload`, 6 Anfragen/min je Token. Antwort `publish_id` und `upload_url` (1 h gültig).
- Datei per `PUT` an `upload_url` mit `Content-Type`, `Content-Length`, `Content-Range` (gleich wie Direct Post).
- `POST /v2/post/publish/status/fetch/` bis `SEND_TO_USER_INBOX`: Die Person bekommt eine Benachrichtigung in der TikTok-App und schließt Text und Veröffentlichung dort ab. Erst danach meldet TikTok `PUBLISH_COMPLETE`.
- Höchstens **5 offene Entwürfe in 24 h** (`spam_risk_too_many_pending_share`, wird als „später erneut“ behandelt).
- Standard ist jetzt `TIKTOK_POST_MODE=inbox`. Direct Post bleibt als Option je Beitrag (`direct`, ohne Audit nur `SELF_ONLY`).
- Offen ⚠️: Die Doku sagt nicht ausdrücklich, ob nicht geprüfte Apps den Entwurfsweg ohne Einschränkung nutzen dürfen; sie verlangt nur die Freigabe des Scopes `video.upload`.

**Instagram mit Instagram-Login, ohne Facebook-Seite (Seiten „Instagram API with Instagram Login“, „Content Publishing“, Referenz „oauth/authorize“ und „me“)**
- Für Instagram-Profikonten (Business oder Creator); laut Doku „does not require a Facebook Page“.
- Anmeldung: `https://api.instagram.com/oauth/authorize` mit `client_id`, `redirect_uri`, `response_type=code`, `scope` (Komma-getrennt), `state`. Meta hängt `#_` an die Weiterleitung an; das gehört nicht zum Code. Codes gelten 1 h und einmal.
- Scopes: `instagram_business_basic`, `instagram_business_content_publish` (die alten Namen `business_*` sind seit 27.01.2025 abgekündigt).
- Konto: `GET https://graph.instagram.com/v25.0/me`.
- Code → Kurzzeit-Token `POST https://api.instagram.com/oauth/access_token`, Langzeit-Token (60 Tage) `GET https://graph.instagram.com/access_token?grant_type=ig_exchange_token`, Verlängerung `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token` (Token mindestens 24 h alt). ⚠️ Diese drei Seiten ließen sich am 15.11. nicht automatisch abrufen; die Adressen entsprechen der bekannten Meta-Doku und müssen vor dem ersten Verbinden im Browser bestätigt werden.
- Veröffentlichen: `POST /<IG_ID>/media` mit `media_type=REELS`, `video_url`, `caption`, `share_to_feed` → `GET /<container>?fields=status_code` (`IN_PROGRESS`, `FINISHED`, `ERROR`, `EXPIRED`, `PUBLISHED`; höchstens einmal pro Minute, höchstens 5 Minuten) → `POST /<IG_ID>/media_publish?creation_id=…`.
- **Wichtig:** Der fortsetzbare Upload (`upload_type=resumable`) ist laut Doku nur für Apps mit Facebook-Login. Mit Instagram-Login muss Meta das Video von einer **öffentlich erreichbaren Adresse** holen. Dashboard und API bleiben privat (Cloudflare Access); das Video wird deshalb kurz in einen privaten **Cloudflare-R2-Bucket** gelegt, Meta bekommt eine signierte Adresse, die nach `R2_PRESIGN_SECONDS` (Standard 900 s) verfällt, und die Datei wird danach gelöscht. Ohne R2 meldet der Kanal „nicht eingerichtet“, es wird nichts versucht.
- Limit: 100 API-Posts je 24 h laut Hauptabschnitt (ein anderer Abschnitt nennt 50 ⚠️); geprüft über `content_publishing_limit`. Eigene Obergrenze weiter `INSTAGRAM_DAILY_POST_LIMIT`.
- Kennzahlen über Instagram-Login (`instagram_business_manage_insights`) sind noch nicht angebunden ⚠️; Statistik-Abrufe melden „nicht verfügbar“.
- Der bisherige Weg über eine Facebook-Seite bleibt mit `INSTAGRAM_LOGIN=facebook` nutzbar.

**Cloudflare R2 (S3-API)**
- Signatur AWS Signature Version 4 (Region `auto`, Dienst `s3`), Query-String-Variante. Umsetzung ohne SDK in `services/r2.py`, geprüft gegen das offizielle AWS-Beispiel für signierte Adressen (Test `test_r2_presign_matches_the_aws_example`).
- Endpunkt `https://<ACCOUNT_ID>.r2.cloudflarestorage.com/<BUCKET>/<KEY>`; Bucket bleibt privat.

**Twitch**
- Die Twitch-API (Referenz, geprüft 15.11.2026) hat **keinen Upload-Endpunkt** für Videos. Unter „Videos“ gibt es nur „Get Videos“ und „Delete Videos“; „Clips“ erstellt Clips aus Streams. Twitch bleibt Trendquelle und Livestream-Kanal; das Freigabecenter sagt das offen.

**Code:** `services/approval.py`, `api/approval.py` (`/api/approval…`), `services/instagram.py`, `services/r2.py`, Erweiterungen in `services/tiktok.py`, `services/youtube.py`, `services/publishers.py`; Rückleitung `GET /api/oauth/instagram/callback`.

**Einrichtung Instagram-Login (erst bei Freigabe eines echten Tests):** In der Meta-App das Produkt „Instagram“ → „API setup with Instagram login“ hinzufügen, Weiterleitungs-URI `https://<Dashboard-Domain>/api/oauth/instagram/callback`, `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_OAUTH_REDIRECT_URI` setzen; zusätzlich R2 (`R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`) mit einem Schlüssel, der nur diesen Bucket schreiben darf.

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

- **Chat-Assistent (E4):** nutzt Sonnet 5.5 mit Werkzeugen (Tool Use der Messages API, `strict: true`). Je Nachricht höchstens 4 Aufrufe; jeder Aufruf wird einzeln gegen die Monatsgrenze reserviert. Kein Werkzeug kann veröffentlichen.

## Recherche-Feeds (Erweiterung E5)

- **Schnittstelle:** öffentliche RSS 2.0- und Atom-Feeds, die der Admin je Themenbereich einträgt (Seite „Ideenlabor“). Kein Login, keine Kosten, keine inoffiziellen Wege; Inhalte nur zur Recherche, nichts davon wird wiederveröffentlicht.
- **Modus:** `RESEARCH_SOURCES_MODE=mock` (Standard, kein Netz) oder `live`.
- **Schutz:** nur `http`/`https`, keine Zugangsdaten in der Adresse, keine internen oder privaten Ziele (auch nicht nach Weiterleitung, höchstens 3), höchstens `RESEARCH_MAX_FEED_BYTES` (2 MB), Zeitlimit `HTTP_TIMEOUT_S`, XML ohne Entitäten (`defusedxml`), HTML in Texten wird entfernt.
- **Rest-Risiko:** Zwischen Adressprüfung und Verbindung könnte ein Name umgebogen werden (DNS-Rebinding). Auf dem Server zusätzlich ausgehende Verbindungen in interne Netze per Firewall sperren (E10).

## Kanal-Assistent (Ausbau A1)

| Dienst | Endpunkt | Zweck | Kosten |
|---|---|---|---|
| Cloudflare Email Routing | `POST /client/v4/zones/{zone_id}/email/routing/rules` (Body: `matchers` `[{type: "literal", field: "to", value}]`, `actions` `[{type: "forward", value: [ziel]}]`), Antwort `result.id` (`result.tag` ist veraltet) | Weiterleitungsadresse je neuem TikTok-/Instagram-Konto | kostenlos |
| Cloudflare Email Routing | `DELETE /client/v4/zones/{zone_id}/email/routing/rules/{rule_id}` | Adresse entfernen, wenn die Aufgabe verworfen wird | kostenlos |
| YouTube Data API v3 | `GET /youtube/v3/channels?part=id&forHandle=@name` | Prüfen, ob ein Handle vergeben ist | 1 Kontingent-Einheit |
| YouTube Data API v3 | `GET /youtube/v3/search?part=snippet&type=channel&q=<Thema>&maxResults=10&regionCode=DE|US&relevanceLanguage=de|en` | Bestehende Kanäle zum Thema finden (Namensvorschläge sollen sich abheben) | eigener Topf „Search Queries“ laut Doku; die Engine erlaubt sich 80 Aufrufe am Tag (Zähler `quota:youtube_search`) |
| YouTube Data API v3 | `GET /youtube/v3/channels?part=statistics&id=<ids>` | Abonnentenzahlen der gefundenen Kanäle (`statistics.subscriberCount`, `hiddenSubscriberCount`) | 1 Kontingent-Einheit |

Geprüft am 16.11.2026 gegen [Create routing rule](https://developers.cloudflare.com/api/resources/email_routing/subresources/rules/methods/create/): nur `actions` und `matchers` sind Pflicht, `value` je Aktion ist derzeit auf eine Adresse begrenzt, Token-Recht „Email Routing Rules Write“. Der Lösch-Endpunkt ist noch nicht gegen die Seite geprüft (offener Punkt). Die Zieladresse muss einmalig in Cloudflare bestätigt sein. TikTok und Instagram bieten keine offizielle Schnittstelle zur Prüfung von Benutzernamen; die Engine fragt dort nichts ab.

**Namensvorschläge aus Marktdaten (22.11.2026, `services/name_research.py`):** Suche und Statistik laufen nur mit `YOUTUBE_API_KEY` und `TREND_SOURCES_MODE=live`, nur mit API-Schlüssel (kein OAuth) und kosten nichts. Geprüft am 22.11.2026 gegen die Referenzseiten [search.list](https://developers.google.com/youtube/v3/docs/search/list) und [channels.list](https://developers.google.com/youtube/v3/docs/channels/list): Parameter `part`, `type`, `q`, `maxResults` (0–50), `regionCode`, `relevanceLanguage`; Kanaltitel in `snippet.channelTitle`, Kanal-ID in `id.channelId`. Die Seite nennt für search.list „100 calls per day“ in einem eigenen Topf; diese Angabe bitte in der Google-Cloud-Konsole unter Kontingente gegenprüfen (offener Punkt). Ohne Live-Zugang stützen sich die Vorschläge nur auf eigene Daten: Recherche-Meldungen und Ideen des Themenbereichs sowie Videotitel und Aufrufe aus dem Konkurrenz-Radar (letzte 30 Tage).

### Profil nach dem Verbinden übertragen (26.11.2026)

Nach dem Verbinden eines YouTube-Kanals schreibt die Engine das im Kanal-Assistenten vorbereitete Profil (`services/profile_sync.py`, erneut über „Profil übertragen“ in Einstellungen → Kanäle). Geprüft gegen die Referenz vom 12./16.11.2026:

| Aufruf | Kosten | Zweck |
|---|---|---|
| `channels.list` (part `brandingSettings`, `id`) | 1 Einheit | aktuelle Einstellungen lesen, weil `channels.update` alle Felder des Teils ersetzt |
| `channelBanners.insert` (Upload, `image/png`, 16:9, ≥ 2048 × 1152, ≤ 6 MB) | 50 Einheiten | Banner hochladen, Antwort enthält `url` |
| `channels.update` (part `brandingSettings`) | 50 Einheiten | `channel.description` (≤ 1.000 Zeichen), `channel.keywords` (≤ 500 Zeichen gesamt), `image.bannerExternalUrl` |

- Scope: `youtube.force-ssl` (ist schon Teil der Anmeldung).
- Der Titel wird nie geändert; YouTube lehnt eine Änderung ab (`channelTitleUpdateForbidden`).
- ⚠️ `image.bannerExternalUrl` steht nicht in der Liste der beschreibbaren Felder, die Banner-Anleitung nennt aber genau diesen Weg. Das wird beim ersten echten Kanal geprüft.
- Für Profilbild und Kanal-Links gibt es keine Schnittstelle, auch nicht bei TikTok und Instagram. Das Dashboard bietet Bild und Texte zum Herunterladen und Kopieren an.
- Ein Fehler hebt die Verbindung nicht auf, sondern steht beim Kanal („Profil nicht übertragen: …“).

## Kommentare (Ausbau A3)

Geprüft gegen die Anbieter-Dokumentation am 16.11.2026.

| Plattform | Lesen | Antworten | Recht |
|---|---|---|---|
| YouTube | `GET /youtube/v3/commentThreads?part=snippet&videoId=…&maxResults=100&textFormat=plainText` (1 Einheit) | `POST /youtube/v3/comments?part=snippet` mit `snippet.parentId` und `snippet.textOriginal` (50 Einheiten) | `https://www.googleapis.com/auth/youtube.force-ssl` |
| Instagram (Instagram-Login) | `GET graph.instagram.com/{media-id}/comments` | `POST /{comment-id}/replies` mit `message` | `instagram_business_manage_comments` |
| Instagram (Facebook-Login) | `GET graph.facebook.com/{media-id}/comments` | `POST /{comment-id}/replies` | `instagram_manage_comments` |
| TikTok | keine Schnittstelle für normale Apps | – | Kommentar von Hand ins Dashboard kopieren |

Bestehende Verbindungen haben die neuen Rechte nicht; YouTube und Instagram einmal neu verbinden. Kontingent YouTube: je Lauf bis zu 20 Beiträge lesen (je 1 Einheit) und höchstens 10 Antworten (je 50 Einheiten), also bis zu 520 Einheiten je Lauf. Antworten fallen nur an, wenn neue Kommentare da sind. Bei vielen aktiven Kanälen das Tageskontingent (Standard 10.000) im Blick behalten und notfalls `COMMENTS_SECONDS` erhöhen.

## Konkurrenz-Radar (Ausbau A5)

Geprüft gegen die YouTube-Data-API-Dokumentation am 16.11.2026. Nur öffentliche Daten, nur mit API-Schlüssel (kein OAuth):

| Schritt | Aufruf | Kosten |
|---|---|---|
| Kanal finden (einmal je Kanal) | `GET /youtube/v3/channels?part=snippet,contentDetails&forHandle=@name`, Upload-Liste aus `contentDetails.relatedPlaylists.uploads` | 1 Einheit |
| Neueste Videos | `GET /youtube/v3/playlistItems?part=contentDetails&playlistId=…&maxResults=20` | 1 Einheit |
| Titel und Aufrufe | `GET /youtube/v3/videos?part=snippet,statistics&id=…` | 1 Einheit |

Alle 12 Stunden je Kanal 2–3 Einheiten, bei 30 Kanälen also unter 200 Einheiten am Tag (Tageskontingent 10.000). Fehlermeldungen enthalten nie die URL (sie trägt den Schlüssel). TikTok und Instagram: keine offizielle Schnittstelle für Videos fremder Konten, daher nicht beobachtet.

## Trend-Alarm: YouTube-Trendliste (Ausbau A11)

Offizieller Aufruf der YouTube Data API v3, nur mit API-Schlüssel (kein OAuth): `GET /youtube/v3/videos?part=snippet,statistics&chart=mostPopular&regionCode=DE&maxResults=50`, für Gaming-Themenbereiche zusätzlich mit `videoCategoryId=20`. Kosten 1 Einheit je Aufruf; bei `TREND_ALARM_REGIONS=DE,US` und einem Gaming-Bereich 4 Einheiten je Prüfung, alle 30 Minuten also rund 190 von 10.000 Einheiten am Tag. Gelesen werden nur Titel, Kanalname, Veröffentlichungszeit, Schlagwörter und Zahlen (Aufrufe, Likes, Kommentare). Fremde Videos werden **nicht** heruntergeladen oder verwendet (Nutzungsbedingungen, Urheberrecht); die Entwürfe sind Eigenproduktionen zum Thema. Fehlermeldungen enthalten nie die URL (Schlüssel). Vor dem ersten Live-Betrieb gegen die aktuelle Doku prüfen (`videos.list`, Parameter `chart`, `regionCode`, `videoCategoryId`). TikTok, Instagram und X haben keine offizielle Schnittstelle für fremde Trends und werden nicht beobachtet; „das ganze Internet“ ist damit bewusst auf freie, offizielle Quellen begrenzt (plus Recherche-Feeds und Konkurrenz-Radar).

## Themenvorschläge: YouTube-Trends und Wikipedia (26.11.2026)

„Themen vorschlagen“ unter Themenbereiche (`services/topic_suggest.py`, `POST /projects/suggestions`, nur Admin):

- **YouTube** `videos.list` mit `chart=mostPopular`, `regionCode` aus `TREND_ALARM_REGIONS` (höchstens 3, die erste zählt als Heimatmarkt, Standard DE): je Region zuerst der Gesamt-Chart ohne Kategorie, dann je eine `videoCategoryId` der Standardkategorien außer Musik. Kostet 1 Einheit pro Aufruf, bei DE und US etwa 28 Einheiten pro Klick, und läuft über das eigene Tageslimit `youtube`. Hat eine Kategorie in einer Region keinen eigenen Chart (404, oft bei Gaming und Unterhaltung) oder ist er leer, zählen die Videos dieser Kategorie aus dem Gesamt-Chart (`snippet.categoryId`).
- **Bewertung (seit 26.11.2026):** Wachstum wird innerhalb der eigenen Region verglichen, dazu Chartplätze, Anzahl verschiedener Kanäle und Plätze im Gesamt-Chart. Die Heimatregion zählt voll, andere Regionen mit 0,6, damit US-Zahlen Deutschland nicht überdecken. Gaming und Unterhaltung bekommen immer einen Platz, wenn sie in den Trends vorkommen und noch kein gleichnamiger Themenbereich existiert. Es gibt 8 Vorschläge.
- **„Von der KI ausfüllen“** im Formular eines Themenbereichs (`POST /projects/profile-suggestion`, nur Admin): ordnet den Namen einer YouTube-Kategorie zu und ruft für die Heimatregion den Gesamt-Chart und den Kategorie-Chart ab (2 Einheiten pro Klick). Daraus schreibt die KI Beschreibung, Zielgruppe, Tonalität und Unterthemen; ohne KI eine Vorlage aus den häufigsten Titelwörtern. Gespeichert wird erst mit „Speichern“.
- **Wikipedia** über die Wikimedia Analytics API `GET https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{de|en}.wikipedia/all-access/{JJJJ/MM/TT}`. Sie ist kostenlos und braucht keinen Schlüssel. Abgefragt werden die meistgelesenen Artikel des Vortags. Wikimedia verlangt einen eigenen User-Agent; gesendet wird ein allgemeiner Name ohne persönliche Daten.
- Live nur mit `YOUTUBE_API_KEY` und `TREND_SOURCES_MODE=live`. Im Betrieb ohne Schlüssel erscheint ein Hinweis statt erfundener Zahlen, in der Entwicklung erscheinen gekennzeichnete Beispieldaten.
- Die KI formuliert aus den Zahlen 8 Themenbereiche und darf dabei nur die gelieferten Zahlen nennen. Ohne KI werden die stärksten Kategorien mit Vorlagentext vorgeschlagen.

## Push aufs Handy: ntfy (Ausbau A4)

Geprüft gegen https://docs.ntfy.sh/publish/ am 16.11.2026: `POST https://ntfy.sh/<thema>` mit dem Text als Body; Kopfzeilen `Title`, `Priority` (1–5), `Tags` (Emoji-Kurzcodes), `Click` (URL beim Antippen). Nicht-ASCII in Kopfzeilen wird nach RFC 2047 kodiert (`=?UTF-8?B?…?=`), wie die Doku empfiehlt; Nachrichten über 4.096 Byte würden als Anhang verschickt, die Engine kürzt auf 3.500 Zeichen. Optionaler Zugangstoken als `Authorization: Bearer …` (für geschützte Themen; dieser Teil der Doku wurde nicht live geprüft, Standard ist ein geheimer Themenname ohne Token). Kosten: keine. Die Themen-URL ist geheim und wird nie geloggt.

## Linkseiten, Affiliate, Newsletter, Mailversand (Ausbau A8)

- **Content Rewards:** weiterhin keine Schnittstelle für Clipper; Kampagnen werden von Hand übernommen, die Engine schlägt nur den passenden Themenbereich vor (lokale Berechnung, kein Abruf).
- **Affiliate-Programme:** keine Schnittstelle. Die Engine speichert nur den Link, den Alexander aus dem Partnerprogramm kopiert, und zählt Klicks über die eigene Weiterleitung `/go/<id>`. Werbe-Labels der Plattformen (TikTok „Markeninhalt“, YouTube „Bezahlte Werbung“, Instagram „Bezahlte Partnerschaft“) werden nicht per API gesetzt; TikTok-Beiträge gehen als Entwurf ins Postfach, dort schaltet Alexander das Label ein. Die Kennzeichnung „Anzeige“ steht immer im Text.
- **Mailversand:** SMTP mit STARTTLS (Port 587) oder TLS (Port 465) über Python `smtplib`, Zugangsdaten nur in `.env`. Standard `MAIL_MODE=mock`: nichts wird gesendet. Kosten: keine (Postfach des Domain-Anbieters).

## Speicher

- **Cloudflare R2** (S3-kompatibel). Seit E8 nur für kurzlebige Video-Adressen beim Instagram-Login genutzt (`services/r2.py`, eigene SigV4-Signatur, kein SDK). Ablage der Medien sonst weiter lokal. Preis- und Freikontingent vor Einrichtung prüfen ⚠️.

## Offene Punkte

- Entwickler-Apps bei Google, TikTok und Meta müssen vom Betreiber angelegt werden; Audits/App-Reviews können Wochen dauern.
- Klären, ob deutsche und englische Kanäle getrennte OAuth-Verbindungen benötigen (bei YouTube je Kanal, bei Meta je Seite/Konto).
- Prüfung der echten Veröffentlichungswege, Mehrfach-Konten und Backup-Kosten (15.11.2026): siehe `docs/PLATFORM_PUBLISHING_REVIEW.md`. Wichtigster Punkt: TikTok schließt Upload-Werkzeuge für eigene Konten vom Audit aus; ohne Audit nur private Posts für höchstens 5 Konten.
