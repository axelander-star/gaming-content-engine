"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section, StatCard } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type { ChannelPlan, PlannedJob, PublishingJobStatus, StrategyVersion } from "@/lib/types";

const JOB_STATUS: Record<PublishingJobStatus, [string, "neutral" | "ok" | "warn" | "danger"]> = {
  pending: ["Wartet", "neutral"],
  scheduled: ["Geplant", "ok"],
  running: ["Läuft", "warn"],
  succeeded: ["Veröffentlicht", "ok"],
  failed: ["Fehlgeschlagen", "danger"],
  cancelled: ["Zurückgenommen", "neutral"],
  blocked: ["Gesperrt", "danger"],
};

function localTime(iso: string | null, timeZone: string): string {
  if (!iso) return "–";
  return new Intl.DateTimeFormat("de-DE", {
    timeZone,
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

function author(v: StrategyVersion): string {
  if (v.created_by === "publishing_strategy") return "Strategie-Agent";
  return v.created_by.startsWith("user:") ? "Betreiber" : v.created_by;
}

function JobRow({ job, timeZone }: { job: PlannedJob; timeZone: string }) {
  const [label, tone] = JOB_STATUS[job.status];
  return (
    <li>
      <span className="muted">{localTime(job.scheduled_for, timeZone)}</span> ·{" "}
      {job.language.toUpperCase()} {job.label} · {job.title ?? `Variante #${job.variant_id}`}{" "}
      <Badge tone={tone}>{label}</Badge> {job.mode === "mock" && <Badge>Test</Badge>}
      {job.note && <span className="muted"> · {job.note}</span>}
    </li>
  );
}

function ChannelCard({
  plan,
  canRollback,
  onRollback,
}: {
  plan: ChannelPlan;
  canRollback: boolean;
  onRollback: (version: number) => void;
}) {
  const v = plan.current;
  const a = v?.inputs.assessment;
  const upcoming = plan.jobs.filter((j) => j.status !== "cancelled");
  const cancelled = plan.jobs.filter((j) => j.status === "cancelled");
  return (
    <div className="strategy-card" aria-label={`Strategie ${plan.name}`}>
      <div className="strategy-head">
        <strong>{plan.name}</strong>
        {plan.is_paused ? <Badge tone="warn">Pausiert</Badge> : <Badge tone="ok">Aktiv</Badge>}
        {plan.max_posts_per_day === 0 && <Badge tone="warn">Grenzen nicht eingerichtet</Badge>}
        <span className="muted">
          Grenzen {plan.min_posts_per_day}–{plan.max_posts_per_day} pro Tag · Abstand ≥{" "}
          {plan.min_interval_minutes} min · Fenster {plan.window[0]}–{plan.window[1]} Uhr (
          {plan.timezone}) · {plan.ready} bereit
        </span>
      </div>
      {v ? (
        <>
          <p>
            Entscheidung: <strong>{v.posts_per_day} pro Tag</strong>{" "}
            <span className="muted">
              (Version {v.version}, {author(v)}, {formatDateTime(v.created_at)})
            </span>
          </p>
          <ul className="quality-reasons" aria-label="Begründung">
            {v.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          {a && (
            <p className="muted">
              {a.judged} Videos ausgewertet, {a.waiting} noch zu jung
              {a.recent_median !== null && ` · zuletzt ${a.recent_median.toFixed(2)}× Kanalschnitt`}
              {v.params.preferred_hours &&
                ` · beste Stunden ${v.params.preferred_hours.join(", ")}`}
            </p>
          )}
        </>
      ) : (
        <p className="muted">Noch keine Entscheidung – erst wenn Videos bereitstehen.</p>
      )}
      {upcoming.length > 0 && (
        <ul className="quality-reasons" aria-label="Geplante Veröffentlichungen">
          {upcoming.map((j) => (
            <JobRow key={j.id} job={j} timeZone={plan.timezone} />
          ))}
        </ul>
      )}
      {cancelled.length > 0 && (
        <details>
          <summary>{cancelled.length} zurückgenommen</summary>
          <ul className="quality-reasons">
            {cancelled.map((j) => (
              <JobRow key={j.id} job={j} timeZone={plan.timezone} />
            ))}
          </ul>
        </details>
      )}
      {plan.history.length > 1 && (
        <details>
          <summary>Frühere Versionen</summary>
          <ul className="quality-reasons">
            {plan.history.slice(1).map((h) => (
              <li key={h.version}>
                Version {h.version}: {h.posts_per_day} pro Tag ({h.planned_for}, {author(h)})
                {h.reasons[0] && <span className="muted"> · {h.reasons[0]}</span>}{" "}
                {canRollback && (
                  <button
                    type="button"
                    className="btn btn-ghost small"
                    onClick={() => onRollback(h.version)}
                    aria-label={`${plan.name} auf Version ${h.version} zurücksetzen`}
                  >
                    Zurücksetzen
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function PublishingView() {
  const { user } = useAuth();
  const admin = hasRole(user?.role, "admin");
  const [plans, setPlans] = useState<ChannelPlan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPlans(await api.publishingPlan());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const rollback = async (channelId: number, version: number) => {
    try {
      const v = await api.rollbackStrategy(channelId, version);
      setNotice(`Version ${version} wiederhergestellt (neu: Version ${v.version}).`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const jobs = plans?.flatMap((p) => p.jobs) ?? [];
  const decided = plans?.filter((p) => p.current) ?? [];
  return (
    <>
      <PageHeader
        title="Publishing"
        description="Menge, Auswahl und Zeitpunkt je Kanal – entschieden vom Publishing Strategy Agent."
      />
      <div className="grid stats">
        <StatCard
          label="Kanäle mit Strategie"
          value={`${decided.length} / ${plans?.length ?? 0}`}
        />
        <StatCard
          label="Geplant"
          value={String(jobs.filter((j) => j.status === "scheduled").length)}
        />
        <StatCard
          label="Bereit, nicht geplant"
          value={String(plans?.reduce((n, p) => n + p.ready, 0) ?? 0)}
        />
        <StatCard
          label="Modus"
          value={jobs.some((j) => j.mode === "live") ? "Live" : "Test (keine echten Posts)"}
        />
      </div>
      <ErrorText error={error} />
      {notice && (
        <p role="status" className="muted">
          {notice}
        </p>
      )}
      <Section title="Kanäle">
        <p className="muted">
          Es gibt keine feste Menge. Die Höchstgrenzen sind Sicherheitsgrenzen; die Menge ändert
          sich höchstens um eins pro Tag, erhöht wird erst nach ausreichend Daten und nie wegen
          eines einzelnen viralen Videos.
        </p>
        {plans === null ? (
          <p className="muted">Lädt …</p>
        ) : (
          plans.map((p) => (
            <ChannelCard
              key={p.channel_id}
              plan={p}
              canRollback={admin}
              onRollback={(version) => void rollback(p.channel_id, version)}
            />
          ))
        )}
      </Section>
    </>
  );
}
