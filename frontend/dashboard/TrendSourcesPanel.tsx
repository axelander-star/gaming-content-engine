"use client";

import { useEffect, useState } from "react";

import { Badge, ErrorText, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import type { TrendSourceStatus } from "@/lib/types";

type Tone = "ok" | "warn" | "danger" | "neutral";
const STATE: Record<string, [Tone, string]> = {
  ok: ["ok", "Verbunden"],
  partial: ["warn", "Teilweise"],
  error: ["danger", "Fehler"],
  skipped: ["neutral", "Nicht gelaufen"],
  mock: ["neutral", "Testdaten, keine Verbindung"],
};

/** Connection status of YouTube, Twitch and Steam; admins can run a connection test. */
export function TrendSourcesPanel({ canTest }: { canTest: boolean }) {
  const [rows, setRows] = useState<TrendSourceStatus[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .trendSources()
      .then(setRows)
      .catch((e: Error) => setError(e.message));
  }, []);

  async function test(name: TrendSourceStatus["name"]) {
    setBusy(name);
    setError(null);
    try {
      const updated = await api.testTrendSource(name);
      setRows((all) => all.map((r) => (r.name === name ? updated : r)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const mode = rows[0]?.mode;
  return (
    <Section title="Trendquellen">
      <p className="muted small">
        Modus:{" "}
        {mode === "live" ? (
          <Badge tone="ok">Live</Badge>
        ) : (
          <Badge tone="warn">Testdaten (Mock)</Badge>
        )}{" "}
        Zugangsdaten werden nur als Umgebungsvariablen gelesen und hier nie angezeigt. Ein
        Verbindungstest macht genau eine lesende Anfrage und zählt gegen die Tagesquote.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Quelle</th>
              <th>Zugangsdaten</th>
              <th>Status</th>
              <th>Quote heute</th>
              <th>Letzter Lauf / Test</th>
              {canTest && <th />}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const last = r.last;
              const [tone, label]: [Tone, string] = last
                ? (STATE[last.state] ?? ["neutral", last.state])
                : ["neutral", "Noch nie gelaufen"];
              return (
                <tr key={r.name}>
                  <td>{r.label}</td>
                  <td className="small">
                    {r.credentials.length === 0 ? (
                      <span className="muted">nicht nötig</span>
                    ) : r.configured ? (
                      <Badge tone="ok">hinterlegt</Badge>
                    ) : (
                      <>
                        <Badge tone="warn">fehlt</Badge>{" "}
                        <span className="mono">{r.credentials.join(", ")}</span>
                      </>
                    )}
                  </td>
                  <td>
                    <Badge tone={tone}>{label}</Badge>
                    {last?.detail && <div className="small">{last.detail}</div>}
                    {last?.errors.map((e) => (
                      <div key={e} className="small error-inline">
                        {e}
                      </div>
                    ))}
                    {last?.skipped && <div className="muted small">{last.skipped}</div>}
                  </td>
                  <td className="small">
                    {r.quota_used} / {r.quota_limit} {r.quota_unit}
                  </td>
                  <td className="small">
                    {last ? (
                      <>
                        {formatDateTime(last.at)} · {last.kind === "test" ? "Test" : "Lauf"} (
                        {last.mode === "live" ? "live" : "Testdaten"})
                        {last.state !== "ok" && last.last_ok_at && (
                          <div className="muted">
                            Zuletzt erfolgreich {formatDateTime(last.last_ok_at)}
                          </div>
                        )}
                      </>
                    ) : (
                      "–"
                    )}
                  </td>
                  {canTest && (
                    <td>
                      <button
                        type="button"
                        className="btn"
                        disabled={busy !== null || !r.configured}
                        onClick={() => void test(r.name)}
                      >
                        {busy === r.name ? "Teste …" : "Verbindung testen"}
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ErrorText error={error} />
    </Section>
  );
}
