# Abnahmetest nach Spezifikation Abschnitt 20

**Durchgeführt:** 15.11.2026, Entwicklungsumgebung (PostgreSQL 16, Redis, FFmpeg, Mock-Modus) · **Dauer:** ca. 55 s · **Test:** `backend/tests/acceptance/test_spec_section20.py`

Der Test spielt die 15 Schritte aus Abschnitt 20 als **einen zusammenhängenden Durchlauf** ab: vom Trend bis zur angepassten Strategie, mit derselben Datenbank, denselben Agenten und denselben API-Endpunkten wie im Betrieb. Die Agenten laufen über den Master Agent und dessen Freigabe-Prüfungen (Gates), nur synchron statt über die Warteschlange.

```bash
cd backend
ACCEPTANCE_REPORT=/tmp/acceptance.json pytest -q tests/acceptance   # Protokoll als JSON
```

Der Test läuft in jeder CI zusammen mit allen anderen Backend-Tests.

## Einordnung: echt oder simuliert

Wie gewünscht wird nichts als erfolgreich bezeichnet, was nur simuliert wurde. Jeder Schritt hat deshalb eine von drei Einstufungen:

- **Echt:** Der Schritt lief mit dem echten Code und echten Daten (Datei, Datenbank, FFmpeg). Er würde im Betrieb genauso ablaufen.
- **Teilweise simuliert:** Der Ablauf ist echt, aber ein Teil davon ist ein Platzhalter (z. B. die Stimme).
- **Simuliert:** Der Ablauf ist im Code vorhanden, wurde aber nur gegen Testdaten oder Mock-Dienste geprüft. **Ob er mit der echten Plattform funktioniert, ist nicht bewiesen.**

## Ergebnis je Schritt

| # | Schritt (Spezifikation) | Einstufung | Ergebnis und Nachweis |
|---|---|---|---|
| 1 | Gaming-Trend erkennen | **Simuliert** | Trend Research und Game Intelligence laufen echt, aber auf **Testdaten** (`TREND_SOURCES_MODE=mock`). Top-Trend „Neon Drift Rivals“ (Score 68,7), Spielprofil mit 4 Videoideen. Echte Quellen (YouTube, Twitch, Steam) sind gebaut, aber noch nicht erfolgreich abgefragt (siehe „Offene Punkte“). |
| 2 | Geeignetes Material finden | **Teilweise simuliert** | Das Material ist ein mit FFmpeg erzeugtes **Testvideo** (1080p, 45 s). Es wurde über die echte Upload-API hochgeladen und technisch geprüft. Der Material Scout gleicht Trends mit vorhandenem, freigegebenem Material ab und meldet Bedarf. Er **sucht nicht selbst im Netz** und lädt nichts herunter. Das ist Absicht (keine Inhalte ohne nachgewiesene Rechte), weicht aber vom Wortlaut „finden“ ab. |
| 3 | Nutzungsrechte prüfen | **Echt** (mit Testannahme) | Lizenz mit Nachweis-PDF und Bedingungen über die API angelegt, durch einen Admin freigegeben; die Rechteprüfung bestätigt alle 12 Kriterien. **Annahme:** Die Publisher-Richtlinie des Spiels ist für den Test als „erlaubt“ hinterlegt. Eine echte Lizenz liegt nicht vor. |
| 4 | Gameplay analysieren | **Echt** | Video 1920×1080, 45 s, mit FFmpeg analysiert (Bewegung, Lautstärke, Schnitte). |
| 5 | Interessante Szenen erkennen | **Echt** | Beste Szene 6–35 s mit Wert 0,85. Sie überdeckt den eingebauten Action-Teil (15–35 s) vollständig, der ruhige Anfang wurde schlechter bewertet. |
| 6 | Eigenständige Kurzvideos produzieren | **Echt** | Ein Clip 1080×1920, H.264/AAC gerendert. |
| 7 | Deutsche und englische Fassungen | **Echt** (ohne KI) | 4 Varianten (DE und EN), 8 Skripte. Texte stammen aus **Vorlagen**, nicht aus einem Sprachmodell (kostenpflichtig, nicht freigegeben). |
| 8 | Voiceover und Untertitel | **Teilweise simuliert** | Untertitel: 12 Stück erzeugt und eingebrannt (**echt**). Voiceover: 4 Spuren vom Anbieter „mock“, also **stille Test-Stimme, keine Sprachausgabe**. |
| 9 | Qualität kontrollieren | **Echt** | 4 von 4 Prüfungen bestanden; danach Status READY_TO_PUBLISH bzw. SCHEDULED. |
| 10 | Veröffentlichung anhand der Kanalstatistiken entscheiden | **Echt** (ohne echte Statistik) | Publishing Strategy Agent erstellt für „YouTube Shorts DE“ Strategie-Version 1: 1 Post/Tag („vorsichtiger Start“), 1 Auftrag geplant. Die Entscheidung ist echt, es gab aber noch keine Kanalstatistik, deshalb der vorsichtige Start. |
| 11 | Über autorisierte Plattformzugänge veröffentlichen | **Simuliert** | 1 Test-Post im Mock-Modus über den Publishing Agent. **Nichts wurde hochgeladen.** Ein echter Upload wurde auf keiner Plattform ausgeführt. |
| 12 | Performance erfassen | **Simuliert** | Analytics Agent holt Kennzahlen im 1-h-Fenster: 283 Aufrufe, **synthetisch** für den Test-Post. Tagesbericht angelegt, Variante wechselt nach ANALYTICS_PENDING. |
| 13 | Aus den Ergebnissen lernen | **Simuliert** | Weil es keine echten Daten gibt, legt der Test 40 Test-Posts über 4 Tage mit festgelegten Zahlen an. Darauf erstellt der Learning Agent Lernversion 1 (Testphase): „Neon Drift Rivals“ Median 1,34× → Gewicht 1,20; „GTA VI“ 0,56×. Die **Logik ist echt**, die Datengrundlage nicht. |
| 14 | Nächste Strategie anpassen | **Teilweise simuliert** | Strategie-Version 2 für den Folgetag übernimmt das Gelernte: Auswahlgewicht für „Neon Drift Rivals“ 1,34 statt 1,00. Die **Menge bleibt bei 1/Tag**, weil die Gesamtleistung des Kanals im üblichen Bereich liegt (Median 1,00×). Das ist korrektes Verhalten, eine Mengenänderung wurde in diesem Lauf aber nicht gezeigt (sie ist in `tests/integration/test_publishing_strategy.py` und `tests/unit/test_strategy_simulation.py` einzeln getestet). |
| 15 | Alle Vorgänge im Dashboard zeigen | **Echt** | 11 Dashboard-Endpunkte liefern die Daten (HTTP 200), 51 Agentenläufe protokolliert. Die Oberfläche selbst prüft der Playwright-Test (`frontend/e2e/smoke.mjs`). |

**Zusammengefasst:** Alle 15 Schritte laufen ohne Fehler durch. **Echt** funktionieren Rechteprüfung, Analyse, Szenenerkennung, Schnitt, Varianten, Untertitel, Qualitätskontrolle, Strategieentscheidung, Lernlogik und Dashboard. **Simuliert** sind Trenddaten, Materialbeschaffung, Stimme, Veröffentlichung und Kennzahlen. Der Abnahmetest beweist damit, dass die Kette technisch zusammenhängt. **Er beweist nicht, dass das System schon mit echten Plattformen arbeitet.**

## Fehler, die beim Abnahmetest gefunden wurden

| Befund | Auswirkung | Umgang |
|---|---|---|
| Standardwert `max_daily_production_jobs = 10` ist zu niedrig | Schon **ein** Material in DE und EN braucht rund 16 Produktionsaufträge (Analyse, Szenen, Clip, Skripte, Stimme, Untertitel, QC je Variante). Mit dem Standardwert bleibt die Pipeline am ersten Tag stehen, ohne Fehlermeldung, nur mit „Tageslimit erreicht“ im Agentenprotokoll. | Im Test auf 200 gesetzt. **Empfehlung:** Wert im Dashboard unter Einstellungen → Betrieb auf ca. 50 setzen (≈ 3 Materialien/Tag) und im Plan Phase B den Standard anheben sowie eine deutliche Warnung im Dashboard einbauen. Bewusst nicht still geändert, weil der Wert eine Kostenbremse ist. |
| Neue Kanäle starten pausiert | Ohne aktiven Kanal plant die Strategie nichts. | Kein Fehler, sondern gewollt (Sicherheit). Im Test wurden der erste DE- und EN-Kanal entpausiert. In der Inbetriebnahme-Checkliste aufgenommen. |

Weitere Fehler im Programmcode wurden nicht gefunden. Die übrigen Anpassungen am Test betrafen nur den Test selbst (Feldnamen, Zugriffspfade).

## Abweichungen von der Spezifikation

1. **Material wird nicht selbst gesucht** (Schritt 2): Spezifikation „geeignetes Material finden“. Umgesetzt ist das Abgleichen von Trends mit **registriertem, lizenziertem** Material. Grund: Öffentlich zugängliche Videos dürfen nicht automatisch als frei verwendbar behandelt werden.
2. **Texte ohne KI** (Schritt 7): Vorlagen statt Sprachmodell, bis ein Anbieter freigegeben ist.
3. **Keine echte Stimme** (Schritt 8): Mock-Anbieter, bis ein TTS-Anbieter freigegeben ist.
4. **Twitch kann nicht veröffentlichen**: Twitch bietet keine Upload-API; Twitch bleibt Datenquelle (Details: [PLATFORM_PUBLISHING_REVIEW.md](PLATFORM_PUBLISHING_REVIEW.md)).
5. **TikTok nur privat**: Ohne TikTok-Audit erlaubt die API nur `SELF_ONLY`; das Audit schließt Werkzeuge für eigene Konten laut Richtlinie aus.

## Offene technische Probleme

| Problem | Stand |
|---|---|
| YouTube-API-Schlüssel | Von Google als ungültig abgelehnt (14.11. und 15.11.). Muss neu erstellt und **nur** als Umgebungsvariable bzw. Netzwerk-Secret hinterlegt werden. |
| Twitch-Zugang | Token-Abruf war am 14.11. erfolgreich. Eine Helix-Abfrage wurde noch nicht erfolgreich ausgeführt. Die neuen Umgebungsvariablen kommen erst in einer neuen Sitzung an. |
| Zugangsdaten in `.env.example` auf `main` | Echte Werte wurden eingecheckt; der zweite Thread entfernt sie (PR #17). **Die betroffenen Schlüssel müssen rotiert werden**, weil sie in der Git-Historie bleiben. |
| Steam | Aus der Entwicklungsumgebung nicht erreichbar, wird auf dem Server geprüft. |
| Kein echter Upload | Auf keiner Plattform wurde jemals echt hochgeladen; alle Publisher sind nur gegen Mocks getestet. |
| Keine Zwei-Faktor-Anmeldung | Admins melden sich nur mit Passwort an (siehe [SECURITY.md](SECURITY.md) Abschnitt 10). |
| Kein externes Backup | Sicherungen liegen nur auf dem Server. Empfehlung Cloudflare R2, wartet auf Freigabe. |
| Standard-Tageslimit | siehe „Fehler“ oben. |

## Voraussetzungen für den Livebetrieb

Reihenfolge entspricht dem Plan in [ROADMAP.md](ROADMAP.md). Alles, was Geld kostet, ist markiert und braucht die ausdrückliche Freigabe des Betreibers.

1. **Server** (💶 geplant Hetzner CX33; aktuellen Preis vor der Bestellung prüfen) und **Domain** mit DNS auf den Server. Noch nicht bestellt.
2. Erstinstallation nach [OPERATIONS.md](OPERATIONS.md) Abschnitt 1: Härtung, Docker, `.env` mit allen Pflichtwerten, `deploy.sh`, Admin anlegen, Uptime Kuma.
3. **Zwei-Faktor-Anmeldung** für alle Admins (Plan Phase B), bevor echte Kanäle verbunden werden.
4. **Externes Backup** (💶 Cloudflare R2, voraussichtlich 0 € bis < 1 €/Monat) nach Freigabe.
5. **Gültige Zugangsdaten** für Trendquellen (YouTube-Schlüssel neu, Twitch prüfen), danach `TREND_SOURCES_MODE=live`.
6. **OAuth-Apps** je Plattform beim Anbieter anlegen (Google, TikTok, Meta) und die Kanäle im Dashboard verbinden.
7. **Echte Lizenzen** für das verwendete Gameplay hinterlegen.
8. **Entscheidung TikTok** (Entwurf-Upload, halbautomatisch oder Drittanbieter).
9. Optional (💶): Sprachmodell- und Stimmen-Anbieter freigeben.
10. Erst dann, je Kanal einzeln: `PUBLISHING_MODE=live`, Kanal entpausieren, Testveröffentlichung **privat** prüfen, danach `AUTO_PUBLISH_ENABLED=true` nur für freigegebene Kanäle.
