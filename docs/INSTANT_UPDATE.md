# Sofort-Update nach einem Merge (seit 27.11.2026)

Bisher hat der Server alle 5 Minuten nachgesehen, ob es auf `main` etwas Neues gibt. Jetzt meldet GitHub jeden Merge sofort, und der Server startet das Update innerhalb weniger Sekunden. Die Prüfung alle 5 Minuten bleibt als Rückfall, falls eine Meldung verloren geht.

## Ablauf

```
GitHub (Push auf main)
  -> https://update.<domain>/github        (eigener Tunnel-Hostname, ohne Access)
  -> Caddy :8083                           (leitet nur POST /github weiter)
  -> Backend POST /api/hooks/github        (prüft die HMAC-Signatur)
  -> Datei infrastructure/deploy-hook/trigger
  -> scripts/auto_update_watch.sh          (Cron jede Minute, schaut alle 2 s nach)
  -> scripts/auto_update.sh -> deploy.sh   (wie bisher: Sicherung, Bauen, Prüfung, Rücksprung)
```

- Das Backend prüft die Signatur `X-Hub-Signature-256` (HMAC-SHA256 über den Rohinhalt mit dem gemeinsamen Geheimnis). Ohne gültige Signatur passiert nichts (401). Nur `push` auf `main` löst etwas aus; `ping` bestätigt die Verbindung, alles andere wird ignoriert. Anfragen über 1 MB werden abgelehnt.
- Das Backend selbst spielt nichts ein. Es hat keinen Docker-Zugang und führt keine Befehle aus, es legt nur die Datei `trigger` ab. Eingespielt wird weiter nur `origin/main`, das die CI bestanden hat, also auch ein gefälschter Aufruf könnte höchstens ein ohnehin geplantes Update etwas früher starten.
- Der Wächter ist kein Dauerprozess: Cron startet ihn jede Minute, er läuft knapp eine Minute und es läuft immer nur einer. Läuft gerade ein Update aus der 5-Minuten-Prüfung, wartet er darauf und prüft danach erneut.
- Dateien in `infrastructure/deploy-hook/` (nicht im Git): `secret` (Webhook-Geheimnis, vom Server erzeugt), `trigger`, `last-hook`, `watcher` (Lebenszeichen), `last-update` (Ergebnis des letzten Updates). Der Ordner ist ins Backend eingebunden (`/data/deploy-hook`).

## Einrichtung

**Auf dem Server ist nichts zu tun.** Das laufende automatische Update spielt diese Version ein. Beim nächsten Durchlauf legt `auto_update.sh` das Geheimnis an und trägt den Wächter in die Crontab ein. Wer das Update von Hand einschaltet, nimmt wie bisher `./scripts/install_auto_update.sh`; `--off` schaltet beides aus.

Danach zwei Schritte im Browser:

1. **Cloudflare Zero Trust** → Networks → Tunnels → `kanalfabrik-server` → Public Hostname hinzufügen: Subdomain `update`, Domain `kanalfabrik.de`, Typ `HTTP`, URL `caddy:8083`. **Keine** Access-Anwendung für diesen Hostnamen anlegen (GitHub kann sich nicht anmelden; geschützt ist er durch die Signatur).
2. **GitHub** → Repository → Settings → Webhooks → Add webhook:
   - Payload URL: `https://update.kanalfabrik.de/github`
   - Content type: `application/json`
   - Secret: im Studio unter **System → Sofort-Update nach einem Merge** kopieren
   - Which events: „Just the push event“, Active angehakt

GitHub schickt dann sofort ein `ping`. Im Studio steht danach „Aktiv“ und unter „Letzte Meldung von GitHub“ die Uhrzeit.

## Fehlersuche

- GitHub zeigt unter Webhooks → Recent Deliveries jede Zustellung mit Antwort. `503` heißt: Geheimnis auf dem Server fehlt noch (5 Minuten warten). `401`: Geheimnis in GitHub stimmt nicht mit dem im Studio überein. `403` mit Cloudflare-Seite: für `update.` ist doch eine Access-Anwendung aktiv, oder „Bot Fight Mode“ blockiert GitHub.
- Protokoll auf dem Server: `./scripts/install_auto_update.sh --log`.
