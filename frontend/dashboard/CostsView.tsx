"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Icon } from "@/components/icons";
import { Badge, ErrorText, PageHeader, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import { hasRole } from "@/lib/roles";
import type {
  AIUsageWindow,
  CostSummary,
  FixedCost,
  FixedCostCategory,
  FixedCostInput,
} from "@/lib/types";

import { AIUsagePanel } from "./AIUsagePanel";
import { BarList } from "./charts";

/** How often the page reloads its numbers while visible. */
const REFRESH_MS = 15_000;

const eur = (v: number | null | undefined, digits = 2) =>
  v == null
    ? "–"
    : v.toLocaleString("de-DE", {
        style: "currency",
        currency: "EUR",
        minimumFractionDigits: Math.min(2, digits),
        maximumFractionDigits: digits,
      });

const usd = (v: number) =>
  v.toLocaleString("de-DE", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });

const num = (v: number) => v.toLocaleString("de-DE");

const time = (d: Date) =>
  d.toLocaleTimeString("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

const LEVELS: Record<string, [string, "ok" | "warn" | "danger" | "neutral"]> = {
  normal: ["Normal", "ok"],
  warn: ["Warnung", "warn"],
  reduced: ["Kostenreduziert", "warn"],
  priority_only: ["Nur priorisierte Aufgaben", "danger"],
  stop_paid: ["Kostenpflichtiges gestoppt", "danger"],
};

const CATEGORIES: Record<FixedCostCategory, string> = {
  server: "Server",
  domain: "Domain",
  subscription: "Abo",
  storage: "Speicher",
  backup: "Backup",
  other: "Sonstiges",
};

const COST_LABELS: [keyof CostSummary["costs"], string][] = [
  ["fixed", "Fixkosten (Server, Domain, Abos)"],
  ["storage", "Speicher (Medienordner)"],
  ["ai", "KI-API"],
  ["tts", "Sprachausgabe"],
  ["api", "API-Dienste"],
  ["other", "Sonstiges"],
];

function bytes(n: number): string {
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

const EMPTY: FixedCostInput = {
  name: "",
  provider: "",
  category: "server",
  amount: "",
  currency: "EUR",
  interval: "month",
  in_budget: true,
  is_active: true,
  note: "",
};

function toInput(item: FixedCost): FixedCostInput {
  return {
    name: item.name,
    provider: item.provider ?? "",
    category: item.category,
    amount: item.amount.toFixed(2).replace(".", ","),
    currency: item.currency,
    interval: item.interval,
    in_budget: item.in_budget,
    is_active: item.is_active,
    note: item.note ?? "",
  };
}

function FixedCostForm({
  initial,
  onSave,
  onCancel,
  label,
}: {
  initial: FixedCostInput;
  onSave: (data: FixedCostInput) => Promise<void>;
  onCancel?: () => void;
  label: string;
}) {
  const [form, setForm] = useState<FixedCostInput>(initial);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof FixedCostInput>(k: K, v: FixedCostInput[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    try {
      await onSave({
        ...form,
        amount: form.amount.replace(/\./g, "").replace(",", ".") || "0",
        provider: form.provider?.trim() || null,
        note: form.note?.trim() || null,
      });
      if (!onCancel) setForm(EMPTY);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="acc-rev-form fixed-form" onSubmit={submit} aria-label={label}>
      <label>
        Name
        <input
          required
          maxLength={120}
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          placeholder="z. B. Server"
        />
      </label>
      <label>
        Anbieter
        <input
          maxLength={80}
          value={form.provider ?? ""}
          onChange={(e) => set("provider", e.target.value)}
          placeholder="z. B. Contabo"
        />
      </label>
      <label>
        Art
        <select
          value={form.category}
          onChange={(e) => set("category", e.target.value as FixedCostCategory)}
        >
          {Object.entries(CATEGORIES).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label>
        Betrag
        <input
          inputMode="decimal"
          required
          pattern="[0-9]+([,.][0-9]{1,2})?"
          value={form.amount}
          onChange={(e) => set("amount", e.target.value)}
          placeholder="0,00"
        />
      </label>
      <label>
        Währung
        <select
          value={form.currency}
          onChange={(e) => set("currency", e.target.value as "EUR" | "USD")}
        >
          <option value="EUR">€</option>
          <option value="USD">$</option>
        </select>
      </label>
      <label>
        Zahlweise
        <select
          value={form.interval}
          onChange={(e) => set("interval", e.target.value as "month" | "year")}
        >
          <option value="month">monatlich</option>
          <option value="year">jährlich</option>
        </select>
      </label>
      <label>
        Notiz
        <input
          maxLength={300}
          value={form.note ?? ""}
          onChange={(e) => set("note", e.target.value)}
        />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={form.in_budget}
          onChange={(e) => set("in_budget", e.target.checked)}
        />
        zählt zum Engine-Budget
      </label>
      <button className="btn btn-primary" disabled={busy}>
        Speichern
      </button>
      {onCancel && (
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Abbrechen
        </button>
      )}
    </form>
  );
}

function FixedCostsSection({
  data,
  canEdit,
  reload,
}: {
  data: CostSummary;
  canEdit: boolean;
  reload: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const items = data.fixed.items;

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await reload();
    } catch (e) {
      setError((e as Error).message);
      throw e;
    }
  }

  return (
    <Section title="Fixkosten">
      <p className="muted small">
        Laufende Posten wie Server, Domain und Abos. Jahresbeträge werden auf den Monat umgerechnet,
        Dollar mit {data.ai.eur_per_usd.toLocaleString("de-DE")} € je $. Posten mit „zählt zum
        Engine-Budget“ bremsen bei Bedarf kostenpflichtige Aufrufe; die anderen (z. B. dein Claude
        Pro-Abo) erscheinen nur in der Summe.
      </p>
      {data.fixed.from_env && (
        <p className="notice">
          Noch keine Posten gespeichert. Bis dahin gelten die Werte aus der Server-Konfiguration (
          {eur(data.costs.fixed)} im Monat). Die Startliste wird beim nächsten Update automatisch
          angelegt.
        </p>
      )}
      <div className="table-wrap">
        <table aria-label="Fixkosten">
          <thead>
            <tr>
              <th>Posten</th>
              <th>Art</th>
              <th>Betrag</th>
              <th>Pro Monat</th>
              <th>Budget</th>
              {canEdit && <th aria-label="Aktionen" />}
            </tr>
          </thead>
          <tbody>
            {items.map((item) =>
              editing === item.id ? (
                <tr key={item.id}>
                  <td colSpan={canEdit ? 6 : 5}>
                    <FixedCostForm
                      label={`${item.name} bearbeiten`}
                      initial={toInput(item)}
                      onCancel={() => setEditing(null)}
                      onSave={async (d) => {
                        await run(() => api.updateFixedCost(item.id, d));
                        setEditing(null);
                      }}
                    />
                  </td>
                </tr>
              ) : (
                <tr key={item.id} className={item.is_active ? undefined : "muted"}>
                  <td>
                    <strong>{item.name}</strong>
                    {item.provider && <span className="muted small"> · {item.provider}</span>}
                    {item.note && <div className="muted small">{item.note}</div>}
                  </td>
                  <td>{CATEGORIES[item.category] ?? item.category}</td>
                  <td>
                    {item.missing_price ? (
                      <Badge tone="warn">Betrag fehlt</Badge>
                    ) : (
                      <>
                        {item.amount.toLocaleString("de-DE", {
                          style: "currency",
                          currency: item.currency,
                        })}{" "}
                        <span className="muted small">
                          {item.interval === "year" ? "im Jahr" : "im Monat"}
                        </span>
                      </>
                    )}
                  </td>
                  <td>{item.is_active ? eur(item.monthly_eur) : "pausiert"}</td>
                  <td>
                    <Badge tone={item.in_budget ? "ok" : "neutral"}>
                      {item.in_budget ? "ja" : "nur Summe"}
                    </Badge>
                  </td>
                  {canEdit && (
                    <td className="row-actions">
                      <button
                        type="button"
                        className="btn btn-ghost btn-small"
                        onClick={() => setEditing(item.id)}
                      >
                        Bearbeiten
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-small"
                        onClick={() =>
                          void run(() =>
                            api.updateFixedCost(item.id, {
                              is_active: !item.is_active,
                            }),
                          ).catch(() => undefined)
                        }
                      >
                        {item.is_active ? "Pausieren" : "Aktivieren"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-small"
                        onClick={() =>
                          void run(() => api.deleteFixedCost(item.id)).catch(() => undefined)
                        }
                      >
                        Löschen
                      </button>
                    </td>
                  )}
                </tr>
              ),
            )}
            <tr>
              <td colSpan={3}>
                <strong>Summe Fixkosten</strong>
              </td>
              <td>
                <strong>{eur(data.costs.fixed)}</strong>
              </td>
              <td className="muted small">davon Budget {eur(data.costs.fixed_in_budget)}</td>
              {canEdit && <td />}
            </tr>
          </tbody>
        </table>
      </div>
      <ErrorText error={error} />
      {canEdit && (
        <details className="fixed-add">
          <summary>Posten hinzufügen</summary>
          <FixedCostForm
            label="Neuen Fixkosten-Posten anlegen"
            initial={EMPTY}
            onSave={(d) => run(() => api.addFixedCost(d))}
          />
        </details>
      )}
    </Section>
  );
}

function TokenTable({ today, month }: { today: AIUsageWindow; month: AIUsageWindow }) {
  const rows: [string, (w: AIUsageWindow) => string][] = [
    ["Aufrufe (davon echt)", (w) => `${num(w.calls)} (${num(w.live_calls)})`],
    ["Tokens Eingabe", (w) => num(w.input_tokens)],
    ["Tokens Ausgabe", (w) => num(w.output_tokens)],
    ["Tokens Cache", (w) => num(w.cache_tokens)],
    ["Kosten", (w) => usd(w.cost_usd)],
  ];
  return (
    <div className="table-wrap">
      <table aria-label="Token-Verbrauch">
        <thead>
          <tr>
            <th />
            <th>Heute</th>
            <th>Dieser Monat</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, f]) => (
            <tr key={label}>
              <td>{label}</td>
              <td>{f(today)}</td>
              <td>{f(month)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CostsView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "admin");
  const [data, setData] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api.costSummary());
      setError(null);
      setUpdated(new Date());
      setTick((t) => t + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const b = data?.budget;
  const level = b ? (LEVELS[b.level] ?? [b.level, "neutral"]) : null;
  return (
    <>
      <div className="page-head-row">
        <PageHeader
          title="Kosten"
          description="Fixkosten, KI-Tokens, Speicher und API-Verbrauch, laufend aktualisiert."
        />
        <div className="refresh">
          <Badge tone="ok">Live</Badge>
          <span className="muted small" aria-live="polite">
            {updated ? `Stand ${time(updated)}` : "Lade …"}
          </span>
          <button
            type="button"
            className="icon-btn"
            aria-label="Jetzt aktualisieren"
            title="Jetzt aktualisieren"
            disabled={busy}
            onClick={() => void load()}
          >
            <Icon name="refresh" />
          </button>
        </div>
      </div>
      <ErrorText error={error} />
      <div className="grid stats">
        <StatCard label="Monatskosten gesamt" value={eur(data?.costs.total)} />
        <StatCard label="Bisher angefallen" value={eur(data?.costs.accrued, 4)} />
        <StatCard label="Verbrauch heute" value={eur(data?.costs.today, 4)} />
        <StatCard
          label="Engine-Budget"
          value={b ? `${b.used_pct.toLocaleString("de-DE")} % von ${eur(b.budget_eur, 0)}` : "–"}
        />
        <StatCard
          label="Pro veröffentlichtem Video"
          value={eur(data?.unit_costs.per_published, 3)}
        />
      </div>
      <p className="muted small">
        „Monatskosten gesamt“ ist der volle Monat inklusive aller Fixkosten. „Bisher angefallen“
        verteilt die Fixkosten sekundengenau über den Monat und rechnet den echten Verbrauch (KI,
        APIs) dazu. Die Seite aktualisiert sich alle {REFRESH_MS / 1000} Sekunden.
      </p>
      {level && b && (
        <p role="status">
          Budgetstufe: <Badge tone={level[1]}>{level[0]}</Badge>{" "}
          <span className="muted">
            {eur(b.spent_eur)} zählen zum Budget. Warnung ab {b.thresholds.warn} %, kostenreduziert
            ab {b.thresholds.reduced} %, nur priorisierte Aufgaben ab {b.thresholds.priority_only}{" "}
            %, kostenpflichtige Aufgaben gestoppt ab {b.thresholds.stop_paid} %.
          </span>
        </p>
      )}
      {data && <FixedCostsSection data={data} canEdit={canEdit} reload={load} />}
      <Section title="KI-Tokens in Echtzeit">
        <p className="notice">
          Wichtig: Dein Claude-Pro-Abo gilt nur für den Chat auf claude.ai. Die Engine braucht für
          echte KI-Aufrufe einen eigenen Anthropic-API-Schlüssel mit getrennter Abrechnung nach
          Tokens. Ohne Schlüssel laufen alle Aufrufe im Test-Modus und kosten 0 $.
        </p>
        {data && <TokenTable today={data.ai.today} month={data.ai.month} />}
        {data?.ai.today.last_call_at && (
          <p className="muted small">
            Letzter Aufruf: {new Date(data.ai.today.last_call_at).toLocaleString("de-DE")}
          </p>
        )}
      </Section>
      <AIUsagePanel tick={tick} />
      <Section title="Kosten nach Bereich">
        <BarList
          title="Kosten im Monat"
          rows={COST_LABELS.map(([k, label]) => ({
            label,
            value: data?.costs[k] ?? 0,
          }))}
          format={(v) => eur(v)}
        />
      </Section>
      <Section title="Videos, Speicher und API-Nutzung heute">
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
                  <td>API-Kontingent heute: {k}</td>
                  <td>{v}</td>
                </tr>
              ))}
              {data && Object.keys(data.api_usage_today).length === 0 && (
                <tr>
                  <td>API-Kontingent heute</td>
                  <td className="muted">noch keine Abfragen</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </>
  );
}
