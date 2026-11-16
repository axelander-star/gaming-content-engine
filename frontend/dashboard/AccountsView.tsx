"use client";

// Account overview: every channel at a glance, built for 100+ accounts. Filters,
// sortable columns, a status per channel (with a "consider pausing" suggestion
// after the review period) and revenue entries per channel.

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS, formatEur } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  AccountRow,
  AccountStatus,
  AccountsOverview,
  PlatformCode,
  RevenueEntry,
  RevenueSource,
} from "@/lib/types";

const PAGE = 50;
const STATUS_TONE: Record<AccountStatus, "ok" | "warn" | "danger" | "info" | "neutral"> = {
  growing: "ok",
  stable: "neutral",
  new: "info",
  declining: "warn",
  idle: "warn",
  setup: "warn",
  paused: "neutral",
  pause_suggested: "danger",
};
const STATUS_ORDER: AccountStatus[] = [
  "pause_suggested",
  "declining",
  "idle",
  "setup",
  "growing",
  "stable",
  "new",
  "paused",
];
const SOURCE_LABELS: Record<RevenueSource, string> = {
  youtube: "YouTube-Auszahlung",
  content_rewards: "Content Rewards",
  affiliate: "Affiliate",
  sponsor: "Sponsor",
  other: "Sonstiges",
};

type SortKey = "name" | "views_30d" | "trend_30d" | "revenue" | "posts_30d" | "engagement_30d";

const num = (n: number) => n.toLocaleString("de-DE");
const pct = (v: number | null) =>
  v === null ? "–" : `${v > 0 ? "+" : ""}${Math.round(v * 100)} %`;
const money = (row: AccountRow) => Number(row.revenue_30d) + Number(row.estimate_30d);

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthStart(): string {
  const d = new Date();
  return new Date(Date.UTC(d.getFullYear(), d.getMonth(), 1)).toISOString().slice(0, 10);
}

function RevenuePanel({ row, onChanged }: { row: AccountRow; onChanged: () => Promise<void> }) {
  const [entries, setEntries] = useState<RevenueEntry[] | null>(null);
  const [source, setSource] = useState<RevenueSource>(
    row.platform === "youtube" ? "youtube" : "affiliate",
  );
  const [amount, setAmount] = useState("");
  const [start, setStart] = useState(monthStart());
  const [end, setEnd] = useState(today());
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setEntries(await api.revenue(row.channel_id));
  }, [row.channel_id]);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    try {
      await api.addRevenue({
        channel_id: row.channel_id,
        source,
        amount_eur: amount.replace(",", "."),
        period_start: start,
        period_end: end,
        note: note || undefined,
      });
      setAmount("");
      setNote("");
      await load();
      await onChanged();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(id: number) {
    try {
      await api.deleteRevenue(id);
      await load();
      await onChanged();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="acc-panel">
      {row.reasons.length > 0 && (
        <ul className="acc-reasons">
          {row.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <form className="acc-rev-form" onSubmit={add} aria-label={`Einnahme für ${row.name}`}>
        <label>
          Quelle
          <select value={source} onChange={(e) => setSource(e.target.value as RevenueSource)}>
            {Object.entries(SOURCE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Betrag in €
          <input
            inputMode="decimal"
            required
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0,00"
          />
        </label>
        <label>
          Von
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label>
          Bis
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} required />
        </label>
        <label>
          Notiz
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} />
        </label>
        <button className="btn btn-primary">Einnahme speichern</button>
      </form>
      <ErrorText error={error} />
      {entries && entries.length > 0 && (
        <ul className="acc-entries">
          {entries.map((e) => (
            <li key={e.id}>
              <span>
                {SOURCE_LABELS[e.source]}: {formatEur(e.amount_eur)} ({e.period_start} bis{" "}
                {e.period_end}){e.note ? `, ${e.note}` : ""}
              </span>
              <button className="btn btn-ghost btn-small" onClick={() => void remove(e.id)}>
                Löschen
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AccountsView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "admin");
  const [data, setData] = useState<AccountsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [project, setProject] = useState<number | "all">("all");
  const [platform, setPlatform] = useState<PlatformCode | "all">("all");
  const [status, setStatus] = useState<AccountStatus | "all">("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("views_30d");
  const [desc, setDesc] = useState(true);
  const [limit, setLimit] = useState(PAGE);
  const [open, setOpen] = useState<number | null>(null);

  const load = useCallback(async () => {
    setData(await api.accounts());
  }, []);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    const filtered = data.accounts.filter(
      (a) =>
        (project === "all" || a.project_id === project) &&
        (platform === "all" || a.platform === platform) &&
        (status === "all" || a.status === status) &&
        (!q ||
          a.name.toLowerCase().includes(q) ||
          (a.handle ?? "").toLowerCase().includes(q) ||
          a.project.toLowerCase().includes(q)),
    );
    const value = (a: AccountRow): number | string => {
      switch (sort) {
        case "name":
          return a.name.toLowerCase();
        case "revenue":
          return money(a);
        case "trend_30d":
          return a.trend_30d ?? -Infinity;
        case "engagement_30d":
          return a.engagement_30d ?? -Infinity;
        default:
          return a[sort];
      }
    };
    return [...filtered].sort((a, b) => {
      const x = value(a);
      const y = value(b);
      const c = x < y ? -1 : x > y ? 1 : 0;
      return desc ? -c : c;
    });
  }, [data, project, platform, status, query, sort, desc]);

  function sortBy(key: SortKey) {
    if (sort === key) setDesc(!desc);
    else {
      setSort(key);
      setDesc(key !== "name");
    }
  }

  const head = (key: SortKey, label: string) => (
    <th aria-sort={sort === key ? (desc ? "descending" : "ascending") : "none"}>
      <button type="button" className="th-sort" onClick={() => sortBy(key)}>
        {label}
        {sort === key ? (desc ? " ▼" : " ▲") : ""}
      </button>
    </th>
  );

  if (!data) {
    return (
      <>
        <PageHeader title="Konten" />
        <ErrorText error={error} />
        {!error && <p className="muted">Lädt …</p>}
      </>
    );
  }

  const s = data.summary;
  const trend = s.views_prev_30d ? (s.views_30d - s.views_prev_30d) / s.views_prev_30d : null;
  const projects = Array.from(new Map(data.accounts.map((a) => [a.project_id, a.project])));
  const byId = new Map(data.accounts.map((a) => [a.channel_id, a]));

  return (
    <>
      <PageHeader
        title="Konten"
        description={`Alle Kanäle mit Reichweite, Einnahmen und Empfehlung. Bewertet wird ein Kanal ${s.review_days} Tage nach dem ersten Beitrag; „Pausieren erwägen“ ist nur ein Vorschlag.`}
      />
      <ErrorText error={error} />
      <div className="grid stats">
        <StatCard label="Kanäle" value={num(s.channels)} hint={`${s.connected} verbunden`} />
        <StatCard
          label="Aufrufe (30 Tage)"
          value={num(s.views_30d)}
          hint={trend === null ? "kein Vergleich" : `${pct(trend)} zu den 30 Tagen davor`}
        />
        <StatCard label="Neue Follower (30 Tage)" value={num(s.followers_30d)} />
        <StatCard
          label="Einnahmen (30 Tage)"
          value={formatEur(s.revenue_30d)}
          hint={
            Number(s.estimate_30d) > 0
              ? `+ ${formatEur(s.estimate_30d)} geschätzt (Content Rewards)`
              : "eingetragene Auszahlungen"
          }
        />
      </div>

      {s.top_revenue.length > 0 && (
        <Section title="Lohnt sich am meisten">
          <ol className="acc-top">
            {s.top_revenue.map((id) => {
              const a = byId.get(id);
              return a ? (
                <li key={id}>
                  {a.name} ({PLATFORM_LABELS[a.platform]}, {a.project}):{" "}
                  {formatEur(money(a))}
                </li>
              ) : null;
            })}
          </ol>
        </Section>
      )}

      <Section title="Alle Konten">
        <div className="chip-row acc-status" role="group" aria-label="Status filtern">
          <button
            type="button"
            className={`chip chip-btn ${status === "all" ? "is-active" : ""}`}
            aria-pressed={status === "all"}
            onClick={() => setStatus("all")}
          >
            Alle {s.channels}
          </button>
          {STATUS_ORDER.filter((k) => s.by_status[k]).map((k) => (
            <button
              key={k}
              type="button"
              className={`chip chip-btn ${status === k ? "is-active" : ""}`}
              aria-pressed={status === k}
              onClick={() => setStatus(k)}
            >
              {data.accounts.find((a) => a.status === k)?.status_label} {s.by_status[k]}
            </button>
          ))}
        </div>
        <div className="acc-filters">
          <label>
            Themenbereich
            <select
              value={project}
              onChange={(e) => setProject(e.target.value === "all" ? "all" : Number(e.target.value))}
            >
              <option value="all">Alle</option>
              {projects.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Plattform
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value as PlatformCode | "all")}
            >
              <option value="all">Alle</option>
              {(Object.keys(PLATFORM_LABELS) as PlatformCode[]).map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_LABELS[p]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Suche
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Name, @Handle, Thema"
            />
          </label>
        </div>
        <p className="muted small">
          {rows.length} von {data.accounts.length} Konten
        </p>
        <div className="table-wrap">
          <table className="acc-table">
            <thead>
              <tr>
                {head("name", "Kanal")}
                <th>Status</th>
                {head("posts_30d", "Beiträge")}
                {head("views_30d", "Aufrufe")}
                {head("trend_30d", "Trend")}
                {head("engagement_30d", "Interaktion")}
                {head("revenue", "Einnahmen")}
                <th>
                  <span className="sr-only">Details</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, limit).map((a) => (
                <Fragment key={a.channel_id}>
                  <tr>
                    <td>
                      <div className="acc-name">{a.name}</div>
                      <div className="muted small">
                        {PLATFORM_LABELS[a.platform]} · {a.language.toUpperCase()} · {a.project}
                        {a.handle ? ` · @${a.handle}` : ""}
                      </div>
                    </td>
                    <td>
                      <Badge tone={STATUS_TONE[a.status]}>{a.status_label}</Badge>
                    </td>
                    <td>{num(a.posts_30d)}</td>
                    <td>{num(a.views_30d)}</td>
                    <td>{pct(a.trend_30d)}</td>
                    <td>{a.engagement_30d === null ? "–" : `${(a.engagement_30d * 100).toFixed(1)} %`}</td>
                    <td>
                      {formatEur(a.revenue_30d)}
                      {Number(a.estimate_30d) > 0 && (
                        <div className="muted small">+ {formatEur(a.estimate_30d)} geschätzt</div>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-small"
                        aria-expanded={open === a.channel_id}
                        aria-label={`Details ${a.name}`}
                        onClick={() => setOpen(open === a.channel_id ? null : a.channel_id)}
                      >
                        {open === a.channel_id ? "Schließen" : "Details"}
                      </button>
                    </td>
                  </tr>
                  {open === a.channel_id && (
                    <tr className="acc-detail">
                      <td colSpan={8}>
                        {canEdit ? (
                          <RevenuePanel row={a} onChanged={load} />
                        ) : (
                          <ul className="acc-reasons">
                            {a.reasons.map((r) => (
                              <li key={r}>{r}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length > limit && (
          <button className="btn" onClick={() => setLimit(limit + PAGE)}>
            Weitere {Math.min(PAGE, rows.length - limit)} anzeigen
          </button>
        )}
      </Section>
    </>
  );
}
