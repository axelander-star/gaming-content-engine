"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, ErrorText, PageHeader, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import type { CheckStatus, MonitorSample, SystemStatus } from "@/lib/types";

import { ColumnChart } from "./charts";

const STATUS: Record<CheckStatus, [string, "ok" | "warn" | "danger" | "neutral"]> = {
  ok: ["In Ordnung", "ok"],
  warn: ["Warnung", "warn"],
  critical: ["Kritisch", "danger"],
  unknown: ["Unbekannt", "neutral"],
};

function StatusBadge({ status }: { status: CheckStatus }) {
  const [label, tone] = STATUS[status] ?? STATUS.unknown;
  return <Badge tone={tone}>{label}</Badge>;
}

function size(bytes: number): string {
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

/** Highest value per hour, so a day of one-minute samples stays readable. */
function hourly(samples: MonitorSample[], pick: (s: MonitorSample) => number | null) {
  const buckets = new Map<string, { label: string; value: number | null }>();
  for (const s of samples) {
    const d = new Date(s.ts);
    const label = `${String(d.getHours()).padStart(2, "0")}:00`;
    const key = `${d.toDateString()} ${label}`;
    const v = pick(s);
    const prev = buckets.get(key)?.value ?? null;
    buckets.set(key, { label, value: v === null ? prev : Math.max(prev ?? 0, v) });
  }
  return [...buckets.values()];
}

export function SystemView() {
  const [data, setData] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api
      .systemStatus()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const b = data?.backup;
  const rc = b?.restore_check;
  return (
    <>
      <PageHeader
        title="System"
        description="Zustand der Dienste, Datensicherung und Skalierung. Probleme erscheinen zusätzlich als Benachrichtigung."
      />
      <ErrorText error={error} />
      {data && (
        <p role="status">
          Gesamtzustand: <StatusBadge status={data.status} />{" "}
          <span className="muted">geprüft {formatDateTime(data.checked_at)}</span>{" "}
          <button type="button" className="btn btn-ghost small" onClick={load}>
            Neu prüfen
          </button>
        </p>
      )}
      <Section title="Prüfungen">
        <div className="table-wrap">
          <table aria-label="Prüfungen">
            <thead>
              <tr>
                <th>Bereich</th>
                <th>Zustand</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {(data?.checks ?? []).map((c) => (
                <tr key={c.key}>
                  <td>{c.label}</td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td className="muted">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Datensicherung">
        {b && !b.configured && (
          <p className="muted" role="alert">
            Es ist kein Schlüssel für die Sicherung hinterlegt (BACKUP_PASSPHRASE). Bis dahin wird
            nichts gesichert.
          </p>
        )}
        <div className="grid stats">
          <StatCard
            label="Letzte Sicherung"
            value={b?.latest ? formatDateTime(b.latest.created_at) : "–"}
          />
          <StatCard
            label="Wiederherstellungstest"
            value={!rc ? "Noch nicht getestet" : rc.ok ? "Bestanden" : "Fehlgeschlagen"}
            hint={
              rc
                ? `${formatDateTime(rc.checked_at)} · ${rc.rows.toLocaleString("de-DE")} Zeilen`
                : undefined
            }
          />
          <StatCard
            label="Gespeicherte Sicherungen"
            value={b ? `${b.count} (${size(b.total_bytes)})` : "–"}
          />
        </div>
        {rc && !rc.ok && (
          <ul className="quality-reasons" aria-label="Probleme beim Wiederherstellungstest">
            {rc.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        {b && b.backups.length > 0 && (
          <details>
            <summary>Alle Sicherungen</summary>
            <div className="table-wrap">
              <table aria-label="Sicherungen">
                <thead>
                  <tr>
                    <th>Zeitpunkt</th>
                    <th>Datei</th>
                    <th>Größe</th>
                    <th>Zeilen</th>
                  </tr>
                </thead>
                <tbody>
                  {b.backups.map((m) => (
                    <tr key={m.file}>
                      <td>{formatDateTime(m.created_at)}</td>
                      <td className="muted">{m.file}</td>
                      <td>{size(m.size_bytes)}</td>
                      <td>{m.rows.toLocaleString("de-DE")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </Section>
      <Section title="Skalierung">
        <p className="muted small">
          Empfohlen wird eine Skalierung nur, wenn ein Engpass über mehrere Stunden anhält
          (mindestens drei Stunden Messwerte, Engpass in drei Vierteln der Messungen).
        </p>
        <ul className="quality-reasons" aria-label="Skalierungsempfehlung">
          {(data?.scaling ?? []).map((a) => (
            <li key={a.key}>
              <strong>{a.text}</strong>
              {a.evidence && <span className="muted"> · {a.evidence}</span>}
            </li>
          ))}
        </ul>
        <div className="chart-grid-3">
          <ColumnChart
            title="Längste Wartezeit in der Warteschlange (min)"
            points={hourly(data?.samples ?? [], (s) => s.wait_s / 60)}
            format={(v) => v.toLocaleString("de-DE", { maximumFractionDigits: 1 })}
          />
          <ColumnChart
            title="CPU-Last je Kern (%)"
            points={hourly(data?.samples ?? [], (s) => (s.load === null ? null : s.load * 100))}
            format={(v) => `${Math.round(v)}`}
          />
          <ColumnChart
            title="Wartende Aufträge"
            points={hourly(data?.samples ?? [], (s) => s.backlog)}
          />
        </div>
      </Section>
    </>
  );
}
