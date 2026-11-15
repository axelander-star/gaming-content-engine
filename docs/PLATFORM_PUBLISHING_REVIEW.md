# Veröffentlichungswege der Plattformen und externe Backups

Stand: 15.11.2026. Reine Recherche: kein echter API-Aufruf zum Veröffentlichen, kein Account angelegt, nichts gekauft.

Grundlage sind der Code auf `main` (Phase 12/13, Commit `4a55a7b`) und die offiziellen Anbieterseiten, die am 15.11.2026 gelesen wurden (Liste am Ende). Angaben mit ⚠️ sind auf den Seiten widersprüchlich oder nicht eindeutig und müssen vor der Einrichtung im jeweiligen Entwicklerportal bestätigt werden.

**Bedeutung der Statuswerte im Code-Teil**

- **Gebaut, Mock-getestet:** Code vorhanden, Tests laufen mit simulierten HTTP-Antworten. Gegen die echte Plattform wurde **nie** gesendet.
- **Echt geprüft:** mit echten Zugangsdaten gegen die Plattform getestet.
- **Fehlt:** nicht im Code.

## 1. Kurzfassung

| Plattform | Echte Veröffentlichung möglich? | Größte Hürde |
|---|---|---|
| YouTube | **Ja**, auch ohne Prüfung des Google-Projekts (laut aktueller Doku ⚠️) | Google-OAuth-Client anlegen; Upload-Kontingent 100 Videos/Tag je Projekt |
| Twitch | **Nein.** Twitch bietet keine API zum Hochladen von Videos oder Shorts | Nur Datenquelle (Trends, eigene Clips) |
| TikTok | **Nur privat (SELF_ONLY)**, solange die App nicht geprüft ist. Öffentliche Posts brauchen das TikTok-Audit | TikTok schließt laut Richtlinie ausdrücklich „ein Werkzeug zum Hochladen auf die eigenen Konten“ vom Audit aus |
| Instagram | **Ja**, Reels über die Graph API, für eigene Konten ohne App-Review ⚠️ | Profikonto (Business oder Creator) nötig; Posts sind sofort öffentlich |
| Facebook | **Ja**, Reels auf Facebook-**Seiten** (nicht auf Profilen) | Nur Seiten; 30 Reels je Seite in 24 h; sofort öffentlich |

Das wichtigste Ergebnis: **TikTok ist mit einer eigenen App für die eigenen Konten voraussichtlich nicht öffentlich automatisierbar.** Die Richtlinie nennt genau diesen Anwendungsfall als „nicht akzeptabel“ (Details in Abschnitt 3.3). Für TikTok braucht es deshalb eine Entscheidung (Abschnitt 3.3, Optionen A–C).

## 2. Übersicht nach den fünf Ebenen

Legende: ✅ gebaut und mock-getestet · 🟢 echt geprüft · ❌ fehlt · ➖ von der Plattform nicht angeboten

| Ebene | YouTube | Twitch | TikTok | Instagram | Facebook |
|---|---|---|---|---|---|
| **1. API-Verbindung** | ✅ Data API v3 (`services/youtube.py`); API-Key für Trends am 14.11. als ungültig gemeldet | 🟢 Token-Abruf mit Client Credentials am 14.11. erfolgreich; Helix-Abfrage in der Sandbox nicht prüfbar | ✅ `services/tiktok.py` | ✅ `services/meta.py` (Graph API v25.0) | ✅ `services/meta.py` |
| **2. Anmeldung / Account-Verknüpfung** | ✅ OAuth 2.0, Scope `youtube.upload` (+ `youtube.readonly`, `yt-analytics.readonly`), Tokens verschlüsselt | ❌ Nur App-Token (ohne Benutzer). Benutzer-OAuth fehlt | ✅ Login Kit, Scope `video.publish` (+ `video.list`), Refresh-Token 365 Tage | ✅ über **Facebook Login for Business** (Seite + verknüpftes IG-Profikonto). ❌ „Instagram Login“ ohne Facebook-Seite fehlt | ✅ Facebook Login for Business, Seiten-Token |
| **3. Informationen abrufen** | ✅ Trends (`videos.list`), Kennzahlen (`videos.list`, YouTube Analytics) | ✅ Top-Spiele, Streams (Helix) | ✅ Kennzahlen über `video/query` (nur öffentliche Posts haben Zahlen) | ✅ Media Insights | ✅ Video Insights |
| **4. Automatische Content-Erstellung** | ✅ plattformunabhängig (Schnitt, Skript, Untertitel, Formate); KI-Texte und Stimme laufen als Mock | ➖ | wie YouTube | wie YouTube | wie YouTube |
| **5. Echte Veröffentlichung** | ✅ fortsetzbarer Upload, Standard **privat**. Nie echt ausgeführt | ➖ keine Upload-API | ✅ Direct Post, Standard `SELF_ONLY`. Nie echt ausgeführt | ✅ Reels (Container → Upload → Publish). Nie echt ausgeführt | ✅ Reels (`video_reels`). Nie echt ausgeführt |

Ebene 4 ist für alle Plattformen derselbe Ablauf (Phasen 7–10). Echt funktionieren FFmpeg-Schnitt, Formate, eingebrannte Untertitel und Qualitätsprüfung. **Simuliert** sind die KI-Texte (regelbasierte Vorlagen statt LLM) und die Stimme (stille Mock-Stimme), weil dafür kein kostenpflichtiger Anbieter freigegeben ist.

Für Ebene 5 gilt bei allen Plattformen: Veröffentlicht wird nur, wenn `PUBLISHING_MODE=live`, `AUTO_PUBLISH_ENABLED=true`, der Schalter im Dashboard, ein autorisierter Kanal und die Freigabe des Betreibers zusammenkommen. Standard ist Mock.

## 3. Plattformen im Einzelnen

### 3.1 YouTube

**Was die API kann (offiziell):**
- Upload über `videos.insert` (fortsetzbar), Sichtbarkeit `private`, `unlisted` oder `public`, geplante Veröffentlichung über `status.publishAt`. Shorts sind normale Uploads im Hochformat bis 3 Minuten.
- Kontingent: `videos.insert` 100 Aufrufe pro Tag je Google-Cloud-Projekt, alle anderen Aufrufe zusammen 10.000 Einheiten pro Tag. Erhöhung per Antrag bei Google (kostenlos, mit Prüfung).
- Ungeprüfte Projekte: Laut aktueller `videos.insert`-Seite werden Uploads nicht mehr auf „privat“ beschränkt ⚠️ (früher war das so; vor dem ersten echten Upload bestätigen).
- OAuth-Zustimmungsbildschirm im **Testmodus**: Refresh-Tokens laufen nach 7 Tagen ab ⚠️ (Google-Regel für Apps im Status „Testing“). Für Dauerbetrieb die App auf „In production“ stellen; für den sensiblen Scope `youtube.upload` verlangt Google dann eine Verifizierung, solange nicht nur eigene Konten verbunden werden ⚠️.

**Stand im Code:** OAuth, verschlüsselte Tokens, fortsetzbarer Upload mit Wiederaufnahme, Quotenzähler, Standard privat, Kennzahlen. Nie gegen YouTube ausgeführt.

**Fehlt für den echten Betrieb:**
1. Gültiger `YOUTUBE_API_KEY` (der Schlüssel vom 14.11. hatte nicht das Format eines Google-Keys).
2. Google-OAuth-Client (`YOUTUBE_OAUTH_CLIENT_ID`/`_SECRET`) und ein privater Testkanal.
3. Ein öffentlich erreichbarer https-Rückleitungs-Pfad (Server mit Domain) oder lokal `http://localhost`.

**Mehrere Kanäle:** Ja. Ein Google-Konto kann mehrere Kanäle (Brand-Accounts) besitzen; beim Anmelden wählt man den Kanal aus. Im Code hat jeder Kanal eine eigene Verbindung. Alle Kanäle teilen sich aber das Upload-Kontingent des **einen** Google-Projekts (100/Tag).

### 3.2 Twitch

**Was die API kann (offiziell):**
- Lesen: Top-Spiele, Streams, Clips, VODs (Helix, App-Token genügt).
- Clips **erstellen** aus einem laufenden Stream (`POST /helix/clips`, Benutzer-Token mit `clips:edit`).
- Clips **herunterladen**: „Get Clips Download“ ist seit 2026 in der offenen Beta und nur für Broadcaster oder Editoren des jeweiligen Kanals ⚠️.
- **Kein Upload:** Twitch hat keine API zum Hochladen von Videos, Shorts oder Beiträgen.

**Stand im Code:** App-Token (Client Credentials) und Trendabruf. Benutzer-OAuth und Clip-Funktionen fehlen.

**Bedeutung für das Projekt:** Twitch ist eine Datenquelle, kein Veröffentlichungsziel. Für den Gaming Clip Generator ist Twitch nur dann eine Materialquelle, wenn die Rechte vorliegen. Ein öffentlicher Stream ist nicht automatisch frei verwendbar. Technisch herunterladen darf man über die offizielle API nur Clips von Kanälen, bei denen man Broadcaster oder Editor ist.

### 3.3 TikTok

**Was die API kann (offiziell):**

| Punkt | Inhalt |
|---|---|
| Wege | **Direct Post** (`video.publish`, veröffentlicht direkt) und **Upload** (`video.upload`, landet als Entwurf in der TikTok-App, der Nutzer veröffentlicht dort selbst) |
| Ohne Audit | „All content posted by unaudited clients will be restricted to private viewing mode.“ Nur `SELF_ONLY`. Höchstens **5 Nutzer in 24 h** dürfen posten, und die Konten müssen beim Posten **privat** gestellt sein |
| Nach dem Audit | Öffentliche Posts möglich. Tageslimit je App für aktive Creator (aus dem Audit-Antrag) |
| Posting-Limit | „typically around 15 posts per day / creator account“, geteilt über alle Apps, die Direct Post nutzen |
| Rate Limits | `init` 6/min, `creator_info` 20/min, `status/fetch` 30/min je Token |
| Pflicht-UI für das Audit | Nickname des Creators anzeigen; Sichtbarkeit per Auswahlliste **ohne Vorbelegung** vom Nutzer wählen lassen; Kommentar/Duett/Stitch standardmäßig aus; Kennzeichnung kommerzieller Inhalte; Zustimmung zur „Music Usage Confirmation“ **vor** jedem Upload; Vorschau; keine Wasserzeichen |
| Zweck der App | „API Clients must not be limited to test applications and should be intended for a wide audience, not limited to internal groups/private use.“ Ausdrücklich nicht akzeptabel: „A utility tool to help upload contents to the account(s) you or your team manages.“ Ebenfalls nicht akzeptabel: Apps, die beliebige Inhalte von anderen Plattformen zu TikTok kopieren |

**Stand im Code:** Login Kit, Direct Post mit Chunk-Upload, Statusabfrage, Fehlerbehandlung, Kanäle bleiben `connected_restricted` bis `TIKTOK_APP_AUDITED=true`, Sichtbarkeit fest auf `SELF_ONLY`. Nie gegen TikTok ausgeführt.

**Bewertung:**
1. **Private Testposts** gehen ohne Audit, für bis zu 5 Konten, die dafür privat gestellt sein müssen. Das reicht für technische Tests, aber nicht für Reichweite.
2. **Öffentliche Posts** brauchen das Audit. Eine private Steuerzentrale nur für die eigenen Konten ist genau der Fall, den TikTok als nicht akzeptabel nennt. Ein Audit-Antrag ist deshalb voraussichtlich aussichtslos, solange die Plattform nicht für andere Creator angeboten wird.
3. Auch mit Audit verlangt TikTok, dass der Nutzer **pro Post** Sichtbarkeit wählt und zustimmt. Vollautomatisches Posten ohne Klick ist damit nicht vorgesehen. Unsere Freigabeseite müsste diese Felder je Post abfragen; der Code setzt die Sichtbarkeit heute automatisch.
4. Weiterverwendetes Material anderer Plattformen ist laut Richtlinie problematisch. Eigene, lizenzierte Gameplay-Aufnahmen mit eigenem Text sind der sichere Weg.

**Optionen (Entscheidung des Betreibers):**
- **A – Upload als Entwurf (empfohlen prüfen):** System lädt mit `video.upload` als Entwurf hoch, Alexander tippt in der TikTok-App auf „Veröffentlichen“. Ob das ohne Audit erlaubt ist, steht auf den Seiten nicht eindeutig ⚠️; das Entwicklerportal zeigt es beim Anlegen der App. Aufwand im Code: klein (anderer Endpunkt `/v2/post/publish/inbox/video/init/`, gleicher Upload).
- **B – Halbautomatisch:** System erstellt Video, Titel und Hashtags, stellt Datei und Text zum Download bereit, Alexander lädt selbst hoch. Kein API-Risiko, keine Kosten.
- **C – Freigegebener Drittanbieter:** Ein bereits auditierter Planungsdienst postet in unserem Auftrag. Das kostet monatlich und ist ein weiterer Dienst mit Zugriff auf die Konten. Nur nach Kostenaufstellung und Freigabe.

### 3.4 Instagram

**Was die API kann (offiziell):**

| Punkt | Inhalt |
|---|---|
| Zwei Anmeldewege | (1) **Facebook Login for Business**: Instagram-Profikonto muss mit einer Facebook-Seite verknüpft sein (so ist es gebaut). (2) **Instagram API with Instagram Login**: „does not require a Facebook Page to be linked“; für Business- **und** Creator-Konten; Scopes `instagram_business_basic`, `instagram_business_content_publish` |
| Kontotyp | Nur Profikonten (Business oder Creator), keine privaten Konten |
| Formate | Reels, Bilder (nur JPEG), Karussells, Stories |
| Limit | Die Seite nennt einmal 100 und einmal 50 Posts je 24 h ⚠️. Der Code fragt deshalb vor jedem Post `content_publishing_limit` ab |
| Sichtbarkeit | Immer öffentlich, kein Testmodus |
| Freigaben | Für Konten, die in der Meta-App eine Rolle haben (Admin, Entwickler, Tester), genügt Standard-Zugriff ohne App-Review ⚠️. Für fremde Konten braucht es App-Review (Advanced Access) und in der Regel eine Unternehmensverifizierung ⚠️ |

**Stand im Code:** Reels über Facebook Login for Business mit Container, fortsetzbarem Upload und Statusabfrage. Nie gegen Instagram ausgeführt.

**Fehlt:**
1. Meta-App vom Typ „Business“ (`META_APP_ID`/`_SECRET`) und https-Rückleitung (Server mit Domain).
2. **Instagram Login** als zweiter Weg. Damit ließen sich Creator-Konten ohne Facebook-Seite anbinden; das vereinfacht mehrere Instagram-Konten deutlich. Aufwand: mittel (anderer OAuth-Host, eigene Token-Erneuerung, gleiche Publishing-Endpunkte auf `graph.instagram.com`).

**Bewertung:** Echte Veröffentlichung ist für die eigenen Konten realistisch, ohne Prüfung durch Meta. Alle eigenen Instagram-Konten müssen Profikonten sein und als Tester bzw. über das eigene Meta-Konto in der App berechtigt werden.

### 3.5 Facebook

**Was die API kann (offiziell):**
- Reels nur auf **Seiten**: „You can only publish Reels to Facebook Pages.“ Persönliche Profile gehen nicht.
- Limit: 30 Reels je Seite in 24 h (gleitend). Dauer 3–90 s, 9:16, mind. 540×960, 24–60 fps.
- Berechtigungen: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`; der Nutzer braucht auf der Seite die Aufgabe `CREATE_CONTENT`.
- Immer öffentlich. Für eigene Seiten mit Rolle in der App kein App-Review nötig ⚠️.

**Stand im Code:** Reels-Upload in drei Phasen mit Fortsetzung, Statusabfrage. Nie gegen Facebook ausgeführt.

**Bewertung:** Realistisch für eigene Seiten. Die Grenze von 90 s prüft die Qualitätskontrolle bereits je Plattform (`services/quality.py`, `PLATFORM_RULES`).

## 4. Mehrere Accounts je Plattform

**Was heute geht:**
- Beliebig viele Kanäle je Plattform (Tabelle `channels`, eindeutig über Plattform + Sprache + Name).
- Je Kanal genau eine verschlüsselte Verbindung (`channel_credentials`), eigene Strategie, eigene Sicherheitsgrenzen, eigene Duplikaterkennung.
- Jede Veröffentlichung gehört genau einem Kanal; ein Post kann nie im falschen Konto landen (bei Meta wird abgebrochen, wenn mehrere Seiten passen).

**Was fehlt:**
1. **Zuordnung Kanal → Content-Projekt/Themenbereich.** Kanäle haben heute nur Sprache und Plattform. Für „Gaming-TikTok bekommt nur Gaming“ braucht es ein Feld `project_id` und Regeln (gehört zum neuen Kernmodul „Regelbasierte Content-Steuerung“).
2. **Auswahl bei Meta nach einer Anmeldung.** Heute muss man beim Verbinden jedes Kanals im Facebook-Dialog genau die eine passende Seite freigeben. Besser: einmal anmelden, dann im Dashboard die Seite bzw. das Instagram-Konto je Kanal auswählen.
3. **Gleichzeitig oder zeitversetzt posten** je Konto: Die Strategie plant heute je Kanal unabhängig. Eine Gruppenregel („Konto 2 eine Stunde nach Konto 1“) fehlt.
4. **Freigabe je Konto:** Es gibt einen globalen Schalter und die Freigabe je Video. Ein eigener Modus je Konto (automatisch, mit Freigabe, nur sammeln) fehlt.

**Grenzen der Plattformen bei mehreren Konten:**

| Plattform | Grenze |
|---|---|
| YouTube | 100 Uploads/Tag gemeinsam für alle Kanäle eines Google-Projekts (Erhöhung beantragbar) |
| TikTok | ohne Audit höchstens 5 Konten in 24 h, nur privat; je Konto etwa 15 Posts/Tag |
| Instagram | 50 bzw. 100 Posts je Konto in 24 h ⚠️; ohne App-Review nur Konten mit Rolle in der App |
| Facebook | 30 Reels je Seite in 24 h; ohne App-Review nur Seiten, die man selbst verwaltet |
| Alle | Mehrere Konten mit gleichen Inhalten können als Spam gewertet werden. Je Konto eigener Text und eigener Schnitt (bereits Varianten A–D) |

## 5. Was für echte Veröffentlichungen noch fehlt (alle Plattformen)

1. **Server mit Domain und https.** TikTok und Meta akzeptieren nur https-Rückleitungen.
2. **Entwickler-Apps** bei Google, TikTok und Meta (kostenlos, vom Betreiber anzulegen).
3. **Testkonten:** privater YouTube-Testkanal, privates TikTok-Testkonto, Instagram-Profikonto und Facebook-Testseite.
4. **Ausdrückliche Freigabe** für den ersten echten Post je Plattform. Bei Instagram und Facebook ist jeder Post sofort öffentlich.
5. **Code-Ergänzungen:** TikTok-Freigabefelder je Post (Sichtbarkeit ohne Vorbelegung, Zustimmung), TikTok-Entwurfsmodus (Option A), Instagram Login, Kanal-Projekt-Zuordnung, Meta-Seitenauswahl.

## 6. Externe Backups: Hetzner Storage Box oder Cloudflare R2

**Was gesichert wird:** Der Dienst `backup` erzeugt täglich einen GnuPG-verschlüsselten `pg_dump` (14 Tage aufbewahrt). Videos liegen ohnehin in R2. Die Datenbank-Sicherungen sind klein; geschätzt 50–500 MB pro Sicherung, also 1–7 GB bei 14 Tagen.

**Preise (Stand 15.11.2026, offizielle Seiten):**

| | Hetzner Storage Box BX11 | Cloudflare R2 (Standard) |
|---|---|---|
| Speicher | 1 TB fest | nach Verbrauch |
| Preis | 3,20 € / Monat zzgl. MwSt. (≈ 3,81 € brutto) | 0,015 $ / GB-Monat; **10 GB/Monat frei** |
| Schreib-/Lesezugriffe | inklusive | 1 Mio. Schreib- und 10 Mio. Lesezugriffe/Monat frei, danach 4,50 $ bzw. 0,36 $ je Mio. |
| Datenverkehr | inklusive | Abruf kostenlos |
| Einrichtungsgebühr | auf der Seite ausgewiesen, Betrag nicht angezeigt ⚠️ | keine |
| Vertragslaufzeit | keine, sofort kündbar | keine |
| Zugriff | SFTP, rsync, BorgBackup, Restic, rclone, WebDAV, Samba | S3-API (rclone, boto3) |
| Schnappschüsse | 10 (BX11) | Versionierung/Lebenszyklus-Regeln |
| Standort | Deutschland oder Finnland | Region wählbar (EU-Datenhaltung möglich) |

**Geschätzte Monatskosten für unsere Datenbank-Sicherungen:**

| Szenario | Storage Box BX11 | R2 |
|---|---|---|
| 5 GB (realistisch, 14 Tage) | 3,81 € | **0 €** (im Freikontingent) |
| 50 GB (30 Tage, größere DB) | 3,81 € | ca. 0,60 $ (40 GB × 0,015 $) |
| 500 GB (zusätzlich Video-Archiv) | 3,81 € | ca. 7,35 $ |

Achtung: Das R2-Freikontingent gilt einmal je Cloudflare-Konto. Wenn die Videos ebenfalls in R2 liegen, ist es dort schon verbraucht; dann kosten 5 GB Sicherungen etwa 0,08 $ im Monat. Cloudflare verlangt für R2 eine hinterlegte Zahlungsart, auch bei Nutzung im Freikontingent ⚠️.

**Empfehlung: Cloudflare R2, eigener Bucket nur für Sicherungen.**
1. **Anderer Anbieter als der Server.** Fällt das Hetzner-Konto aus oder wird es gesperrt oder kompromittiert, sind die Sicherungen trotzdem da. Die Storage Box hängt am selben Hetzner-Konto wie der geplante Server; das ist nur eine halbe Auslagerung.
2. **Kosten:** bei unserer Datenmenge 0 € bis unter 1 € im Monat statt 3,81 €.
3. **Bereits im Stack:** R2 ist für die Videos vorgesehen, der S3-Zugang ist im Code vorhanden. Für die Sicherungen genügt ein eigener Bucket mit einem eigenen API-Token, der **nur** schreiben darf (kein Löschen), plus eine Lebenszyklus-Regel für das Aufräumen. So kann ein Angreifer auf dem Server alte Sicherungen nicht löschen.
4. Die Sicherungen sind bereits mit GnuPG verschlüsselt, bevor sie den Server verlassen.

**Wann die Storage Box besser ist:** wenn später große Mengen gesichert werden sollen (Video-Archiv, Rohmaterial ab etwa 250 GB) oder BorgBackup mit Deduplizierung gewünscht ist. Ab etwa 250 GB ist der Festpreis günstiger als R2.

Eingerichtet wird nichts ohne ausdrückliche Freigabe. Für die Umsetzung reicht danach eine kleine Erweiterung des Dienstes `backup` (Upload per S3 nach jeder Sicherung, Prüfung im Systemstatus).

## 7. Quellen (gelesen am 15.11.2026)

- TikTok: [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines), [Content Posting API – Get Started](https://developers.tiktok.com/doc/content-posting-api-get-started), [Direct Post Reference](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post), [Upload Content](https://developers.tiktok.com/doc/content-posting-api-get-started-upload-content)
- Meta: [Instagram API with Instagram Login](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login), [Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing), [Reels Publishing (Facebook)](https://developers.facebook.com/docs/video-api/guides/reels-publishing)
- Twitch: [Clips-Doku](https://dev.twitch.tv/docs/api/clips/), [Get Clips Download (Beta)](https://discuss.dev.twitch.com/t/get-clips-download-twitch-api-endpoint-now-available-in-open-beta/64334)
- YouTube: Angaben aus der Prüfung vom 14.11.2026 in `docs/API_INTEGRATIONS.md`
- Speicher: [Hetzner Storage Box](https://www.hetzner.com/storage/storage-box), [BX11](https://www.hetzner.com/storage/storage-box/bx11/), [Cloudflare R2 Pricing](https://developers.cloudflare.com/r2/pricing/) (Stand der Seite 30.10.2026)
