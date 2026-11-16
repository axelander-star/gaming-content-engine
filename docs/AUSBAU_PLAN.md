# Ausbauplan ab 16.11.2026

Freigegeben von Alexander am 16.11.2026 abends. Jeder Schritt kommt als eigener, getesteter Pull Request. Es bleibt alles im Testmodus (`PUBLISHING_MODE=mock`, `AUTO_PUBLISH_ENABLED=false`), bis Alexander etwas ausdrücklich freigibt. Keine kostenpflichtigen Aufrufe ohne Freigabe.

| Schritt | Inhalt | Hinweise |
|---|---|---|
| A1 | **Kanal-Assistent**: fehlende Kanäle je Themenbereich auf YouTube, TikTok, Instagram; Name, Benutzername, Bio DE/EN, Profilbild, Banner, E-Mail-Weiterleitung; Aufgabe „Kanal erstellen“ mit Direktlink | Die Engine legt nie selbst Plattform-Konten an. YouTube: Brand-Kanal unter dem Geschäftskonto. |
| A2 | **Konten-Übersicht** für 100+ Konten: Status, Zahlen, Umsatz je Konto (YouTube, Content Rewards, Affiliate), Empfehlung, welche Kanäle sich lohnen; Vorschlag „Kanal pausieren“ nach 90 Tagen ohne Ergebnis | nur Vorschlag, pausieren entscheidet Alexander |
| A3 | **Kommentare beantworten**: YouTube und Instagram automatisch, TikTok als Entwurf (keine Schnittstelle); Kritik, Beschwerden, heikle Themen zur Freigabe; natürlicher Ton ohne KI-Floskeln | im Testmodus nur Entwürfe |
| A4 | **Chat** mit Datei-Upload (Bilder, PDFs), Spracheingabe, vorgelesenen Antworten und Fertig-Meldungen; **Warnsystem** (Sperrhinweise, Copyright, Einbrüche) mit Push aufs Handy | Spracheingabe lokal, Sprachausgabe Piper |
| A5 | **Wochenplan**: „jeden Donnerstag Uhren“ als Regel, selbstfüllend; Feiertage und Events; Konkurrenz-Radar als Ideenquelle | nur offizielle Datenquellen |
| A6 | **Ein Video auf alle Plattformen** inkl. Englisch mit Titeln/Hashtags je Plattform; **lange Videos in Shorts zerlegen** | |
| A7 | **Hooks natürlicher**, Gewinner-Recycling (neuer Hook, Teil 2), A/B-Test von Hooks | |
| A8 | **Kampagnen je Thema** vorschlagen (Content Rewards), **Affiliate-Links** mit Kennzeichnung „Werbung/Anzeige“, **Bio-Link-Seite** je Kanal mit Newsletter-Anmeldung | Kennzeichnungspflicht und Plattformregeln beachten |
| A9 | **Sponsoren-Postfach**: Markenanfragen sortieren, Antwortentwurf mit Preisvorschlag | nur Entwürfe, nichts wird gesendet |
| A10 | **Wochenbericht per E-Mail** | |

Nicht gewünscht: eigene digitale Produkte.

## Einrichtung E-Mail-Weiterleitung (Cloudflare, für A1)

1. Cloudflare → Domain `kanalfabrik.de` → **E-Mail** → **E-Mail-Routing** aktivieren (DNS-Einträge übernimmt Cloudflare).
2. Unter **Zieladressen** das eigene Postfach eintragen und den Link in der Bestätigungsmail anklicken.
3. **Mein Profil → API-Token → Token erstellen → Benutzerdefiniert**: Berechtigung *Zone → Email Routing Rules → Bearbeiten*, Zone nur `kanalfabrik.de`.
4. Auf dem Server in `.env`: `MAIL_ROUTING_MODE=live`, `MAIL_ALIAS_DOMAIN=kanalfabrik.de`, `MAIL_FORWARD_TO=<bestätigte Adresse>`, `CLOUDFLARE_ZONE_ID=<Zone-ID von der Übersichtsseite>`, `CLOUDFLARE_API_TOKEN=<Token>`; danach `scripts/deploy.sh`.
