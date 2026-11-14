# GAMING CONTENT ENGINE

**Vollständige Projektspezifikation und Bauplan für Claude Code**

**Projekt:** Vollautomatisierte Gaming-Content-Plattform

**Ziel:** Ein cloudbasiertes KI-System, das Gaming-Trends erkennt, rechtlich freigegebenes Gameplay verarbeitet, eigenständige Kurzvideos produziert, diese in Deutsch und Englisch auf mehreren Plattformen veröffentlicht und anhand der tatsächlichen Ergebnisse selbstständig entscheidet, wann und wie viel veröffentlicht wird.

> **Wichtig:** Es gibt keine starre Pflicht, jeden Tag eine bestimmte Anzahl von Videos zu veröffentlichen. Die Veröffentlichungsmenge wird dynamisch anhand der Daten entschieden.

---

## 1. Das Geschäftsmodell

Wir bauen ein automatisiertes Gaming-Content-Unternehmen.

Das System soll eigenständig:

1. Neue Gaming-Trends erkennen.
2. Beliebte und aufkommende Spiele identifizieren.
3. Geeignetes Gameplay-Material finden.
4. Die Nutzungsrechte des Materials überprüfen.
5. Interessante Spielszenen erkennen.
6. Aus den Szenen eigenständige Kurzvideos produzieren.
7. Unterschiedliche Videoformate und kreative Varianten erstellen.
8. Videos auf Deutsch und Englisch lokalisieren.
9. KI-Stimmen und Untertitel erzeugen.
10. Videos technisch und inhaltlich kontrollieren.
11. Den besten Veröffentlichungszeitpunkt bestimmen.
12. Videos auf den verbundenen Plattformen veröffentlichen.
13. Reichweite und Statistiken auswerten.
14. Die Veröffentlichungsmenge automatisch anpassen.
15. Aus erfolgreichen und erfolglosen Videos lernen.

Der Betreiber soll möglichst wenig manuell erledigen müssen.

Das System darf nicht einfach möglichst viele Videos veröffentlichen. Es soll möglichst gute Videos veröffentlichen und die Reichweite langfristig steigern.

## 2. Plattformen und Sprachen

Es werden getrennte deutschsprachige und englischsprachige Kanäle verwaltet.

**Deutsch**

- YouTube Shorts
- TikTok
- Instagram Reels
- Facebook Reels

**Englisch**

- YouTube Shorts
- TikTok
- Instagram Reels
- Facebook Reels

Gesamt: bis zu acht getrennte Veröffentlichungsziele.

Jeder Kanal bekommt:

- Eigenen Namen und eigene Beschreibung
- Eigene Sprache
- Eigene Veröffentlichungsstrategie
- Eigene Statistiken
- Eigene Zielgruppenanalyse
- Eigene Performance-Auswertung

Die englischen Videos sollen keine bloßen Wort-für-Wort-Übersetzungen sein. Hooks, Humor, Formulierungen und Titel müssen für die jeweilige Zielgruppe angepasst werden.

## 3. Automatische Entscheidung über die Anzahl der Videos

Dies ist eine der wichtigsten Funktionen des gesamten Systems.

Es gibt keine feste Vorgabe wie fünf, zehn oder fünfzig Videos pro Tag. Stattdessen besitzt das System einen eigenen **Publishing Strategy Agent**.

Dieser Agent entscheidet für jeden Kanal separat:

- Ob heute veröffentlicht werden soll
- Wie viele Videos veröffentlicht werden sollen
- Welche Videos veröffentlicht werden sollen
- Wann veröffentlicht werden soll
- Welche Videoformate getestet werden sollen
- Welche Videos zurückgehalten werden sollen
- Wann ein Kanal weniger oder mehr Inhalte benötigt

### Daten, die berücksichtigt werden

- Aufrufe nach 1 Stunde
- Aufrufe nach 6 Stunden
- Aufrufe nach 24 Stunden
- Aufrufe nach 48 Stunden
- Aufrufe nach 7 Tagen
- Wiedergabezeit
- Durchschnittliche Wiedergabedauer
- Zuschauerbindung
- Vollständig angesehene Videos
- Wiederholte Wiedergaben, sofern verfügbar
- Likes
- Kommentare
- Geteilte Videos
- Gespeicherte Videos, sofern verfügbar
- Abonnenten- beziehungsweise Follower-Zuwachs
- Interaktionen pro Aufruf
- Entwicklung im Vergleich zu früheren Videos
- Performance nach Spiel
- Performance nach Videoformat
- Performance nach Hook
- Performance nach Sprache
- Performance nach Veröffentlichungszeitpunkt

Nicht jede Plattform stellt alle Daten bereit. Der Agent verwendet nur tatsächlich verfügbare und autorisierte Messwerte.

### Beispiel für die automatische Entscheidung

Angenommen, der deutsche TikTok-Kanal veröffentlicht mehrere Videos.

- Video A erzielt deutlich bessere Ergebnisse als der bisherige Kanaldurchschnitt.
- Video B bleibt deutlich unter dem bisherigen Durchschnitt.
- Video C hat eine gute Zuschauerbindung, aber noch wenige Aufrufe.
- Video D wird häufig geteilt.

Der Agent wertet diese Unterschiede aus.

Mögliche Entscheidungen:

- Erfolgreiche Videoformate stärker testen.
- Schwache Formate reduzieren.
- Gute Videos nicht unnötig durch zu viele neue Veröffentlichungen verdrängen.
- Neue Varianten erfolgreicher Konzepte produzieren.
- Mehr Videos veröffentlichen, wenn die Qualität und die Ergebnisse stimmen.
- Weniger Videos veröffentlichen, wenn die Qualität sinkt oder die Reichweite schwach ist.

> **Wichtig:** Ein Video wird nicht allein wegen niedriger Aufrufzahlen nach einer Stunde als schlecht bewertet. Das System berücksichtigt unterschiedliche Messzeiträume und ausreichend Daten.

### Sicherheitsregeln für die Veröffentlichungsmenge

- Keine automatische Erhöhung nur aufgrund eines einzelnen viralen Videos.
- Keine unbegrenzte Veröffentlichungsmenge.
- Keine Veröffentlichung unterhalb der Qualitätsanforderungen.
- Keine wiederholten nahezu identischen Videos.
- Plattformlimits und API-Vorgaben müssen eingehalten werden.
- Jeder Kanal erhält eigene Mindest- und Höchstgrenzen.
- Der Betreiber kann die automatische Veröffentlichung jederzeit pausieren.

Die Höchstgrenzen sind technische Sicherheitsgrenzen und keine täglichen Veröffentlichungsziele.

## 4. Spiele und Trend-Recherche

Das System soll nicht nur auf ein einziges Spiel ausgerichtet sein. Es soll unterschiedliche Gaming-Kategorien beobachten:

- Open World
- Action
- Shooter
- Horror
- Survival
- Simulation
- Sportspiele
- Rennspiele
- Rollenspiele
- Multiplayer
- Battle Royale
- Indie-Games
- Neue Veröffentlichungen
- Spiele mit plötzlich steigender Aufmerksamkeit

Beispiele für beobachtbare Spiele sind GTA, Minecraft, Fortnite, Roblox, Call of Duty, Resident Evil und weitere aktuelle oder aufkommende Titel. Diese Namen sind Beispiele und keine feste Spieleliste.

### Trendquellen

- YouTube Data API
- Twitch Helix API
- Steam-Daten und öffentlich verfügbare Steam-Schnittstellen
- Offizielle Spiele- und Entwicklerkanäle
- Zulässige öffentliche Trenddaten
- Eigene Performance-Daten der veröffentlichten Videos

### Trend Agent

Der Trend Agent soll täglich und bei Bedarf häufiger:

1. Neue Spiele entdecken.
2. Aufruf- und Interesseentwicklung analysieren.
3. Aufkommende Trends erkennen.
4. Spiele nach Potenzial bewerten.
5. Trends nach Sprache und Zielgruppe unterscheiden.
6. Trends mit bisherigen Videoergebnissen vergleichen.
7. Dem Master Agent konkrete Vorschläge liefern.

Ein Trend ist nicht automatisch eine Produktionsfreigabe. Das Material muss separat beschafft und rechtlich geprüft werden.

## 5. Materialbeschaffung und Nutzungsrechte

Das System benötigt Gameplay-Material, das rechtmäßig für die geplante kommerzielle Nutzung verwendet werden darf.

Mögliche Quellen:

- Eigene Gameplay-Uploads des Betreibers
- Gameplay von Creatorn mit ausdrücklicher Lizenz
- Partner- und Creator-Uploads
- Material aus vertraglich freigegebenen Quellen
- Sonstige eindeutig kommerziell lizenzierte Materialien

### Material Scout Agent

Aufgaben:

- Passende Gameplay-Quellen finden
- Creator und Quellen verwalten
- Lizenzinformationen erfassen
- Herkunft des Materials dokumentieren
- Material nach Spiel und Szene kategorisieren
- Fehlende Nachweise melden

### Rights Agent

Vor jeder Verarbeitung prüft er:

- Ist kommerzielle Nutzung erlaubt?
- Ist Bearbeitung erlaubt?
- Sind Kurzvideos erlaubt?
- Sind alle gewünschten Plattformen abgedeckt?
- Sind deutsche und englische Fassungen erlaubt?
- Ist die Lizenz noch gültig?
- Gibt es Einschränkungen zur Monetarisierung?
- Sind Musik und weitere Bestandteile ebenfalls freigegeben?

**Ohne gültige Freigabe wird kein Material verarbeitet oder veröffentlicht.**

Öffentlich zugängliche Streams und Videos sind nicht automatisch frei verwendbar. Es darf keine unberechtigte Stream-Aufzeichnung oder Video-Übernahme stattfinden.

Für Spiele mit besonderen kommerziellen Nutzungsbedingungen muss die jeweilige Spielepublisher-Policy geprüft werden. Bei GTA 6 beispielsweise darf keine pauschale kommerzielle Freigabe unterstellt werden.

## 6. Die KI-Agenten

Die Plattform erhält eine zentrale Agentensteuerung. Der Master Agent koordiniert alle anderen Agenten. Jeder Agent hat einen klar abgegrenzten Aufgabenbereich.

### Agent 1: Master Orchestrator Agent

Der zentrale Koordinator. Aufgaben:

- Alle Agenten steuern
- Aufgaben priorisieren
- Fehler erkennen
- Produktionsaufträge verteilen
- Budgets kontrollieren
- Veröffentlichungen koordinieren
- Ergebnisse zusammenführen
- Entscheidungen protokollieren

### Agent 2: Trend Research Agent

- Gaming-Trends analysieren
- Neue Spiele erkennen
- Potenzial bewerten
- Trends nach Zielgruppen sortieren
- Trendberichte erstellen

### Agent 3: Game Intelligence Agent

- Spieleinformationen sammeln
- Zielgruppen einschätzen
- Relevante Spielmodi erkennen
- Geeignete Videoideen vorschlagen
- Spiele nach bisheriger Kanalperformance bewerten

### Agent 4: Material Scout Agent

- Freigegebenes Gameplay-Material finden
- Creator-Uploads verwalten
- Quellen dokumentieren
- Material nach Spiel und Kategorie sortieren

### Agent 5: Rights & License Agent

- Lizenzen prüfen
- Rechte dokumentieren
- Ablaufdaten überwachen
- Unzulässige Quellen sperren
- Veröffentlichung ohne Freigabe verhindern

### Agent 6: Gameplay Analysis Agent

- Gameplay analysieren
- Interessante Szenen erkennen
- Action-Momente finden
- Lustige Situationen erkennen
- Überraschungen identifizieren
- Spannende Szenen bewerten
- Zeitmarken für den Videoschnitt erzeugen

### Agent 7: Clip Production Agent

- Szenen schneiden
- Anfang und Ende optimieren
- Hochformat erstellen
- Bildausschnitt anpassen
- Übergänge erstellen
- Formatvarianten produzieren

### Agent 8: Creative Director Agent

- Kreative Konzepte entwickeln
- Hooks erstellen
- Dramaturgie verbessern
- Verschiedene Videoformate planen
- Neue Erzählweisen testen

Mögliche Formate:

- Lustige Gaming-Momente
- Unerwartete Wendungen
- Epische Szenen
- Knapp gescheiterte Situationen
- Überraschungen
- Tipps und Tricks
- Storytelling
- Challenge-Clips
- Vergleichsvideos
- Kurze Spielanalysen

### Agent 9: Script & Hook Agent

- Einstiegssätze schreiben
- Voiceover-Texte erstellen
- Spannungsaufbau planen
- Call-to-Actions formulieren
- Titel und Beschreibungen erstellen

### Agent 10: Localization Agent

- Deutsche Fassungen erstellen
- Englische Fassungen erstellen
- Humor lokalisieren
- Hooks anpassen
- Titel und Beschreibungen lokalisieren

### Agent 11: Voice Agent

- KI-Stimmen erzeugen
- Deutsche Stimmen verwenden
- Englische Stimmen verwenden
- Sprechtempo anpassen
- Aussprache kontrollieren
- Audio synchronisieren

Es dürfen nur Stimmen und TTS-Dienste mit den erforderlichen kommerziellen Nutzungsrechten eingesetzt werden.

### Agent 12: Subtitle Agent

- Untertitel erstellen
- Untertitel synchronisieren
- Lesbarkeit prüfen
- Rechtschreibung kontrollieren
- Positionierung im Hochformat optimieren

### Agent 13: Quality Control Agent

- Videoqualität prüfen
- Audioqualität prüfen
- Untertitel kontrollieren
- Rechtefreigabe kontrollieren
- Doppelte Szenen erkennen
- Fehlerhafte Exporte blockieren
- Plattformanforderungen prüfen

### Agent 14: Publishing Strategy Agent

Dieser Agent entscheidet über die Veröffentlichungsstrategie.

- Veröffentlichungsmenge bestimmen
- Veröffentlichungszeitpunkte bestimmen
- Videos priorisieren
- Kanäle getrennt bewerten
- Performance-Daten berücksichtigen
- Veröffentlichung bei schlechter Qualität stoppen
- Erfolgreiche Formate stärker testen

### Agent 15: Publishing Agent

- Veröffentlichungen vorbereiten
- Titel und Beschreibungen zuordnen
- Plattformen auswählen
- Veröffentlichungen über offizielle APIs ausführen
- Veröffentlichungsstatus speichern
- Fehler und API-Limits behandeln

### Agent 16: Analytics Agent

- Statistiken abrufen
- Aufrufzahlen vergleichen
- Zuschauerbindung analysieren
- Kanalentwicklung messen
- Erfolgreiche Videos erkennen
- Schwache Videos erkennen
- Berichte erstellen

### Agent 17: Learning Agent

- Ergebnisse auswerten
- Kreativstrategien verbessern
- Erfolgreiche Formate identifizieren
- Schlechte Formate reduzieren
- Erkenntnisse an andere Agenten weitergeben
- Änderungen kontrolliert testen

### Agent 18: Budget & Cost Agent

- Serverkosten überwachen
- KI-Kosten überwachen
- Speicherverbrauch kontrollieren
- API-Nutzung kontrollieren
- Monatsbudget überwachen
- Kostenintensive Aufgaben begrenzen

## 7. Videoproduktion

Die Videoproduktion soll vollständig automatisiert werden, sobald geeignetes Material und die erforderlichen Nutzungsrechte vorliegen.

### Produktionsablauf

1. Gameplay-Material laden.
2. Datei technisch prüfen.
3. Spiel und Quelle zuordnen.
4. Interessante Szenen erkennen.
5. Szenen bewerten.
6. Beste Szenen auswählen.
7. Schnittpunkte bestimmen.
8. Video schneiden.
9. Hochformat erzeugen.
10. Hook und Voiceover hinzufügen.
11. Untertitel hinzufügen.
12. Musik und Soundeffekte nur mit passenden Nutzungsrechten einsetzen.
13. Deutsche und englische Variante erstellen.
14. Technische Qualitätskontrolle ausführen.
15. Video für Veröffentlichung freigeben.

### Technische Videoeinstellungen

- Format: MP4
- Codec: H.264
- Seitenverhältnis: 9:16
- Zielauflösung: 1080 × 1920, sofern das Ausgangsmaterial dies ermöglicht
- Audio: AAC
- Untertitel: eingebrannt und/oder als separate Datei
- Framerate: passend zum Ausgangsmaterial und Zielplattform
- Dateigröße: innerhalb der jeweiligen Plattformgrenzen

### Unterschiedliche Varianten

Das System darf nicht einfach denselben Clip mehrfach hochladen. Es soll unterschiedliche eigenständige Varianten erstellen, zum Beispiel:

- Variante A: Schneller, humorvoller Einstieg
- Variante B: Spannungsaufbau mit Überraschung
- Variante C: Kurzes Storytelling
- Variante D: Andere freigegebene Szene desselben Spiels

Jede Variante muss einen echten kreativen Unterschied aufweisen.

Doppelte Inhalte werden mit Hashes, visuellen Fingerprints und Szeneninformationen erkannt.

## 8. Dashboard

Das Dashboard ist die zentrale Bedienoberfläche des Unternehmens. Es soll übersichtlich, modern und professionell aussehen.

### Hauptseite: Übersicht

- Gesamtaufrufe
- Aufrufe heute
- Aufrufe der letzten sieben Tage
- Aufrufe der letzten 30 Tage
- Anzahl veröffentlichter Videos
- Videos in Produktion
- Videos in der Qualitätskontrolle
- Videos mit Veröffentlichungsfreigabe
- Aktive Kanäle
- Beste Videos
- Beste Spiele
- Beste Videoformate
- Aktuelle Trends
- Monatliche Kosten
- Systemstatus

### Seite: Agenten

Für jeden Agenten anzeigen:

- Name
- Aufgabe
- Status
- Letzter Lauf
- Aktuelle Aufgabe
- Ergebnis
- Fehlermeldungen
- Verbrauchte Kosten
- Aktivieren und pausieren

### Seite: Videoproduktion

- Eingehendes Material
- Erkannte Szenen
- Ausgewählte Clips
- Aktuelle Renderjobs
- Deutsche Versionen
- Englische Versionen
- Qualitätsstatus
- Freigegebene Videos
- Fehlerhafte Videos

### Seite: Publishing

- YouTube
- TikTok
- Instagram
- Facebook
- Deutsche Kanäle
- Englische Kanäle
- Veröffentlichungsstatus
- Geplante Veröffentlichungen
- Fehlgeschlagene Veröffentlichungen
- Automatische Veröffentlichungsstrategie

### Seite: Analytics

Filter:

- Plattform
- Sprache
- Spiel
- Zeitraum
- Videoformat
- Hook
- Veröffentlichungszeitpunkt

Diagramme:

- Aufrufe über Zeit
- Zuschauerbindung
- Durchschnittliche Wiedergabedauer
- Interaktionsrate
- Follower-Wachstum
- Performance pro Spiel
- Performance pro Format
- Performance pro Kanal

### Seite: Einstellungen

- Monatsbudget
- Automatische Veröffentlichung an/aus
- Maximale tägliche Produktionsjobs
- Maximale parallele Renderjobs
- Mindestqualität
- Mindestabstand zwischen Veröffentlichungen
- Maximale Veröffentlichungen pro Kanal
- Sprachen
- Plattformen
- KI-Anbieter
- TTS-Anbieter
- API-Verbindungen
- Benachrichtigungen

### Seite: Kosten

- Serverkosten
- KI-Kosten
- Speicher
- API-Kosten
- Monatliche Gesamtkosten
- Kosten pro produziertem Video
- Kosten pro veröffentlichtem Video
- Kosten pro 1.000 Aufrufe, soweit berechenbar

## 9. Technische Architektur

Das System soll cloudbasiert laufen und nicht vom privaten PC abhängig sein.

### Vorgeschlagene Infrastruktur

Server:

- Hetzner Cloud CX33 als Startkonfiguration
- 4 vCPU
- 8 GB RAM
- 80 GB Speicher
- Ubuntu 24.04 LTS

Diese Größe ist ein Startpunkt und keine Garantie für eine Produktion von 50 Videos täglich. Die tatsächliche Kapazität muss gemessen werden.

### Software

| Bereich | Technologie |
|---|---|
| Backend | Python, FastAPI |
| Frontend | Next.js, React, TypeScript |
| Datenbank | PostgreSQL |
| Queue | Redis |
| Workflow | n8n |
| Videobearbeitung | FFmpeg, OpenCV, PySceneDetect |
| Speicher | Cloudflare R2 |
| Reverse Proxy | Caddy |
| Container | Docker, Docker Compose |
| Monitoring | Uptime Kuma, strukturierte Logs, Fehlerüberwachung, Kostenüberwachung |
| Versionsverwaltung | GitHub |

### Architektur

Der Ablauf:

Trendquellen → Trend Agent → Master Agent → Material Scout → Rights Agent → Gameplay Analysis → Clip Production → Creative Agent → Localization → Voice Agent → Subtitle Agent → Quality Control → Publishing Strategy → Publishing Agent → Analytics Agent → Learning Agent.

Alle Agenten kommunizieren über das Backend und die Aufgabenwarteschlange.

Alle wichtigen Entscheidungen werden in PostgreSQL protokolliert.

## 10. Datenbank

Mindestens folgende Datenbankbereiche sind erforderlich:

- users
- channels
- platforms
- games
- trends
- creators
- sources
- licenses
- assets
- gameplay_files
- scenes
- clips
- variants
- scripts
- voiceovers
- subtitles
- quality_checks
- publishing_jobs
- posts
- metrics
- analytics_snapshots
- agent_runs
- agent_decisions
- costs
- system_settings
- notifications
- audit_logs

Jedes Video muss bis zu seiner Quelle zurückverfolgbar sein.

## 11. Automatische Veröffentlichung

Die Veröffentlichungen sollen über offizielle Schnittstellen erfolgen.

- YouTube Data API
- TikTok Content Posting API
- Instagram Graph API
- Facebook Graph API

Es dürfen keine Passwort-Bots eingesetzt werden, die Plattformbeschränkungen umgehen.

Jede Plattform hat eigene Anforderungen und Berechtigungen. TikTok kann beispielsweise bei nicht geprüften Anwendungen Einschränkungen für öffentliche Veröffentlichungen haben.

Das System muss erkennen, ob ein Kanal tatsächlich zur Veröffentlichung autorisiert ist.

Wenn eine Plattform nicht freigeschaltet ist, bleibt das Video im Status `READY_TO_PUBLISH`.

## 12. Automatische Lernstrategie

Die KI soll nicht nur Statistiken anzeigen, sondern daraus Entscheidungen ableiten.

**Beispiel:** Ein bestimmtes Horror-Spiel erzeugt über mehrere Videos hinweg eine überdurchschnittliche Zuschauerbindung.

Der Learning Agent erkennt:

- Das Spiel funktioniert gut.
- Das Format funktioniert gut.
- Die Hook-Struktur funktioniert gut.

Der Publishing Strategy Agent kann daraufhin:

- Mehr passende Szenen priorisieren.
- Neue Varianten testen.
- Den Veröffentlichungsplan für den betreffenden Kanal anpassen.

Ein anderes Spiel erzeugt dauerhaft schwache Ergebnisse. Es wird entsprechend niedriger priorisiert.

> **Wichtig:** Die KI darf nicht voreilig aus wenigen Daten lernen. Es sollen ausreichend Daten gesammelt werden. Änderungen sollen zunächst kontrolliert getestet werden. Die bisherige Strategie muss gespeichert werden, damit eine schlechte Änderung rückgängig gemacht werden kann.

## 13. Budget und Kostenkontrolle

Zielbudget: maximal etwa 50 Euro pro Monat. Das ist ein Planungsziel und keine garantierte Gesamtkostenzusage.

Mögliche Kostenbereiche:

- Cloudserver
- Speicher
- Backups
- Domain
- Externe KI-Modelle
- Sprachgenerierung
- API-Dienste

Die Kosten müssen vor der Einrichtung anhand der jeweils aktuellen Anbieterpreise geprüft werden.

### Budgetregeln

| Verbrauch | Reaktion |
|---|---|
| 50 % | Warnung |
| 70 % | Kostenreduzierter Betrieb |
| 85 % | Nur priorisierte Aufgaben |
| 95 % | Kostenpflichtige Zusatzaufgaben stoppen |

Der Budget Agent muss vor jeder kostenpflichtigen externen KI-Anfrage prüfen, ob das Budget ausreicht.

Lokale Verarbeitung soll bevorzugt werden, sofern sie auf dem Server wirtschaftlich und technisch sinnvoll ist.

Keine unkontrollierten KI-Schleifen und keine unbegrenzten API-Aufrufe.

Servergrundkosten laufen auch dann weiter, wenn die Produktion pausiert wird.

## 14. Produktionsstufen

Das System soll schrittweise aufgebaut werden.

**Stufe 1: Technische Grundlage** – Repository, Docker, Backend, Datenbank, Redis, Dashboard-Grundgerüst, Benutzeranmeldung, Monitoring

**Stufe 2: Agentensystem** – Master Agent, Trend Agent, Game Intelligence Agent, Material Scout, Rights Agent, Agentenprotokollierung

**Stufe 3: Videoproduktion** – Gameplay-Upload, Szenenerkennung, Clip-Schnitt, Hochformat, Voiceover, Untertitel, Qualitätskontrolle

**Stufe 4: Mehrsprachigkeit** – Deutsche Version, Englische Version, lokalisierte Titel, lokalisierte Beschreibungen, unterschiedliche kreative Varianten

**Stufe 5: Publishing** – YouTube, TikTok, Instagram, Facebook, getrennte Sprachkanäle, Veröffentlichungsplanung

**Stufe 6: Analytics** – Statistiken abrufen, Performance vergleichen, Kanalberichte, Spieleberichte, Formatberichte

**Stufe 7: Selbstoptimierung** – Publishing Strategy Agent, Learning Agent, dynamische Veröffentlichungsmenge, automatische Priorisierung, kontrollierte Tests, Budgetoptimierung

**Stufe 8: Skalierung** – Mehr Renderkapazität, mehr Quellen, mehr Spiele, mehr Videoformate, höheres Produktionsvolumen

Die Skalierung erfolgt nur, wenn Messwerte zeigen, dass die vorhandene Infrastruktur ausgelastet ist.

## 15. Sicherheit und Kontrolle

Pflichtanforderungen:

- Sichere Anmeldung
- Verschlüsselte Zugangsdaten
- API-Schlüssel nicht im Quellcode
- Environment-Variablen und Secret-Verwaltung
- Regelmäßige Backups
- Rollen- und Rechteverwaltung
- Protokollierung aller Veröffentlichungen
- Nachvollziehbare Lizenznachweise
- Fehlerüberwachung
- Wiederherstellung nach Fehlern
- Schutz vor doppelten Veröffentlichungen
- Not-Aus-Schalter
- Pausieren einzelner Agenten
- Pausieren einzelner Plattformen

Die automatische Veröffentlichung muss standardmäßig ausgeschaltet sein, bis alle Tests erfolgreich abgeschlossen und die Plattformzugänge freigegeben sind.

## 16. Workflow-Status

Jedes Material und jedes Video durchläuft nachvollziehbare Status:

```
DISCOVERED
RIGHTS_PENDING
RIGHTS_APPROVED
ANALYZED
SCENE_SELECTED
EDITING
LOCALIZATION
VOICEOVER
SUBTITLES
QUALITY_CHECK
QUALITY_APPROVED
READY_TO_PUBLISH
SCHEDULED
PUBLISHED
ANALYTICS_PENDING
ANALYZED
ARCHIVED
```

Bei einem Fehler wird der Status dokumentiert und eine erneute Verarbeitung ermöglicht.

## 17. Wichtige Geschäftsregeln

1. Keine Veröffentlichung ohne Rechteprüfung.
2. Keine Veröffentlichung ohne Qualitätsfreigabe.
3. Keine identischen Massen-Uploads.
4. Keine feste tägliche Veröffentlichungspflicht.
5. Die Veröffentlichungsmenge wird anhand von Daten bestimmt.
6. Jeder Kanal wird separat analysiert.
7. Deutsch und Englisch werden separat optimiert.
8. Das System muss Kosten kontrollieren.
9. Der Betreiber kann jederzeit eingreifen.
10. Alle wichtigen Entscheidungen müssen nachvollziehbar sein.
11. Die tatsächlichen Plattform- und API-Berechtigungen müssen berücksichtigt werden.
12. Das System muss auch dann sicher weiterarbeiten, wenn einzelne Dienste ausfallen.

## 18. Claude-Code-Umsetzungsanweisung

Claude Code soll dieses Projekt als vollständige, modular aufgebaute Software entwickeln. Nicht nur ein Konzept oder eine Demo erstellen. Es sollen echte, ausführbare Anwendungen mit Backend, Frontend, Datenbank, Agenten, Workflows, Tests und Dokumentation entstehen.

### Grundregeln für Claude Code

- Lies zuerst die gesamte PROJECT_SPEC.md.
- Lies die CLAUDE.md.
- Arbeite modular.
- Erstelle keine riesigen unübersichtlichen Dateien.
- Verwende saubere Typisierung.
- Schreibe automatisierte Tests.
- Dokumentiere jede wichtige Funktion.
- Erstelle Docker-Konfigurationen.
- Verwende keine erfundenen API-Funktionen.
- Erfinde keine erfolgreichen Plattformverbindungen.
- Erstelle keine kostenpflichtigen API-Aufrufe ohne ausdrückliche Freigabe.
- Veröffentliche keine echten Videos während der Entwicklung.
- Verwende zunächst Testdaten und Mock-Dienste.
- Prüfe Sicherheitsaspekte.
- Führe nach jeder Entwicklungsphase Tests aus.
- Dokumentiere alle offenen Punkte.
- Arbeite nicht alle Phasen gleichzeitig ab.

### Projektstruktur

```
gaming-content-engine/
├── CLAUDE.md
├── PROJECT_SPEC.md
├── README.md
├── .gitignore
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEVELOPMENT_PLAN.md
│   ├── SECURITY.md
│   ├── PROJECT_STATUS.md
│   ├── API_INTEGRATIONS.md
│   └── AGENTS.md
├── backend/
│   ├── app/
│   ├── agents/
│   ├── api/
│   ├── core/
│   ├── database/
│   ├── models/
│   ├── services/
│   ├── workflows/
│   └── tests/
├── frontend/
│   ├── app/
│   ├── components/
│   ├── dashboard/
│   ├── lib/
│   └── public/
├── infrastructure/
│   ├── docker/
│   ├── caddy/
│   └── monitoring/
└── scripts/
```

### Entwicklungsphasen

- **Phase 1:** Repository, Dokumentation, Architektur und Projektgrundlage.
- **Phase 2:** Docker, PostgreSQL, Redis und Backend.
- **Phase 3:** Anmeldung, Benutzerverwaltung und Dashboard-Grundgerüst.
- **Phase 4:** Master Agent und Agentenverwaltung.
- **Phase 5:** Trend Research und Game Intelligence.
- **Phase 6:** Material Scout und Rights Agent.
- **Phase 7:** Gameplay-Analyse und Videoproduktion.
- **Phase 8:** Creative Director, Hooks und Skripte.
- **Phase 9:** Deutsch- und Englisch-Lokalisierung, Voiceover und Untertitel.
- **Phase 10:** Quality Control und Duplikaterkennung.
- **Phase 11:** Publishing Strategy Agent und dynamische Veröffentlichungsplanung.
- **Phase 12:** YouTube-Integration.
- **Phase 13:** TikTok-, Instagram- und Facebook-Integration.
- **Phase 14:** Analytics, Learning Agent und Budgetkontrolle.
- **Phase 15:** Monitoring, Sicherheit, Backups und Skalierung.

Nach jeder Phase:

- Tests durchführen
- Fehler beheben
- Dokumentation aktualisieren
- PROJECT_STATUS.md aktualisieren
- Nächste Phase erst beginnen, wenn die aktuelle Phase geprüft wurde

## 19. Startanweisung für Claude Code

Beginne jetzt mit Phase 1.

Erstelle die Projektstruktur, die Dokumentation, die Architektur und den Entwicklungsplan.

Baue noch keine echte Social-Media-Veröffentlichung ein.

Führe noch keine kostenpflichtigen KI- oder API-Aufrufe durch.

Erstelle zunächst eine technisch saubere Grundlage, die später erweitert werden kann.

Arbeite danach Phase für Phase.

Gib nach jeder Phase aus:

1. Was wurde erstellt?
2. Welche Dateien wurden geändert?
3. Welche Tests wurden durchgeführt?
4. Welche Tests waren erfolgreich?
5. Welche Fehler bestehen noch?
6. Was ist der nächste Schritt?

Das Ziel ist eine tatsächlich ausführbare Gaming Content Engine und kein bloßes Konzept.

## 20. Abschlusskriterien

Das Projekt gilt erst als funktionsfähig, wenn folgender Ablauf erfolgreich getestet wurde:

1. Das System erkennt einen Gaming-Trend.
2. Es findet geeignetes Material.
3. Es prüft die Nutzungsrechte.
4. Es analysiert das Gameplay.
5. Es erkennt interessante Szenen.
6. Es produziert eigenständige Kurzvideos.
7. Es erzeugt deutsche und englische Fassungen.
8. Es erzeugt Voiceover und Untertitel.
9. Es kontrolliert die Qualität.
10. Es entscheidet anhand der Kanalstatistiken über die Veröffentlichung.
11. Es veröffentlicht über autorisierte Plattformzugänge.
12. Es erfasst die Performance.
13. Es lernt aus den Ergebnissen.
14. Es passt die nächste Veröffentlichungsstrategie an.
15. Es zeigt alle Vorgänge im Dashboard.

**Endziel:** Ein möglichst autonomes, cloudbasiertes Gaming-Content-Unternehmen, das seine Inhalte selbstständig recherchiert, produziert, veröffentlicht und anhand realer Performance-Daten optimiert. Der Betreiber kontrolliert das System über ein einziges Dashboard.
