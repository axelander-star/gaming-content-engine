# Clipping-Kampagnen (Content Rewards)

Stand: 16.11.2026 · Dashboard-Seite **Kampagnen** (`/kampagnen`) · Backend `services/campaigns.py`, `api/campaigns.py`

## Worum es geht

Auf [Content Rewards](https://contentrewards.com) (gehört zu Whop) bezahlen Streamer und Marken pro 1.000 geprüfte Aufrufe, wenn Clips aus ihrem Material auf eigenen Kanälen laufen. Für die Engine ist das eine **lizenzierte Materialquelle**: Der Kampagnen-Inhaber stellt das Material bereit und erlaubt, daraus Clips zu schneiden. Die Erlaubnis gilt **nur für diese Kampagne**.

## Ablauf

1. **Kampagne anlegen** (Seite Kampagnen, „Neue Kampagne“): Werte aus der Kampagnenbeschreibung übernehmen, also Seite, Vergütung je 1.000 Aufrufe, Budget, Plattformen, Sprachen, Pflicht-Hashtags, Werbehinweis, Pflichttext (Credit, @Erwähnung), Clip-Länge, Enddatum, Materiallinks und die Regeln als Text. Dazu die Kanäle ankreuzen, die bei Content Rewards verbunden sind. Ohne die Bestätigung „Regeln gelesen“ lässt sich keine Kampagne anlegen.
2. Daraus entstehen automatisch eine **Quelle vom Typ `campaign`** und eine **freigegebene Lizenz**, die nur die gewählten Plattformen und Sprachen und nur die Laufzeit bis zum Enddatum abdeckt. Nachweis ist die Kampagnenseite, geprüft von der Person, die die Kampagne angelegt hat. Die Publisher-Richtlinie des Spiels wird weiter geprüft (das Spiel wird beim Anlegen oder Hochladen gewählt).
3. **Material hochladen** (Knopf in der Kampagnenkarte, fortsetzbarer Upload). Die Engine schneidet es wie jedes Gameplay: Szenen finden, Clips rendern, Konzept, Skript, Lokalisierung, Stimme, Untertitel. Clips entstehen **nur für die Kampagnenkanäle**, nicht für die übrigen Kanäle des Themenbereichs.
4. Die **Qualitätskontrolle** setzt den Werbehinweis an den Anfang der Beschreibung, fügt Pflichttext und Pflicht-Hashtags hinzu und prüft zusätzlich: Kampagne aktiv, Kanal zählt in der Kampagne, Länge im erlaubten Bereich, Pflichtangaben im Text. Alles davon ist blockierend.
5. Kampagnen-Clips gehen danach **nicht automatisch** in die Veröffentlichung, sondern warten unter „Clips zur Freigabe“. Texte lassen sich ändern; Werbehinweis und Pflicht-Hashtags werden dabei wieder eingesetzt. **Freigeben** stellt YouTube-Videos auf „öffentlich“ (nur öffentliche Videos zählen); wann der Clip erscheint, entscheidet wie immer der Strategie-Agent je Kanal.
6. Sobald der Clip veröffentlicht ist, erscheint er unter **„Jetzt einreichen“** mit Link, Countdown (Standard 30 Minuten ab Veröffentlichung, je Kampagne einstellbar), „Link kopieren“ und „Kampagnenseite öffnen“. Zusätzlich gibt es eine Benachrichtigung.
7. Link auf der Kampagnenseite einreichen und hier **„Eingereicht ✓“** drücken. Der Eintrag wandert nach „Erledigt“ (verspätete Einreichungen werden markiert). „Nicht einreichen“ und „Rückgängig“ gibt es auch.

Hat ein Beitrag noch keinen öffentlichen Link (TikTok-Entwurf in der App, Testbetrieb), steht dort „Link fehlt“ und ein Eingabefeld. Nach dem Eintragen startet die Frist ab diesem Moment, weil der Beitrag gerade erst öffentlich wurde.

## Warum die Einreichung von Hand bleibt

- Für Clipper gibt es **keine offizielle Schnittstelle** zu Content-Rewards-Kampagnen. Die Whop-API kennt „Bounties“ (`POST /bounty_submissions` mit Benutzer-Zugang), es ist aber nicht belegt, dass Content-Rewards-Kampagnen darüber laufen.
- Formulare automatisch ausfüllen oder Seiten auslesen widerspricht den [Whop-API-Bedingungen](https://whop.com/tos-developer-api/) und gefährdet das Konto.
- Es zählen nur Konten, die in Content Rewards verbunden und bestätigt sind; bei Instagram nur Business-Konten.

## Kampagnenstatus

| Status | Wirkung |
|---|---|
| Aktiv | Material wird geschnitten, Clips werden geprüft und nach Freigabe veröffentlicht. |
| Pausiert | Die Rechteprüfung des Kampagnenmaterials schlägt fehl („Kampagne ist pausiert“): keine neuen Clips, keine Veröffentlichung. Offene Einreichungen bleiben. |
| Beendet | Wie pausiert, z. B. wenn das Budget aufgebraucht ist. |

Das Enddatum wirkt über die Lizenz: Nach Ablauf meldet die Rechteprüfung „Abgelaufen“.

## Ertrag (Richtwerte, Stand November 2026)

- Gaming-Kampagnen zahlen im Mittel etwa 1,40 $ je 1.000 Aufrufe ([Content-Rewards-Daten](https://contentrewards.com/articles/clipping-cpm-rates-november-2026), 28 Kampagnen); Content Rewards behält 10 % ein, Auszahlung nach etwa 10 Tagen.
- `services.campaigns.estimated_payout` rechnet Aufrufe in einen geschätzten Betrag um (Mindestaufrufe, Obergrenze je Clip, 10 % Gebühr). Eine Anzeige im Dashboard und die Berücksichtigung im Strategie-Agenten folgen, sobald echte Aufrufzahlen vorliegen.

## Sicherheit

- Nichts wird automatisch eingereicht und kein Konto bei Content Rewards oder Whop angelegt.
- `PUBLISHING_MODE=mock` bleibt Standard: Im Testbetrieb entstehen Testbeiträge ohne Link.
- Bezahlte Clips brauchen die Werbekennzeichnung; TikTok verlangt zusätzlich die KI-Kennzeichnung bei KI-Stimme (setzt der TikTok-Adapter automatisch).

## Offene Punkte

- Aufrufzahlen je Kampagnen-Clip und geschätzter Ertrag im Dashboard (sobald Analytics echte Werte liefert).
- Strategie-Agent: lohnende Kampagnen bevorzugen, Restbudget berücksichtigen.
- Videos aus der Mediathek gehören bisher keiner Kampagne an; Kampagnenmaterial läuft über den Upload in der Kampagnenkarte.
