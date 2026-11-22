"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Icon, PlatformMark } from "@/components/icons";
import type { IconName } from "@/components/icons";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { TrendsPanel } from "@/dashboard/TrendsPanel";
import { api } from "@/lib/api";
import { formatDateTime, formatEur } from "@/lib/labels";
import type {
  Budget,
  CostSummary,
  Dashboard,
  DashboardActivity,
  DashboardStateKey,
  Overview,
  PlatformConnection,
  PlatformTile,
  Readiness,
} from "@/lib/types";

/** The start page refreshes itself while it is visible. */
const REFRESH_MS = 30_000;

type Tone = "neutral" | "ok" | "warn" | "danger" | "info";

const STATE_META: Record<DashboardStateKey, { label: string; color: string }> =
  {
    draft: { label: "Entwurf", color: "#6b7282" },
    in_progress: { label: "In Bearbeitung", color: "#4da0ff" },
    ready: { label: "Bereit zur Veröffentlichung", color: "#8b7bff" },
    scheduled: { label: "Geplant", color: "#f0b544" },
    uploading: { label: "Wird hochgeladen", color: "#2fc7c0" },
    published: { label: "Veröffentlicht", color: "#34c774" },
    failed: { label: "Fehlgeschlagen", color: "#ff636b" },
  };

const CONNECTION: Record<PlatformConnection, [string, Tone]> = {
  not_connected: ["Nicht verbunden", "neutral"],
  restricted: ["Verbunden (eingeschränkt)", "warn"],
  connected: ["Verbunden", "ok"],
  expired: ["Anmeldung abgelaufen", "danger"],
  data_source_mock: ["Datenquelle · Testdaten", "info"],
  data_source_ok: ["Datenquelle · aktiv", "ok"],
  data_source_error: ["Datenquelle · Fehler", "danger"],
};

const ACTIONS: Record<string, string> = {
  status_change: "Status geändert",
  failed: "Fehlgeschlagen",
  retry: "Neuer Versuch",
  "auth.login": "Anmeldung",
  "auth.logout": "Abmeldung",
  "auth.logout_all": "Überall abgemeldet",
  "agent.succeeded": "Agentenlauf erfolgreich",
  "agent.failed": "Agentenlauf fehlgeschlagen",
  "agent.run_manual": "Agent manuell gestartet",
  "agent.pause": "Agent pausiert",
  "agent.resume": "Agent fortgesetzt",
  "project.create": "Themenbereich angelegt",
  "project.update": "Themenbereich geändert",
  "channel.create": "Kanal angelegt",
  "channel.project": "Kanal verschoben",
  "channel.pause": "Kanal pausiert",
  "channel.resume": "Kanal fortgesetzt",
  "channel.limits": "Kanal-Grenzen geändert",
  "channel.connected": "Kanal verbunden",
  "channel.connect_started": "Kanal-Verbindung gestartet",
  "channel.disconnect": "Kanal getrennt",
  "material.register": "Material registriert",
  "material.upload": "Material hochgeladen",
  "upload.create": "Upload begonnen",
  "upload.complete": "Upload abgeschlossen",
  "license.create": "Lizenz angelegt",
  "license.update": "Lizenz geändert",
  "license.document": "Lizenzdokument hinzugefügt",
  "license.expired": "Lizenz abgelaufen",
  "policy.set": "Publisher-Richtlinie gesetzt",
  "settings.controls.update": "Steuerung geändert",
  "strategy.rollback": "Strategie zurückgesetzt",
  "learning.rollback": "Lernstand zurückgesetzt",
  "trend_source.test": "Trendquelle getestet",
  "user.create": "Benutzer angelegt",
  "user.update": "Benutzer geändert",
};

const ENTITY: Record<string, string> = {
  variants: "Video",
  gameplay_files: "Material",
  channels: "Kanal",
  content_projects: "Themenbereich",
  licenses: "Lizenz",
  users: "Benutzer",
};

function activityIcon(a: DashboardActivity): [IconName, Tone] {
  if (a.action.endsWith("failed") || a.status_after === "FAILED")
    return ["alert", "danger"];
  if (a.kind === "agent") return ["bot", "info"];
  if (a.action.startsWith("upload") || a.action.startsWith("material"))
    return ["upload", "neutral"];
  if (a.status_after === "PUBLISHED") return ["check", "ok"];
  return ["activity", "neutral"];
}

function timeOnly(d: Date): string {
  return d.toLocaleTimeString("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function KpiCard({
  icon,
  label,
  value,
  hint,
  tone = "neutral",
}: {
  icon: IconName;
  label: string;
  value: string | number;
  hint?: string;
  tone?: Tone;
}) {
  return (
    <div className="card kpi">
      <span className={`kpi-icon tone-${tone}`}>
        <Icon name={icon} size={18} />
      </span>
      <div className="kpi-body">
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value}</div>
        {hint && <div className="stat-hint muted">{hint}</div>}
      </div>
    </div>
  );
}

function StateBar({ data }: { data: Dashboard }) {
  const segments = data.states.filter((s) => s.key !== "uploading");
  const total = segments.reduce((n, s) => n + s.count, 0);
  return (
    <Section title="Status aller Videos">
      <div
        className="state-bar"
        role="img"
        aria-label={segments
          .map((s) => `${STATE_META[s.key].label}: ${s.count}`)
          .join(", ")}
      >
        {total === 0 ? (
          <span className="state-bar-empty" />
        ) : (
          segments
            .filter((s) => s.count > 0)
            .map((s) => (
              <span
                key={s.key}
                style={{
                  flexGrow: s.count,
                  background: STATE_META[s.key].color,
                }}
                title={`${STATE_META[s.key].label}: ${s.count}`}
              />
            ))
        )}
      </div>
      <ul className="state-legend">
        {data.states.map((s) => (
          <li key={s.key}>
            <span
              className="dot"
              style={{ background: STATE_META[s.key].color }}
            />
            <span className="muted">{STATE_META[s.key].label}</span>
            <strong>{s.count}</strong>
          </li>
        ))}
      </ul>
      {total === 0 && (
        <p className="muted small">
          Noch keine Videos. Sie erscheinen hier, sobald Material analysiert und
          geschnitten wurde.
        </p>
      )}
    </Section>
  );
}

function PlatformCard({ tile }: { tile: PlatformTile }) {
  const [label, tone] = CONNECTION[tile.connection];
  return (
    <article className="card platform-tile" aria-label={tile.name}>
      <header>
        <PlatformMark code={tile.code} />
        <div className="platform-title">
          <h3>{tile.name}</h3>
          <span className="muted small">{tile.note}</span>
        </div>
      </header>
      <Badge tone={tone}>{label}</Badge>
      {tile.can_publish ? (
        <dl className="tile-stats">
          <div>
            <dt>Kanäle verbunden</dt>
            <dd>
              {tile.channels_connected} von {tile.channels}
            </dd>
          </div>
          <div>
            <dt>Veröffentlicht</dt>
            <dd>{tile.published}</dd>
          </div>
          <div>
            <dt>Testläufe</dt>
            <dd>{tile.test_posts}</dd>
          </div>
          <div>
            <dt>Offen / Fehler</dt>
            <dd>
              {tile.open_jobs} / {tile.failed_jobs}
            </dd>
          </div>
        </dl>
      ) : (
        <p className="muted small tile-note">
          Liefert Trends und Streamdaten. Videos können nicht zu Twitch
          hochgeladen werden.
        </p>
      )}
      {tile.can_publish && (
        <div className="muted small">
          Zuletzt:{" "}
          {tile.last_published_at
            ? formatDateTime(tile.last_published_at)
            : "noch nie"}
        </div>
      )}
    </article>
  );
}

export function OverviewView() {
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [data, setData] = useState<Overview | null>(null);
  const [ready, setReady] = useState<Readiness | null>(null);
  const [budget, setBudget] = useState<Budget | null>(null);
  const [costs, setCosts] = useState<CostSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    const [d, o, r, b, k] = await Promise.allSettled([
      api.dashboard(),
      api.overview(),
      api.readiness(),
      api.budget(),
      api.costSummary(),
    ]);
    setCosts(k.status === "fulfilled" ? k.value : null);
    if (d.status === "fulfilled") setDash(d.value);
    if (o.status === "fulfilled") setData(o.value);
    setReady(
      r.status === "fulfilled"
        ? r.value
        : { status: "degraded", database: false, redis: false },
    );
    setBudget(b.status === "fulfilled" ? b.value : null);
    const failed = [d, o].find((x) => x.status === "rejected");
    setError(
      failed && failed.status === "rejected"
        ? String(failed.reason?.message ?? failed.reason)
        : null,
    );
    setUpdated(new Date());
    setBusy(false);
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const c = dash?.controls ?? data?.controls;
  return (
    <>
      <div className="page-head-row">
        <PageHeader
          title="Übersicht"
          description="Alle Videos, Plattformen und Abläufe auf einen Blick."
        />
        <div className="refresh">
          <span className="muted small" aria-live="polite">
            {updated ? `Aktualisiert ${timeOnly(updated)}` : "Lade …"}
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

      <div className="grid kpis">
        <KpiCard
          icon="film"
          label="Videos gesamt"
          value={dash?.videos_total ?? "–"}
        />
        <KpiCard
          icon="check"
          label="Veröffentlicht"
          value={dash?.published ?? "–"}
          tone="ok"
        />
        <KpiCard
          icon="clock"
          label="Geplant"
          value={dash?.scheduled ?? "–"}
          tone="warn"
        />
        <KpiCard
          icon="layers"
          label="Unveröffentlicht"
          value={dash?.unpublished ?? "–"}
          hint="Entwurf, in Bearbeitung, bereit oder geplant"
          tone="info"
        />
        <KpiCard
          icon="alert"
          label="Fehlgeschlagen"
          value={dash?.failed ?? "–"}
          tone={dash && dash.failed > 0 ? "danger" : "neutral"}
        />
        <KpiCard
          icon="send"
          label="Aktive Kanäle"
          value={
            data ? `${data.channels_active} / ${data.channels_total}` : "–"
          }
          hint="Kanäle sind bis zur Einrichtung pausiert"
        />
        <KpiCard
          icon="coins"
          label="Kosten diesen Monat"
          value={
            costs
              ? formatEur(costs.costs.total)
              : budget
                ? formatEur(budget.spent_eur)
                : "–"
          }
          hint={
            budget
              ? `Engine-Budget: ${formatEur(budget.spent_eur)} von ${formatEur(budget.budget_eur)} (${budget.used_pct} %)`
              : undefined
          }
        />
      </div>

      {dash && <StateBar data={dash} />}

      <section aria-label="Plattformen" className="grid platforms">
        {dash?.platforms.map((t) => (
          <PlatformCard key={t.code} tile={t} />
        ))}
      </section>

      <div className="grid two">
        <Section title="Letzte Veröffentlichungen">
          {dash && dash.recent_posts.length === 0 && (
            <p className="muted">Noch nichts veröffentlicht.</p>
          )}
          <ul className="feed">
            {dash?.recent_posts.map((p) => (
              <li key={p.id}>
                <PlatformMark code={p.platform} size={26} />
                <div className="feed-body">
                  <div className="feed-title">
                    {p.title ?? `Video #${p.id}`}
                  </div>
                  <div className="muted small">
                    {p.channel} · {p.content_project} ·{" "}
                    {p.published_at ? formatDateTime(p.published_at) : "–"}
                  </div>
                </div>
                {p.is_mock ? (
                  <Badge>Test</Badge>
                ) : (
                  <Badge tone="ok">Live</Badge>
                )}
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Fehler">
          {dash && dash.failures.length === 0 && (
            <p className="muted">
              Keine fehlgeschlagenen Videos oder Veröffentlichungen.
            </p>
          )}
          <ul className="feed">
            {dash?.failures.map((f) => (
              <li key={`${f.kind}-${f.id}`}>
                <span className="feed-icon tone-danger">
                  <Icon name="alert" size={16} />
                </span>
                <div className="feed-body">
                  <div className="feed-title">
                    {f.title ??
                      (f.kind === "video"
                        ? `Video #${f.id}`
                        : `Auftrag #${f.id}`)}
                  </div>
                  <div className="muted small">
                    {f.kind === "video" ? "Produktion" : "Veröffentlichung"}
                    {f.channel ? ` · ${f.channel}` : ""} ·{" "}
                    {formatDateTime(f.at)}
                  </div>
                  {f.error && <div className="feed-error small">{f.error}</div>}
                </div>
              </li>
            ))}
          </ul>
          {dash && dash.failures.length > 0 && (
            <Link href="/produktion" className="small">
              Zur Videoproduktion
            </Link>
          )}
        </Section>
      </div>

      <div className="grid two">
        <Section title="Aktivitäten">
          {dash && dash.activity.length === 0 && (
            <p className="muted">Noch keine Aktivitäten.</p>
          )}
          <ul className="feed">
            {dash?.activity.map((a, i) => {
              const [icon, tone] = activityIcon(a);
              const entity =
                a.entity_type && a.entity_id
                  ? `${ENTITY[a.entity_type] ?? a.entity_type} #${a.entity_id}`
                  : null;
              return (
                <li key={`${a.at}-${i}`}>
                  <span className={`feed-icon tone-${tone}`}>
                    <Icon name={icon} size={16} />
                  </span>
                  <div className="feed-body">
                    <div className="feed-title">
                      {ACTIONS[a.action] ?? a.action}
                      {entity ? ` · ${entity}` : ""}
                      {a.status_before && a.status_after
                        ? ` (${a.status_before} → ${a.status_after})`
                        : ""}
                    </div>
                    <div className="muted small">
                      {a.actor ?? "System"} · {formatDateTime(a.at)}
                    </div>
                    {a.message && (
                      <div className="muted small feed-msg">{a.message}</div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>
        <Section title="Systemstatus">
          <dl className="kv">
            <dt>Backend</dt>
            <dd>
              {ready ? (
                <Badge tone={ready.status === "ok" ? "ok" : "danger"}>
                  {ready.status === "ok" ? "Bereit" : "Gestört"}
                </Badge>
              ) : (
                "–"
              )}
            </dd>
            <dt>Datenbank</dt>
            <dd>
              {ready ? (
                <Badge tone={ready.database ? "ok" : "danger"}>
                  {ready.database ? "OK" : "Fehler"}
                </Badge>
              ) : (
                "–"
              )}
            </dd>
            <dt>Warteschlange (Redis)</dt>
            <dd>
              {ready ? (
                <Badge tone={ready.redis ? "ok" : "danger"}>
                  {ready.redis ? "OK" : "Fehler"}
                </Badge>
              ) : (
                "–"
              )}
            </dd>
            <dt>Not-Aus</dt>
            <dd>
              {c ? (
                <Badge tone={c.emergency_stop ? "danger" : "ok"}>
                  {c.emergency_stop ? "Aktiv" : "Aus"}
                </Badge>
              ) : (
                "–"
              )}
            </dd>
            <dt>Automatische Veröffentlichung</dt>
            <dd>
              {c ? (
                <Badge tone={c.publishing_allowed ? "warn" : "neutral"}>
                  {c.publishing_allowed ? "Aktiv" : "Aus"}
                </Badge>
              ) : (
                "–"
              )}
            </dd>
            <dt>Publishing-Modus</dt>
            <dd>
              {c ? (
                <Badge tone={c.publishing_mode === "live" ? "warn" : "neutral"}>
                  {c.publishing_mode === "live" ? "Live" : "Mock (Test)"}
                </Badge>
              ) : (
                "–"
              )}
            </dd>
          </dl>
        </Section>
      </div>
      <TrendsPanel />
    </>
  );
}
