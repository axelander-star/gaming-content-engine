"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  AnalyticsFilters,
  AnalyticsOverview,
  LearningVersionOut,
  PerfGroup,
  PerfVideo,
} from "@/lib/types";

import { BarList, ColumnChart } from "./charts";

const FILTERS: [keyof AnalyticsFilters, string][] = [
  ["platform", "Plattform"],
  ["language", "Sprache"],
  ["game", "Spiel"],
  ["format", "Format"],
  ["hook", "Hook"],
  ["hour", "Veröffentlichungszeit (UTC-Stunde)"],
];

const STATUS: Record<LearningVersionOut["status"], [string, "ok" | "warn" | "neutral" | "danger"]> =
  {
    trial: ["Im Test", "warn"],
    active: ["Aktiv", "ok"],
    rolled_back: ["Zurückgenommen", "danger"],
    superseded: ["Abgelöst", "neutral"],
  };

const KIND_LABELS: Record<string, string> = { game: "Spiel", format: "Format", hook: "Hook" };

const pct = (v: number | null) => (v === null ? "–" : `${(v * 100).toFixed(1)} %`);
const num = (v: number | null | undefined) => (v == null ? "–" : v.toLocaleString("de-DE"));

function GroupTable({ title, rows }: { title: string; rows: PerfGroup[] }) {
  return (
    <div className="table-wrap">
      <table aria-label={title}>
        <thead>
          <tr>
            <th>{title}</th>
            <th>Videos</th>
            <th>Aufrufe</th>
            <th>Median</th>
            <th>Interaktion</th>
            <th>Bindung</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => (
            <tr key={g.key}>
              <td>{g.key}</td>
              <td>{g.posts}</td>
              <td>{num(g.views)}</td>
              <td>{num(g.median_views)}</td>
              <td>{pct(g.engagement_rate)}</td>
              <td>{g.retention_pct === null ? "–" : `${g.retention_pct} %`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VideoList({ label, videos }: { label: string; videos: PerfVideo[] }) {
  if (videos.length === 0) return null;
  return (
    <div>
      <strong>{label}</strong>
      <ul className="quality-reasons" aria-label={label}>
        {videos.map((v) => (
          <li key={v.post_id}>
            {v.url ? (
              <a href={v.url} target="_blank" rel="noreferrer">
                {v.title ?? `Post #${v.post_id}`}
              </a>
            ) : (
              (v.title ?? `Post #${v.post_id}`)
            )}{" "}
            <span className="muted">
              · {v.channel} · {v.game ?? "–"} · {v.format ?? "–"} · {num(v.views)} Aufrufe (
              {v.window})
            </span>{" "}
            {v.is_mock && <Badge>Test</Badge>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function LearningSection({ admin }: { admin: boolean }) {
  const [versions, setVersions] = useState<LearningVersionOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api
      .learningVersions()
      .then(setVersions)
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  const current =
    versions?.find((v) => v.status === "trial") ?? versions?.find((v) => v.status === "active");
  return (
    <Section title="Erkenntnisse (Learning Agent)">
      <p className="muted small">
        Gelernt wird erst ab acht bewerteten Videos je Spiel, Format oder Hook an mindestens drei
        Tagen. Jede Änderung läuft zuerst sieben Tage im Test und wird zurückgenommen, wenn sie
        schlechter abschneidet. Die Faktoren (0,8–1,2) ändern nur die Reihenfolge, sie sperren
        nichts.
      </p>
      <ErrorText error={error} />
      {versions === null ? (
        <p className="muted">Lädt …</p>
      ) : !current ? (
        <p className="muted">Noch keine Erkenntnisse – dafür fehlen bisher genug Messwerte.</p>
      ) : (
        <div className="strategy-card" aria-label="Aktuelle Lernversion">
          <div className="strategy-head">
            <strong>Version {current.version}</strong>
            <Badge tone={STATUS[current.status][1]}>{STATUS[current.status][0]}</Badge>
            {current.trial_until && current.status === "trial" && (
              <span className="muted">Test bis {formatDateTime(current.trial_until)}</span>
            )}
          </div>
          <ul className="quality-reasons" aria-label="Begründung">
            {current.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {Object.entries(current.weights).map(([kind, rows]) =>
            Object.keys(rows).length ? (
              <p key={kind} className="muted">
                {KIND_LABELS[kind] ?? kind}:{" "}
                {Object.entries(rows)
                  .map(([k, w]) => `${k} ${w.toFixed(2)}×`)
                  .join(", ")}
              </p>
            ) : null,
          )}
        </div>
      )}
      {versions && versions.length > 1 && (
        <details>
          <summary>Alle Versionen</summary>
          <ul className="quality-reasons">
            {versions.map((v) => (
              <li key={v.version}>
                Version {v.version} <Badge tone={STATUS[v.status][1]}>{STATUS[v.status][0]}</Badge>{" "}
                <span className="muted">
                  {formatDateTime(v.created_at)}
                  {typeof v.evaluation.result === "string" && ` · ${v.evaluation.result}`}
                </span>{" "}
                {admin && v.version !== current?.version && (
                  <button
                    type="button"
                    className="btn btn-ghost small"
                    aria-label={`Lernversion ${v.version} wiederherstellen`}
                    onClick={() =>
                      api
                        .rollbackLearning(v.version)
                        .then(load)
                        .catch((e: Error) => setError(e.message))
                    }
                  >
                    Wiederherstellen
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Section>
  );
}

export function AnalyticsView() {
  const { user } = useAuth();
  const [filters, setFilters] = useState<AnalyticsFilters>({ days: 30 });
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .analytics(filters)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [filters]);

  const t = data?.totals;
  const timeline = data?.timeline ?? [];
  const series = (pick: (r: (typeof timeline)[number]) => number | null) =>
    timeline.map((r) => ({ label: r.day.slice(5), value: pick(r) }));
  const bars = (key: string) =>
    (data?.groups[key] ?? []).slice(0, 8).map((g) => ({
      label: g.key,
      value: g.views,
      note: `${g.posts} Videos`,
    }));

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Performance nach Plattform, Sprache, Spiel, Format, Hook und Zeitpunkt."
      />
      <div className="filters" role="group" aria-label="Filter">
        <label>
          Zeitraum
          <select
            className="input-sm"
            value={filters.days}
            onChange={(e) => setFilters({ ...filters, days: Number(e.target.value) })}
          >
            {[7, 30, 90, 365].map((d) => (
              <option key={d} value={d}>
                {d} Tage
              </option>
            ))}
          </select>
        </label>
        {FILTERS.map(([key, label]) => (
          <label key={key}>
            {label}
            <select
              className="input-sm"
              value={(filters[key] as string | undefined) ?? ""}
              onChange={(e) => setFilters({ ...filters, [key]: e.target.value || undefined })}
            >
              <option value="">Alle</option>
              {(data?.options[key] ?? []).map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <ErrorText error={error} />
      {data?.test_data && (
        <p role="status" className="muted">
          <Badge>Test</Badge> Die Zahlen stammen von Testveröffentlichungen (Mock) und sind
          synthetisch. Im Live-Modus werden nur echte Posts ausgewertet.
        </p>
      )}
      <div className="grid stats">
        <StatCard label="Videos gemessen" value={t ? `${t.measured} / ${t.posts}` : "–"} />
        <StatCard label="Aufrufe" value={num(t?.views)} />
        <StatCard label="Interaktionsrate" value={pct(t?.engagement_rate ?? null)} />
        <StatCard
          label="Zuschauerbindung"
          value={t?.retention_pct == null ? "–" : `${t.retention_pct} %`}
        />
        <StatCard
          label="Ø Wiedergabedauer"
          value={t?.avg_view_duration_s == null ? "–" : `${t.avg_view_duration_s} s`}
        />
        <StatCard label="Follower-Zuwachs" value={num(t?.followers_gained)} />
      </div>
      <Section title="Verlauf nach Veröffentlichungstag">
        <div className="chart-grid-4">
          <ColumnChart title="Aufrufe" points={series((r) => r.views)} />
          <ColumnChart
            title="Zuschauerbindung (%)"
            points={series((r) => r.retention_pct)}
            format={(v) => `${Math.round(v)}`}
          />
          <ColumnChart
            title="Ø Wiedergabedauer (s)"
            points={series((r) => r.avg_view_duration_s)}
            format={(v) => `${Math.round(v)}`}
          />
          <ColumnChart
            title="Interaktionsrate (%)"
            points={series((r) => (r.engagement_rate === null ? null : r.engagement_rate * 100))}
            format={(v) => v.toFixed(1)}
          />
          <ColumnChart title="Follower-Zuwachs" points={series((r) => r.followers_gained)} />
        </div>
      </Section>
      <Section title="Performance pro Spiel, Format und Kanal">
        <div className="chart-grid-3">
          <BarList title="Aufrufe pro Spiel" rows={bars("game")} />
          <BarList title="Aufrufe pro Format" rows={bars("format")} />
          <BarList title="Aufrufe pro Kanal" rows={bars("channel")} />
        </div>
        <details>
          <summary>Tabellen</summary>
          <GroupTable title="Spiel" rows={data?.groups.game ?? []} />
          <GroupTable title="Format" rows={data?.groups.format ?? []} />
          <GroupTable title="Kanal" rows={data?.groups.channel ?? []} />
          <GroupTable title="Hook" rows={data?.groups.hook ?? []} />
          <GroupTable title="Stunde (UTC)" rows={data?.groups.hour ?? []} />
        </details>
      </Section>
      <Section title="Stärkste und schwächste Videos">
        {data && data.top.length === 0 ? (
          <p className="muted">Noch keine gemessenen Videos im Zeitraum.</p>
        ) : (
          <div className="chart-grid-3">
            <VideoList label="Stärkste Videos" videos={data?.top ?? []} />
            <VideoList label="Schwächste Videos" videos={data?.weak ?? []} />
          </div>
        )}
      </Section>
      <LearningSection admin={hasRole(user?.role, "admin")} />
    </>
  );
}
