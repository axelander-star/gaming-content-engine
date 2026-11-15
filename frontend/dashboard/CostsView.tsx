"use client";

import { useEffect, useState } from "react";

import { Badge, ErrorText, PageHeader, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import type { CostSummary } from "@/lib/types";

import { AIUsagePanel } from "./AIUsagePanel";
import { BarList } from "./charts";

const eur = (v: number | null | undefined, digits = 2) =>
  v == null
    ? "–"
    : v.toLocaleString("de-DE", {
        style: "currency",
        currency: "EUR",
        maximumFractionDigits: digits,
      });

const LEVELS: Record<string, [string, "ok" | "warn" | "danger" | "neutral"]> = {
  normal: ["Normal", "ok"],
  warn: ["Warnung", "warn"],
  reduced: ["Kostenreduziert", "warn"],
  priority_only: ["Nur priorisierte Aufgaben", "danger"],
  stop_paid: ["Kostenpflichtiges gestoppt", "danger"],
};

const COST_LABELS: [keyof CostSummary["costs"], string][] = [
  ["server", "Server"],
  ["other_fixed", "Weitere Fixkosten (Backups, Domain)"],
  ["storage", "Speicher"],
  ["ai", "KI"],
  ["tts", "Sprachausgabe"],
  ["api", "API-Dienste"],
  ["other", "Sonstiges"],
];

function bytes(n: number): string {
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function CostsView() {
  const [data, setData] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .costSummary()
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);
  const b = data?.budget;
  const level = b ? (LEVELS[b.level] ?? [b.level, "neutral"]) : null;
  return (
    <>
      <PageHeader
        title="Kosten"
        description="Server-, KI-, Speicher- und API-Kosten im laufenden Monat."
      />
      <ErrorText error={error} />
      <div className="grid stats">
        <StatCard label="Monatliche Gesamtkosten" value={eur(data?.costs.total)} />
        <StatCard
          label="Budget"
          value={b ? `${b.used_pct.toLocaleString("de-DE")} % von ${eur(b.budget_eur, 0)}` : "–"}
        />
        <StatCard label="Pro produziertem Video" value={eur(data?.unit_costs.per_produced, 3)} />
        <StatCard
          label="Pro veröffentlichtem Video"
          value={eur(data?.unit_costs.per_published, 3)}
        />
        <StatCard label="Pro 1.000 Aufrufe" value={eur(data?.unit_costs.per_1000_views, 3)} />
      </div>
      {level && b && (
        <p role="status">
          Budgetstufe: <Badge tone={level[1]}>{level[0]}</Badge>{" "}
          <span className="muted">
            Warnung ab {b.thresholds.warn} %, kostenreduziert ab {b.thresholds.reduced} %, nur
            priorisierte Aufgaben ab {b.thresholds.priority_only} %, kostenpflichtige Aufgaben
            gestoppt ab {b.thresholds.stop_paid} %. Fixkosten zählen von Monatsbeginn an voll.
          </span>
        </p>
      )}
      {data && !data.prices_configured && (
        <p className="muted">
          Für Server und Speicher sind noch keine Preise eingetragen (SERVER_MONTHLY_EUR,
          OTHER_FIXED_MONTHLY_EUR, STORAGE_EUR_PER_GB_MONTH). Sie werden erst nach Prüfung der
          aktuellen Anbieterpreise gesetzt; bis dahin zählen sie mit 0 €.
        </p>
      )}
      <AIUsagePanel />
      <Section title="Kosten nach Bereich">
        <BarList
          title="Kosten im Monat"
          rows={COST_LABELS.map(([k, label]) => ({ label, value: data?.costs[k] ?? 0 }))}
          format={(v) => eur(v)}
        />
      </Section>
      <Section title="Videos, Speicher und API-Nutzung">
        <div className="table-wrap">
          <table aria-label="Mengen">
            <tbody>
              <tr>
                <td>Produziert (Qualität bestanden)</td>
                <td>{data?.videos.produced ?? "–"}</td>
              </tr>
              <tr>
                <td>Veröffentlicht (echt)</td>
                <td>{data?.videos.published ?? "–"}</td>
              </tr>
              <tr>
                <td>Testveröffentlichungen (Mock, zählen nicht pro Video)</td>
                <td>{data?.videos.published_test ?? "–"}</td>
              </tr>
              <tr>
                <td>Aufrufe echter Posts</td>
                <td>{data?.videos.views.toLocaleString("de-DE") ?? "–"}</td>
              </tr>
              <tr>
                <td>Speicher (Medienordner)</td>
                <td>{data ? bytes(data.storage.bytes) : "–"}</td>
              </tr>
              {Object.entries(data?.api_usage_today ?? {}).map(([k, v]) => (
                <tr key={k}>
                  <td>API heute: {k}</td>
                  <td>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
