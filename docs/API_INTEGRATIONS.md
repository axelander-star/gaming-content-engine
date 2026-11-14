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

## Publishing-Plattformen (Phase 12/13)

### YouTube (Shorts)

- **API:** YouTube Data API v3, Upload über die `videos.insert`-Methode (resumable upload), OAuth 2.0 mit Upload-Scope.
- **Metriken:** YouTube Analytics API (Aufrufe, Wiedergabezeit, durchschnittliche Wiedergabedauer, Zuschauerbindung).
- **Einschränkungen:** Uploads verbrauchen einen großen Teil der Tagesquote ⚠️. Uploads aus nicht geprüften API-Projekten können auf „privat" beschränkt sein, bis ein Audit erfolgt ist ⚠️.
- **Shorts-Erkennung:** Hochformat und Länge gemäß aktuellen YouTube-Vorgaben ⚠️.

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
