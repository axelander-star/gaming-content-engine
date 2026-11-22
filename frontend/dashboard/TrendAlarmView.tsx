"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type { TrendAlarm, TrendAlarmDraft, TrendAlarmInfo } from "@/lib/types";

const STATUS_LABELS: Record<string, string> = {
  drafting: "Entwürfe werden erstellt",
  ready: "Wartet auf Freigabe",
  approved: "Freigegeben",
  dismissed: "Verworfen",
  expired: "Abgelaufen",
  failed: "Keine Entwürfe",
};

const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  instagram: "Instagram",
  facebook: "Facebook",
};

const SOURCE_LABELS: Record<string, string> = {
  youtube_chart: "YouTube-Trends",
  competitor: "Konkurrenz-Radar",
};

function statusTone(status: string): "ok" | "warn" | "danger" | "neutral" {
  if (status === "ready") return "warn";
  if (status === "approved") return "ok";
  if (status === "failed") return "danger";
  return "neutral";
}

function scoreTone(score: number): "ok" | "warn" | "neutral" {
  return score >= 90 ? "ok" : score >= 75 ? "warn" : "neutral";
}

function DraftCard({
  alarm,
  draft,
  canDecide,
  busy,
  onApprove,
}: {
  alarm: TrendAlarm;
  draft: TrendAlarmDraft;
  canDecide: boolean;
  busy: boolean;
  onApprove: () => void;
}) {
  const chosen = alarm.approved_production_id === draft.production_id;
  const open = draft.posts.filter((p) => p.status === "quality_approved").length;
  return (
    <article className={`card trend-draft${chosen ? " is-chosen" : ""}`}>
      <div className="trend-draft-head">
        <span className="chip">{draft.angle ?? "Entwurf"}</span>
        {chosen && <Badge tone="ok">Gewählt</Badge>}
      </div>
      <h4>{draft.title ?? "Entwurf"}</h4>
      {draft.item_id !== null ? (
        <video
          controls
          preload="metadata"
          playsInline
          aria-label={`Entwurf ${draft.angle ?? ""}`}
          poster={api.libraryFileUrl(draft.item_id, "thumb")}
          src={api.libraryFileUrl(draft.item_id, "original")}
        />
      ) : (
        <p className="muted small">
          {draft.status === "failed"
            ? `Fehlgeschlagen: ${draft.error ?? "unbekannt"}`
            : "Wird gerade erstellt …"}
        </p>
      )}
      {draft.posts.length > 0 && (
        <ul className="trend-posts small">
          {draft.posts.map((p) => (
            <li key={p.variant_id}>
              {PLATFORM_LABELS[p.platform] ?? p.platform} · {p.channel}
              {p.status === "ready_to_publish" || p.status === "scheduled"
                ? " · freigegeben"
                : p.status === "published"
                  ? " · veröffentlicht"
                  : p.status === "archived"
                    ? " · verworfen"
                    : ""}
            </li>
          ))}
        </ul>
      )}
      {canDecide && alarm.status === "ready" && open > 0 && (
        <button
          type="button"
          className="btn btn-primary trend-approve"
          disabled={busy}
          onClick={onApprove}
        >
          Diesen freigeben und hochladen
        </button>
      )}
    </article>
  );
}

function AlarmCard({
  alarm,
  highlight,
  canDecide,
  onChange,
  onError,
}: {
  alarm: TrendAlarm;
  highlight: boolean;
  canDecide: boolean;
  onChange: (a: TrendAlarm) => void;
  onError: (msg: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<TrendAlarm>) {
    setBusy(true);
    try {
      onChange(await fn());
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      id={`alarm-${alarm.id}`}
      className={`card trend-alarm${highlight ? " is-highlight" : ""}`}
      aria-label={`Trend-Alarm ${alarm.title}`}
    >
      <div className="idea-head">
        <div>
          <h3>{alarm.title}</h3>
          <div className="idea-meta">
            <span className="chip">{alarm.project}</span>
            <span className="muted small">
              {SOURCE_LABELS[alarm.source] ?? alarm.source} · {formatDateTime(alarm.created_at)}
            </span>
            <Badge tone={statusTone(alarm.status)}>
              {STATUS_LABELS[alarm.status] ?? alarm.status}
            </Badge>
            {alarm.autopilot && <Badge tone="warn">Automatik</Badge>}
            {alarm.is_mock && <Badge>Testdaten</Badge>}
          </div>
        </div>
        <div className={`idea-score idea-score-${scoreTone(alarm.score)}`} title="Alarmwert">
          {alarm.score}
        </div>
      </div>
      <ul className="trend-facts">
        {alarm.facts.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>
      {alarm.url && (
        <p className="small">
          <a href={alarm.url} target="_blank" rel="noopener noreferrer nofollow">
            Original ansehen{alarm.creator ? ` (${alarm.creator})` : ""}
          </a>{" "}
          <span className="muted">– nur zum Anschauen, daraus wird nichts kopiert.</span>
        </p>
      )}
      {alarm.error && <p className="feed-error small">{alarm.error}</p>}
      {alarm.drafts.length > 0 && (
        <div className="trend-drafts">
          {alarm.drafts.map((d) => (
            <DraftCard
              key={d.production_id}
              alarm={alarm}
              draft={d}
              canDecide={canDecide}
              busy={busy}
              onApprove={() => act(() => api.approveTrendAlarm(alarm.id, d.production_id))}
            />
          ))}
        </div>
      )}
      {alarm.status === "ready" &&
        alarm.drafts.every((d) => d.posts.length === 0) &&
        alarm.drafts.some((d) => d.item_id !== null) && (
          <p className="muted small">
            Es gibt in diesem Themenbereich noch keinen passenden Kanal. Die Videos liegen in der
            Mediathek.
          </p>
        )}
      {canDecide && (alarm.status === "ready" || alarm.status === "drafting") && (
        <div className="idea-actions">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => act(() => api.dismissTrendAlarm(alarm.id))}
          >
            Alarm verwerfen
          </button>
        </div>
      )}
    </section>
  );
}

function AutopilotPanel({
  info,
  isAdmin,
  onChange,
  onError,
}: {
  info: TrendAlarmInfo;
  isAdmin: boolean;
  onChange: () => void;
  onError: (msg: string) => void;
}) {
  async function toggle(id: number, enabled: boolean) {
    try {
      await api.setTrendAutopilot(id, enabled);
      onChange();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <Section title="Vollautomatik je Kanal">
      <p className="muted small">
        Ist die Automatik an, gibt der Agent bei sehr starken Trends (ab {info.autopilot_min_score}{" "}
        Punkten) den ersten Entwurf für diesen Kanal selbst frei, ohne auf dich zu warten. Zeitpunkt
        und Menge bestimmt weiter der Publishing-Strategie-Agent.
      </p>
      {!info.autopilot_enabled && (
        <p className="notice small">
          Hauptschalter aus (<code>TREND_AUTOPILOT_ENABLED=false</code>): Die Schalter unten wirken
          erst, wenn er auf dem Server an ist. Bis dahin braucht jeder Alarm deine Freigabe.
        </p>
      )}
      {info.channels.length === 0 ? (
        <p className="muted small">Noch keine Kanäle.</p>
      ) : (
        <ul className="feed">
          {info.channels.map((c) => (
            <li key={c.id}>
              <div className="feed-body">
                <div className="feed-title">
                  {c.name} <span className="chip">{c.project}</span>
                </div>
                <div className="muted small">
                  {PLATFORM_LABELS[c.platform] ?? c.platform} · {c.language.toUpperCase()}
                  {c.is_paused ? " · pausiert" : ""}
                </div>
              </div>
              <Switch
                checked={c.trend_autopilot}
                disabled={!isAdmin}
                tone="danger"
                label={`Vollautomatik für ${c.name}`}
                onChange={(next) => toggle(c.id, next)}
              />
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

/** Trend alarm: hot topics with facts, ready drafts and the one-tap approval (Ausbau A11). */
export function TrendAlarmView() {
  const { user } = useAuth();
  const canDecide = hasRole(user?.role, "operator");
  const isAdmin = hasRole(user?.role, "admin");
  const [view, setView] = useState<"open" | "all">("open");
  const [alarms, setAlarms] = useState<TrendAlarm[] | null>(null);
  const [info, setInfo] = useState<TrendAlarmInfo | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .trendAlarms(view)
      .then(setAlarms)
      .catch((e: Error) => setError(e.message));
    api
      .trendAlarmInfo()
      .then(setInfo)
      .catch((e: Error) => setError(e.message));
  }, [view]);

  useEffect(load, [load]);

  // the push opens /trend-alarm?alarm=ID: show that alarm first, even if it is decided
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("alarm"));
    if (!id) return;
    setFocus(id);
    api
      .trendAlarm(id)
      .then((a) => setAlarms((list) => [a, ...(list ?? []).filter((x) => x.id !== a.id)]))
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (focus && alarms?.some((a) => a.id === focus)) {
      document.getElementById(`alarm-${focus}`)?.scrollIntoView({ block: "start" });
    }
  }, [focus, alarms]);

  async function scan() {
    setError(null);
    try {
      await api.scanTrendAlarms();
      setNotice(
        info?.mode === "live"
          ? "Prüfung läuft. Neue Alarme erscheinen hier und kommen aufs Handy."
          : "Prüfung mit Testdaten läuft. Ein Test-Alarm erscheint gleich hier.",
      );
      for (const ms of [4000, 10000, 25000, 60000]) setTimeout(load, ms);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function replace(a: TrendAlarm) {
    setAlarms((list) => (list ?? []).map((x) => (x.id === a.id ? a : x)));
    if (a.status === "approved") {
      setNotice(
        info?.publishing_mode === "live"
          ? "Freigegeben. Der Publishing-Agent lädt das Video zum nächsten passenden Zeitpunkt hoch."
          : "Freigegeben. Testmodus: Es wird nichts echt veröffentlicht.",
      );
    }
  }

  return (
    <>
      <PageHeader
        title="Trend-Alarm"
        description="Der Agent beobachtet YouTube-Trends und deinen Konkurrenz-Radar. Hebt ein Thema ab, erstellt er eigene Video-Entwürfe und schickt dir einen Alarm aufs Handy. Mit einem Tipp gibst du einen Entwurf frei."
      />
      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label="Alarme">
          {(
            [
              ["open", "Offen"],
              ["all", "Alle"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={view === key}
              className={`tab${view === key ? " is-active" : ""}`}
              onClick={() => setView(key)}
            >
              {label}
            </button>
          ))}
        </div>
        {isAdmin && (
          <button type="button" className="btn btn-primary" onClick={scan}>
            Jetzt prüfen
          </button>
        )}
      </div>
      {notice && <p className="notice">{notice}</p>}
      <ErrorText error={error} />
      <div className="chat-layout">
        <div className="idea-list">
          {alarms && alarms.length === 0 && (
            <p className="muted">
              {view === "open"
                ? "Gerade kein offener Alarm. Der Agent prüft regelmäßig und meldet sich auf dem Handy."
                : "Noch keine Alarme."}
            </p>
          )}
          {alarms?.map((a) => (
            <AlarmCard
              key={a.id}
              alarm={a}
              highlight={a.id === focus}
              canDecide={canDecide}
              onChange={replace}
              onError={setError}
            />
          ))}
        </div>
        <div className="side-stack">
          {info && (
            <Section title="So arbeitet der Alarm">
              <div className="ai-head">
                <Badge tone={info.mode === "live" ? "warn" : "neutral"}>
                  {info.mode === "live" ? "Live: echte YouTube-Daten" : "Test: Beispieldaten"}
                </Badge>
              </div>
              <ul className="source-list small">
                <li>
                  Alarm ab {info.threshold} von 100 Punkten, höchstens {info.max_per_day} am Tag.
                </li>
                <li>
                  Bewertet werden Reichweite, Tempo (Aufrufe pro Stunde), wie weit ein Video über
                  dem Üblichen liegt, Frische, Passung zum Themenbereich und passende Kampagnen.
                </li>
                <li>
                  Quellen: YouTube-Trends {info.regions.join(", ")} (ab{" "}
                  {info.min_views.toLocaleString("de-DE")} Aufrufen) und Konkurrenz-Radar.
                </li>
                <li>{info.drafts} Entwürfe je Alarm, alles eigene Videos mit eigener Stimme.</li>
                <li>
                  Handy:{" "}
                  {info.push_mode === "live" ? "Push ist an." : "Push im Testmodus, nur Glocke."}
                </li>
                <li>
                  Veröffentlichen:{" "}
                  {info.publishing_mode === "live" ? "echt" : "Testmodus, es geht nichts raus"}.
                </li>
              </ul>
              {info.mode === "mock" && (
                <p className="muted small">
                  Ohne YouTube-API-Schlüssel und <code>TREND_SOURCES_MODE=live</code> gibt es nur
                  Test-Alarme über „Jetzt prüfen“; automatisch wird dann nichts gemeldet.
                </p>
              )}
            </Section>
          )}
          {info && (
            <AutopilotPanel info={info} isAdmin={isAdmin} onChange={load} onError={setError} />
          )}
        </div>
      </div>
    </>
  );
}
