# Uploads in Teilstücken (fortsetzbar)

Cloudflare lässt im kostenlosen Tarif höchstens 100 MB je Anfrage durch. Große Dateien (Gameplay bis 4 GB) gehen deshalb in Teilstücken hoch. Bricht die Verbindung ab, wird der Browser neu geladen oder der Tab geschlossen, geht der Upload an der letzten bestätigten Stelle weiter.

Code: `backend/services/uploads.py` (Protokoll, Verbraucher), `backend/api/uploads.py` (Endpunkte), `frontend/lib/upload.ts` (Client), Tests in `backend/tests/integration/test_uploads.py`.

## Ablauf

| Schritt | Anfrage | Antwort |
|---|---|---|
| 1. Starten | `POST /api/uploads` mit `purpose`, `filename`, `size_bytes`, `content_type`, `params`, optional `sha256` | `201` mit `id`, `chunk_bytes`, `received_bytes = 0`. Die `params` werden **vor** dem ersten Byte geprüft (z. B. Lizenz und Spiel). |
| 2. Teil senden | `PATCH /api/uploads/{id}`, Rohdaten, Header `Upload-Offset: <received_bytes>`, optional `X-Chunk-Sha256` | `200` mit neuem `received_bytes`. Falscher Offset: `409` mit dem erwarteten Offset im Header `Upload-Offset`. |
| 3. Stand abfragen | `GET /api/uploads/{id}` | `received_bytes` ist die Stelle, an der es weitergeht. |
| 4. Abschließen | `POST /api/uploads/{id}/complete` | Prüft Größe und (falls angegeben) SHA-256, übergibt die Datei an den Verbraucher. `status` ist danach `COMPLETED` (Ergebnis in `result`) oder `FAILED` (`error_message`). Mehrfach aufrufbar. |
| Abbrechen | `DELETE /api/uploads/{id}` | Teildatei wird gelöscht, Status `CANCELLED`. |

Alle Endpunkte verlangen die Rolle Operator und das CSRF-Token; eine Sitzung gehört genau einem Benutzer (fremde Sitzungen antworten `404`).

## Verhalten bei Störungen

- **Antwort verloren:** Der Client sendet denselben Teil erneut, bekommt `409` mit dem richtigen Offset und macht dort weiter. Nichts wird doppelt geschrieben.
- **Absturz zwischen Schreiben und Speichern:** Jeder Teil wird an seinen Offset geschrieben und die Datei dahinter abgeschnitten; ein nicht bestätigter Rest wird beim nächsten Teil überschrieben.
- **Gleichzeitige Anfragen:** Die Sitzungszeile wird während eines Teils oder des Abschlusses gesperrt (`SELECT … FOR UPDATE`).
- **Lange Prüfung beim Abschluss:** Cloudflare beendet Anfragen nach 100 s. Der Client ruft `complete` dann einfach erneut auf und erhält das Ergebnis.
- **Verwaiste Uploads:** Sitzungen verfallen nach `UPLOAD_SESSION_TTL_HOURS` (Standard 24 h) ohne Aktivität. Der Monitor-Lauf des Schedulers setzt sie auf `CANCELLED` und löscht Teildateien, auch Dateien ohne Sitzung, die älter als eine Stunde sind.
- **Fehlerhafte Datei:** Schlägt die Prüfung des Verbrauchers fehl, endet die Sitzung mit `FAILED`; angelegte Datensätze werden über einen Savepoint zurückgerollt und die Teildatei gelöscht.

## Einstellungen

| Variable | Standard | Bedeutung |
|---|---|---|
| `UPLOAD_CHUNK_BYTES` | 16 MiB (256 KiB bis 64 MiB) | Größe eines Teils; bleibt deutlich unter der 100-MB-Grenze |
| `UPLOAD_SESSION_TTL_HOURS` | 24 | Verfallszeit ohne Aktivität |
| `MAX_UPLOAD_BYTES` | wie bisher | Obergrenze der gesamten Datei (je Verbraucher änderbar) |

Teildateien liegen unter `MEDIA_ROOT/tmp/uploads/<id>.part`.

## Dashboard

`resumableUpload(file, { purpose, params, onProgress, signal })` aus `frontend/lib/upload.ts` erledigt alles: Sitzung anlegen oder wiederfinden (die Sitzungs-ID wird je Datei aus Name, Größe und Änderungszeit im `localStorage` gemerkt), Teile senden, bei Netzwerkfehlern und 5xx mit wachsender Wartezeit erneut versuchen, danach abschließen. Der Bereich „Gameplay hochladen“ unter Videoproduktion zeigt den Fortschritt und kann den Upload anhalten; wird dieselbe Datei erneut gewählt, geht es an derselben Stelle weiter.

## Neue Verbraucher anschließen

Ein Verbraucher entscheidet, was mit der fertigen Datei passiert (heute `material`: lizenziertes Gameplay registrieren, `api/rights.py`). Weitere, etwa eine Medienbibliothek, werden genauso angeschlossen:

```python
uploads.register_consumer(
    "media_library",
    uploads.Consumer(
        allowed_types={"video/mp4": ".mp4", "image/png": ".png"},
        validate=lambda db, settings, user_id, params: {...},   # vor dem Upload, gibt bereinigte params zurück
        accept=lambda db, settings, session, path: {...},       # nach dem Upload, darf die Datei verschieben
        max_bytes=lambda settings: settings.max_upload_bytes,   # optional
    ),
)
```

`validate` und `accept` lösen bei Problemen `uploads.UploadError(status, detail)` aus. `accept` läuft in einem Savepoint; sein Rückgabewert landet als JSON in `result`.

Der bisherige Upload in einem Stück (`POST /api/materials/upload`) bleibt für kleine Dateien und Skripte erhalten.
