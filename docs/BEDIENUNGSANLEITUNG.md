# Bedienungsanleitung: KI-Content-Plattform

**Stand:** 15.11.2026 (nach Erweiterung E9) · gilt für das Dashboard unter `/` nach der Anmeldung

Diese Anleitung beschreibt die Seiten, die mit der Erweiterung zur KI-Content-Plattform (E1–E8) dazugekommen sind, und den üblichen Weg von der Idee bis zum Beitrag. Die älteren Seiten der Gaming-Pipeline (Agenten, Rechte, Videoproduktion, Publishing, Analytics, Kosten, System, Einstellungen) funktionieren unverändert, siehe [OPERATIONS.md](OPERATIONS.md).

Am Ende steht die gesammelte Liste der **offenen Freigaben und Voraussetzungen**.

## Die wichtigste Regel vorab

Jedes Video, jede Idee und jeder Kanal gehört zu genau einem **Themenbereich** (z. B. Gaming, Ernährung). Ein Video kann nur auf Kanälen seines eigenen Bereichs erscheinen. Das prüft das System an mehreren Stellen gleichzeitig (Oberfläche, Server, Datenbank, vor dem Veröffentlichen). Du musst darauf also nicht selbst achten; wenn du es versuchst, bekommst du die Meldung „anderer Themenbereich“.

Solange `PUBLISHING_MODE=mock` gilt (Standard), wird **nichts** wirklich veröffentlicht. Alle Beiträge sind dann Testbeiträge und im Dashboard als „Test“ markiert.

## Der übliche Ablauf

1. **Ideenlabor:** Ideen sammeln und eine übernehmen.
2. **Redaktionsplan:** Die Idee landet an einem Tag im Plan. Du siehst die Woche oder den Monat.
3. **Eigenproduktion:** Aus der Idee ein Skript machen, Bilder zuordnen, Video erzeugen.
4. **Mediathek:** Dort liegt das fertige Video, zusammen mit deinen eigenen Aufnahmen.
5. **Freigabecenter:** Beiträge für die Kanäle vorbereiten, Texte prüfen, freigeben.
6. **Publishing:** Der Strategie-Agent entscheidet je Kanal, wann und wie viel veröffentlicht wird.

Alles davon kannst du auch über den **Assistenten** anstoßen.

## Die Seiten im Einzelnen

### Übersicht

Startseite mit Systemzustand (Backend, Datenbank, Warteschlange), Publishing-Modus, Not-Aus, verbundenen Kanälen, letzten Veröffentlichungen und offenen Fehlern. Hier siehst du auf einen Blick, ob etwas hängt.

### Assistent

Ein Chat, über den du das System in Alltagssprache steuerst, z. B. „Diese Woche GTA 6“, „Mittwoch zusätzlich Ernährung“, „Freitag kein Gaming“ oder „Zeig mir die Ideen“. Rechts siehst du den Wochenplan mit den Schwerpunkten.

- Jede Aktion des Assistenten wird angezeigt („Ausgeführt“ oder „Nicht ausgeführt“) und lässt sich mit **Rückgängig** zurücknehmen.
- Der Assistent kann **nichts veröffentlichen** und keine Freigaben erteilen. Das bleibt immer bei dir im Freigabecenter.
- Im Testmodus (Mock) erkennt er nur feste Befehle und kostet nichts. Mit Claude live zählt jede Nachricht zur KI-Monatsgrenze (höchstens 20 $).

### Ideenlabor

Sammelt Ideen aus den Recherche-Quellen je Themenbereich und bewertet sie nach Trend, Passung, Aufwand und Rechte-Risiko.

- **Recherche-Quellen** (RSS-Feeds) legt ein Admin unter „Neue Quelle“ an und schaltet sie ein oder aus. Im Testmodus werden Beispiel-Feeds verwendet, es wird nichts abgerufen.
- **Recherche starten** (Admin) sammelt neue Ideen.
- **Übernehmen** setzt die Idee auf den gewählten Tag im Redaktionsplan. **Verwerfen** legt sie ab.
- Texte aus fremden Quellen werden nur als Text behandelt. Steht dort z. B. „Ignoriere alle Regeln“, hat das keine Wirkung.

### Redaktionsplan

Kalender mit Wochen- oder Monatsansicht (Zeitzone Europe/Berlin). Ein **Schwerpunkt** legt fest, welcher Themenbereich an einem Tag dran ist.

- „Neuer Schwerpunkt“: Bereich und Tag wählen.
- **Tage ohne Eintrag sind für alle Bereiche offen.** Steht an einem Tag „Ernährung“, plant der Strategie-Agent dort keine Gaming-Beiträge.

### Eigenproduktion

Videos ganz ohne fremdes Videomaterial: Text, Stimme, eigene Bilder oder Farbflächen, Untertitel.

1. „Neue Produktion“: Themenbereich, Sprache und entweder eine übernommene Idee oder ein eigenes Thema wählen, dann **Skript erstellen**.
2. Jeden Abschnitt prüfen und ändern: Überschrift, Sprechtext, Bild (nur aus der Mediathek **desselben** Bereichs, sonst Farbfläche), Reihenfolge.
3. **Video erzeugen.** Das fertige Video (Hochformat 1080×1920, Untertitel eingebrannt) landet in der Mediathek als „Selbst erzeugt“.

**Stimme:** Entschieden ist **Piper** (lokal auf dem Server, kostenlos). Deutsch spricht „Thorsten“ (CC0), Englisch „LJ Speech“ (Public Domain); beide Lizenzen erlauben kommerzielle Nutzung. Einschalten unter **Einstellungen → Betrieb → Stimme (TTS)**. Vorher einmal die Stimmen auf den Server laden (`python -m app.piper_voices fetch`, ca. 180 MB). Bis dahin ist die stumme Teststimme aktiv.

### Mediathek

Alle Dateien je Themenbereich: eigene Videos, Bilder, Ton und die selbst erzeugten Videos.

- **Datei hochladen:** Bereich wählen, Datei wählen und **„Eigene Aufnahme bestätigen“** anhaken. Ohne diese Bestätigung wird nichts angenommen; Person und Zeit werden gespeichert.
- Das System prüft die Datei und legt automatisch eine Hochformat-Fassung (9:16) und ein Vorschaubild an. Das Original bleibt zunächst unverändert.
- **Originale hochgeladener Videos werden nach 30 Tagen gelöscht** (deine Entscheidung vom 16.11.). Die 9:16-Fassung bleibt und lässt sich weiter posten. Ist das Original selbst schon die fertige Fassung (Hochformat) oder länger als 3 Minuten, gibt es keine zweite Datei: dann wird das Video nach 30 Tagen archiviert, aber erst, wenn kein vorbereiteter oder eingeplanter Beitrag es mehr braucht. Bilder, Ton und selbst erzeugte Videos sind nicht betroffen.
- **Archivieren** statt Löschen: Archivierte Dateien lassen sich zurückholen und werden nirgends mehr verwendet.

### Freigabecenter

Hier wird aus einem fertigen Video ein Beitrag je Kanal. **Ohne deine Freigabe geht kein Video aus der Mediathek raus.**

1. **Neuer Beitrag:** Video wählen, dann die Kanäle desselben Bereichs ankreuzen und **Beiträge vorbereiten**.
2. Das System prüft das Video je Plattform (Länge, Auflösung, Hochformat, Datei lesbar) und schlägt Titel, Beschreibung und Hashtags vor. Unter „Offene Punkte“ steht, was noch fehlt.
3. Texte und Plattform-Optionen anpassen:
   - **YouTube:** Sichtbarkeit (Standard privat), Short oder normales Video, geplanter Zeitpunkt, „speziell für Kinder“, Kategorie.
   - **TikTok:** „Entwurf in die TikTok-App“ (empfohlen; Text und Veröffentlichen machst du danach in der App) oder „Direkt posten“ (privat, bis die App geprüft ist).
   - **Instagram:** Reel auch im Feed zeigen.
   - **Twitch** hat keine Upload-Schnittstelle. Das steht offen im Freigabecenter; Twitch bleibt eine Datenquelle.
4. **Freigeben.** Der Beitrag ist dann „veröffentlichungsbereit“ und lässt sich nicht mehr ändern.
5. Wann er erscheint, entscheidet der Strategie-Agent je Kanal (Menge und Uhrzeit sind nicht fest eingestellt).
6. **Freigabe zurückziehen** geht auch, wenn der Beitrag schon eingeplant ist; der Auftrag wird dann storniert. Nicht freigegebene Beiträge kannst du **verwerfen**.

### Themenbereiche

Bereiche und ihre Kanäle verwalten (Anlegen und Ändern nur Admin).

- „Neuer Themenbereich“: Name, Sprachen, Unterthemen.
- „Neuer Kanal“: Bereich, Plattform, Sprache und Kanalname. Die Verbindung zur Plattform (OAuth) stellt ein Admin unter **Einstellungen** in der Kanaltabelle her („Mit … verbinden“).
- **Mehrere YouTube-Kanäle:** Jeder Kanal im Dashboard hat seine eigene Verbindung. Lege z. B. „YouTube Gaming“ und „YouTube Ernährung“ an und verbinde jeden mit seinem eigenen YouTube-Kanal. Google fragt dabei, welches Konto bzw. welcher Brand-Kanal gemeint ist. Dasselbe YouTube-Konto lässt sich nicht an zwei Kanäle hängen; das System lehnt es ab, damit Gaming und Ernährung nie auf demselben echten Kanal landen.
- Ein Bereich lässt sich pausieren (dann wird für ihn nichts geplant) oder archivieren.

## Rollen

| Rolle | Darf |
|---|---|
| Betrachter | alles ansehen, nichts ändern |
| Operator | Ideen übernehmen oder verwerfen, Plan, Produktionen, Mediathek, Beiträge vorbereiten und freigeben |
| Admin | zusätzlich Themenbereiche, Kanäle und Recherche-Quellen anlegen, Kanäle verbinden, Einstellungen, Benutzer, Not-Aus |

## Offene Freigaben und Voraussetzungen (gesammelt)

Bevor irgendetwas echt läuft, fehlen noch folgende Punkte. Die Nummern verweisen auf die Tabelle in [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md), Abschnitt 2.

**Entscheidungen, die bei dir liegen**

| Punkt | Frage | Empfehlung |
|---|---|---|
| A18 X/Twitter | anbinden ja/nein | erst nach YouTube und Instagram |
| A11 Sicherungen | Offsite-Kopie in R2 oder Storage Box | R2 |
| Server | Hetzner bestellen (CX33 ca. 10,70 €/Monat brutto) | nach deiner Freigabe; Ablauf in [HETZNER_VORBEREITUNG.md](HETZNER_VORBEREITUNG.md) |
| Domain | Name für Dashboard und Rechtstext-Seite (.de) | kurz, neutral, ohne Themenbezug, weil weitere Bereiche dazukommen |

**Entschieden am 16.11.2026:** Stimme Piper; TikTok als Entwurf ins Postfach (oder je Beitrag „Direkt posten“); Originale eigener Aufnahmen nach 30 Tagen löschen; Hetzner-Konto legst du an.

**Freigaben für Kosten (erst nach deinem ausdrücklichen OK)**

- Claude-API-Schlüssel hinterlegen und `PAID_API_CALLS_ENABLED=true` (A20, höchstens 20 $/Monat).
- Hetzner-Server (A8), Cloudflare R2 (A10, A15b), Domain (A6).

**Konten und Apps, die du anlegen musst**

| Plattform | Was | Punkte |
|---|---|---|
| YouTube | Google-OAuth-Client, App auf „In production“, Kanäle je Bereich | A12, A13 |
| Instagram | Profikonto je Bereich; Meta-App mit „API mit Instagram-Login“; **keine Facebook-Seite nötig**; braucht R2 | A14, A15, A15a, A15b |
| TikTok | App mit Scope `video.upload` (Entwurf); ob ohne Audit möglich, ist offen ⚠️ | A16, A17 |
| Facebook | nur falls Reels auf einer Seite gewünscht | A15 |
| Twitch | keine Upload-Schnittstelle, nur Datenquelle | – |
| Cloudflare | Zero Trust (privater Zugang), R2, Domain | A10, A29 |

**Vor dem ersten echten Verbinden zu prüfen**

- Drei Instagram-Token-Adressen waren nicht automatisch abrufbar und sind in [API_INTEGRATIONS.md](API_INTEGRATIONS.md) mit ⚠️ markiert. Bitte einmal im Browser bestätigen.
- Ob TikTok den Entwurfsweg für nicht geprüfte Apps erlaubt, sagt die Doku nicht ausdrücklich ⚠️.

**Sicherheitsvorgaben, die bis zum Livebetrieb gelten**

- `PUBLISHING_MODE=mock` und `AUTO_PUBLISH_ENABLED=false` bleiben eingestellt.
- Zugangsdaten nur in `.env` auf dem Server bzw. im Passwortmanager, nie im Repository.
- Dashboard und API bleiben hinter Cloudflare Access privat ([PRIVATE_ACCESS.md](PRIVATE_ACCESS.md)).
