# Dashboard

Next.js 16 (App Router), React 19 und TypeScript (strict). Spricht ausschließlich mit der Backend-API unter `/api` (gleiche Origin).

## Aufbau

| Ordner | Inhalt |
|---|---|
| `app/` | Routen: `login/` und die Gruppe `(dashboard)/` mit Übersicht, Agenten, Videoproduktion, Publishing, Analytics, Kosten, Einstellungen |
| `components/` | `AuthProvider` (Sitzung), `AppShell` (Navigation, Not-Aus-Banner), UI-Bausteine |
| `dashboard/` | Seiteninhalte mit Logik (Übersicht, Steuerung, Betrieb, Kanäle, Benutzer) |
| `lib/` | API-Client mit CSRF-Header, Typen, Rollen- und Beschriftungs-Helfer |
| `e2e/` | End-to-End-Smoke-Test (Playwright) |

## Lokal starten

```bash
npm ci
BACKEND_URL=http://127.0.0.1:8000 npm run dev      # Backend muss laufen
```

Für lokale Entwicklung über HTTP muss das Backend mit `SESSION_COOKIE_SECURE=false` laufen.

## Prüfen

```bash
npm run typecheck
npm run build
E2E_PASSWORD=<admin-passwort> npm run e2e           # Dashboard auf :3000, Admin admin@example.com
```

## Sicherheit

- Die Sitzung liegt in einem HttpOnly-Cookie; das Dashboard sieht kein Token.
- Schreibende Anfragen senden den Wert des Cookies `gce_csrf` als Header `X-CSRF-Token`.
- Rollenprüfungen im Dashboard dienen nur der Anzeige. Durchgesetzt werden sie im Backend.
