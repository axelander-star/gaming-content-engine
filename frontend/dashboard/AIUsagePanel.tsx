"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import type { AICallStatus, AIStatus, AITestResult, AIUsage } from "@/lib/types";

const usd = (v: string | number, digits = 2) =>
  Number(v).toLocaleString("de-DE", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: Math.max(digits, 4),
  });

const STATUS: Record<AICallStatus, [string, "ok" | "warn" | "danger" | "neutral"]> = {
  reserved: ["Läuft", "warn"],
  succeeded: ["Erfolgreich", "ok"],
  refused: ["Abgelehnt", "warn"],
  failed: ["Fehler", "danger"],
  blocked: ["Blockiert", "neutral"],
};

const PURPOSES: Record<string, string> = {
  test: "Testaufruf",
  chat: "Chat",
  ideas: "Ideen",
  planning: "Planung",
  title: "Titel",
  description: "Beschreibung",
  hook: "Hook",
};

/** Claude usage against the hard monthly cap (extension E3). */
export function AIUsagePanel({ tick = 0 }: { tick?: number } = {}) {
  const { user } = useAuth();
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [usage, setUsage] = useState<AIUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("Schlage einen kurzen Videotitel über Meal Prep vor.");
  const [tier, setTier] = useState<"text" | "reasoning">("text");
  const [result, setResult] = useState<AITestResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.aiStatus().then(setStatus).catch((e: Error) => setError(e.message));
    api.aiUsage().then(setUsage).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load, tick]);

  async function onTest(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.aiTest(prompt, tier));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      load();
    }
  }

  const pct = status ? Math.min(100, status.used_pct) : 0;
  return (
    <Section title="KI-Nutzung (Claude)">
      {status && (
        <>
          <div className="ai-head">
            <Badge tone={status.live ? "warn" : "neutral"}>
              {status.live ? "Live: echte Aufrufe" : "Test (Mock): keine Kosten"}
            </Badge>
            {status.reason && <span className="muted small">{status.reason}</span>}
          </div>
          <div className="ai-cap">
            <div className="ai-cap-row">
              <span>
                <strong>{usd(Number(status.spent_usd) + Number(status.reserved_usd))}</strong>{" "}
                <span className="muted">von {usd(status.cap_usd)} API-Monatsgrenze der Engine</span>
              </span>
              <span className="muted small">noch {usd(status.remaining_usd)}</span>
            </div>
            <div
              className="meter"
              role="meter"
              aria-label="Verbrauch der KI-Monatsgrenze"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct}
            >
              <span
                style={{ width: `${pct}%` }}
                className={pct >= 90 ? "meter-danger" : pct >= 70 ? "meter-warn" : undefined}
              />
            </div>
          </div>
          <dl className="kv">
            <dt>Kurze Texte</dt>
            <dd>
              {status.model_text}{" "}
              <span className="muted small">
                ({usd(status.prices[status.model_text]?.input ?? 0)} /{" "}
                {usd(status.prices[status.model_text]?.output ?? 0)} je 1 Mio. Tokens)
              </span>
            </dd>
            <dt>Chat, Ideen, Planung</dt>
            <dd>
              {status.model_reasoning}{" "}
              <span className="muted small">
                ({usd(status.prices[status.model_reasoning]?.input ?? 0)} /{" "}
                {usd(status.prices[status.model_reasoning]?.output ?? 0)} je 1 Mio. Tokens)
              </span>
            </dd>
            <dt>API-Schlüssel</dt>
            <dd>
              <Badge tone={status.key_configured ? "ok" : "neutral"}>
                {status.key_configured ? "hinterlegt" : "fehlt"}
              </Badge>
            </dd>
            <dt>Kostenpflichtige Aufrufe</dt>
            <dd>
              <Badge tone={status.paid_calls_enabled ? "warn" : "neutral"}>
                {status.paid_calls_enabled ? "freigegeben" : "gesperrt"}
              </Badge>
            </dd>
            <dt>Aufrufe diesen Monat</dt>
            <dd>
              {status.calls_this_month}
              {status.blocked_this_month > 0 && ` (davon ${status.blocked_this_month} blockiert)`}
            </dd>
          </dl>
          <p className="muted small">
            Vor jedem echten Aufruf wird der ungünstigste Preis reserviert. Passt er nicht mehr unter
            die Grenze, wird der Aufruf nicht gesendet. Die Grenze lässt sich unter Einstellungen
            senken, aber nie über {usd(status.cap_max_usd)} heben.
          </p>
        </>
      )}

      {usage && usage.by_purpose.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Zweck</th>
                <th>Aufrufe</th>
                <th>Tokens (ein / aus)</th>
                <th>Kosten</th>
              </tr>
            </thead>
            <tbody>
              {usage.by_purpose.map((g) => (
                <tr key={g.key}>
                  <td>{PURPOSES[g.key] ?? g.key}</td>
                  <td>{g.calls}</td>
                  <td>
                    {g.input_tokens.toLocaleString("de-DE")} /{" "}
                    {g.output_tokens.toLocaleString("de-DE")}
                  </td>
                  <td>{usd(g.cost_usd, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {usage && usage.recent.length > 0 && (
        <details>
          <summary>Letzte Aufrufe</summary>
          <ul className="feed">
            {usage.recent.map((c) => (
              <li key={c.id}>
                <div className="feed-body">
                  <div className="feed-title">
                    {PURPOSES[c.purpose] ?? c.purpose} · {c.model}
                    {c.provider === "mock" ? " · Test" : ""}
                  </div>
                  <div className="muted small">
                    {formatDateTime(c.created_at)} · {c.input_tokens} / {c.output_tokens} Tokens ·{" "}
                    {usd(c.cost_usd, 4)}
                    {c.content_project ? ` · ${c.content_project}` : ""}
                  </div>
                  {c.error && <div className="feed-error small">{c.error}</div>}
                </div>
                <Badge tone={STATUS[c.status][1]}>{STATUS[c.status][0]}</Badge>
              </li>
            ))}
          </ul>
        </details>
      )}

      {user?.role === "admin" && (
        <form className="inline-form" onSubmit={onTest} aria-label="KI testen">
          <input
            aria-label="Testfrage"
            value={prompt}
            maxLength={2000}
            onChange={(e) => setPrompt(e.target.value)}
            style={{ flex: "1 1 260px" }}
          />
          <select
            aria-label="Modellstufe"
            value={tier}
            onChange={(e) => setTier(e.target.value as "text" | "reasoning")}
          >
            <option value="text">Kurzer Text</option>
            <option value="reasoning">Chat / Planung</option>
          </select>
          <button className="btn btn-ghost" type="submit" disabled={busy || !prompt.trim()}>
            KI testen
          </button>
        </form>
      )}
      {result && (
        <div className="ai-result">
          <div className="muted small">
            {result.provider === "mock" ? "Testantwort (Mock)" : result.model} ·{" "}
            {usd(result.cost_usd, 4)}
          </div>
          <p>{result.text}</p>
        </div>
      )}
      <ErrorText error={error} />
    </Section>
  );
}
