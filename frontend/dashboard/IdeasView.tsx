"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  ContentProject,
  Idea,
  IdeaSort,
  IdeaStatus,
  ResearchItem,
  ResearchSources,
} from "@/lib/types";

const STATUS_TABS: [IdeaStatus, string][] = [
  ["new", "Offen"],
  ["accepted", "Übernommen"],
  ["rejected", "Verworfen"],
];

const SORTS: [IdeaSort, string][] = [
  ["score", "Ranking (beste zuerst)"],
  ["trend", "Trend (heißeste zuerst)"],
  ["fit", "Passung"],
  ["title", "Name (A–Z)"],
  ["newest", "Datum (neueste zuerst)"],
  ["oldest", "Datum (älteste zuerst)"],
];

const PAGE_SIZE = 5;

function Pager({
  page,
  pages,
  total,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  onPage: (page: number) => void;
}) {
  if (total <= PAGE_SIZE) return null;
  return (
    <nav className="pager" aria-label="Seiten der Ideen">
      <button
        type="button"
        className="btn btn-ghost"
        disabled={page <= 0}
        onClick={() => onPage(page - 1)}
      >
        ← Zurück
      </button>
      <span className="muted small">
        Seite {page + 1} von {pages} · {total} Ideen
      </span>
      <button
        type="button"
        className="btn btn-ghost"
        disabled={page >= pages - 1}
        onClick={() => onPage(page + 1)}
      >
        Weiter →
      </button>
    </nav>
  );
}

const FORMAT_LABELS: Record<string, string> = {
  short: "Kurzvideo",
  explainer: "Erklärvideo",
  long: "Langes Video",
};

function scoreTone(score: number): "ok" | "warn" | "neutral" {
  return score >= 70 ? "ok" : score >= 50 ? "warn" : "neutral";
}

function ScoreBar({ label, value, inverse }: { label: string; value: number; inverse?: boolean }) {
  const good = inverse ? 100 - value : value;
  return (
    <div className="score-bar">
      <span className="muted small">{label}</span>
      <div className="meter" role="meter" aria-label={label} aria-valuenow={value}>
        <span
          style={{ width: `${value}%` }}
          className={good >= 60 ? undefined : good >= 40 ? "meter-warn" : "meter-danger"}
        />
      </div>
      <span className="small">{value}</span>
    </div>
  );
}

function IdeaCard({
  idea,
  rank,
  canDecide,
  onChange,
  onError,
}: {
  idea: Idea;
  rank?: number;
  canDecide: boolean;
  onChange: () => void;
  onError: (msg: string) => void;
}) {
  const [day, setDay] = useState("");
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      onChange();
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="card idea-card" aria-label={`Idee ${idea.title}`}>
      <div className="idea-head">
        <div>
          <h3>
            {rank !== undefined && <span className="idea-rank">#{rank}</span>}
            {idea.title}
          </h3>
          <div className="idea-meta">
            <span className="chip">{idea.project}</span>
            <span className="muted small">{FORMAT_LABELS[idea.format] ?? idea.format}</span>
            {idea.provider === "mock" && <Badge>Testidee</Badge>}
          </div>
        </div>
        <div className={`idea-score idea-score-${scoreTone(idea.score)}`} title="Gesamtbewertung">
          {idea.score}
        </div>
      </div>
      <p>{idea.pitch}</p>
      <div className="score-grid">
        <ScoreBar label="Trend" value={idea.trend_score} />
        <ScoreBar label="Passung" value={idea.fit_score} />
        <ScoreBar label="Aufwand" value={idea.effort_score} inverse />
        <ScoreBar label="Rechte-Risiko" value={idea.rights_risk} inverse />
      </div>
      <p className="muted small">{idea.reasoning}</p>
      {idea.sources.length > 0 && (
        <details>
          <summary>Quellen ({idea.sources.length})</summary>
          <ul className="source-list">
            {idea.sources.map((s, i) => (
              <li key={`${s.item_id ?? i}`}>
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noopener noreferrer nofollow">
                    {s.title}
                  </a>
                ) : (
                  s.title
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {canDecide && idea.status === "new" && (
        <div className="idea-actions">
          <label className="inline-label">
            Tag im Plan (optional)
            <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => act(() => api.acceptIdea(idea.id, day || null))}
          >
            Übernehmen
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => act(() => api.rejectIdea(idea.id))}
          >
            Verwerfen
          </button>
        </div>
      )}
      {idea.status !== "new" && (
        <div className="idea-actions">
          <Badge tone={idea.status === "accepted" ? "ok" : "neutral"}>
            {idea.status === "accepted"
              ? idea.planned_for
                ? `Übernommen für ${new Date(`${idea.planned_for}T12:00:00`).toLocaleDateString("de-DE")}`
                : "Übernommen"
              : "Verworfen"}
          </Badge>
          {canDecide && (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              disabled={busy}
              onClick={() => act(() => api.reopenIdea(idea.id))}
            >
              Wieder öffnen
            </button>
          )}
        </div>
      )}
    </article>
  );
}

function SourcesPanel({
  sources,
  projects,
  isAdmin,
  onChange,
  onError,
}: {
  sources: ResearchSources | null;
  projects: ContentProject[];
  isAdmin: boolean;
  onChange: () => void;
  onError: (msg: string) => void;
}) {
  const [projectId, setProjectId] = useState<number | "">("");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");

  async function onAdd(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (projectId === "") return;
    try {
      await api.createResearchSource({ content_project_id: projectId, name, url });
      setName("");
      setUrl("");
      onChange();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn();
      onChange();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  if (!sources) return null;
  return (
    <Section title="Recherche-Quellen">
      <div className="ai-head">
        <Badge tone={sources.mode === "live" ? "warn" : "neutral"}>
          {sources.mode === "live" ? "Live: Feeds werden abgerufen" : "Test: Beispiel-Feeds, kein Abruf"}
        </Badge>
      </div>
      {sources.sources.length === 0 ? (
        <p className="muted small">
          Noch keine Feeds. Im Testmodus nutzt jeder Themenbereich einen Beispiel-Feed aus seinen
          Unterthemen.
        </p>
      ) : (
        <ul className="feed">
          {sources.sources.map((s) => (
            <li key={s.id}>
              <div className="feed-body">
                <div className="feed-title">
                  {s.name} <span className="chip">{s.project}</span>
                </div>
                <div className="muted small">{s.url}</div>
                <div className="muted small">
                  {s.enabled ? "aktiv" : "aus"} · {s.items} Einträge
                  {s.last_fetched_at && ` · zuletzt ${formatDateTime(s.last_fetched_at)}`}
                </div>
                {s.last_error && <div className="feed-error small">{s.last_error}</div>}
              </div>
              {isAdmin && (
                <div className="row-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    onClick={() => run(() => api.updateResearchSource(s.id, { enabled: !s.enabled }))}
                  >
                    {s.enabled ? "Ausschalten" : "Einschalten"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    aria-label={`Quelle ${s.name} löschen`}
                    onClick={() => run(() => api.deleteResearchSource(s.id))}
                  >
                    Löschen
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {isAdmin && (
        <form className="source-form" aria-label="Neue Quelle" onSubmit={onAdd}>
          <label>
            Themenbereich
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
              required
            >
              <option value="">Bitte wählen</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Name
            <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            Feed-Adresse (RSS oder Atom)
            <input
              type="url"
              value={url}
              placeholder="https://…"
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </label>
          <button type="submit" className="btn btn-ghost">
            Quelle hinzufügen
          </button>
        </form>
      )}
    </Section>
  );
}

/** Idea lab: scored ideas from research feeds, accept into the plan or reject (extension E5). */
export function IdeasView() {
  const { user } = useAuth();
  const canDecide = hasRole(user?.role, "operator");
  const isAdmin = hasRole(user?.role, "admin");
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [projectId, setProjectId] = useState<number | undefined>(undefined);
  const [status, setStatus] = useState<IdeaStatus>("new");
  const [sort, setSort] = useState<IdeaSort>("score");
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [ideas, setIdeas] = useState<Idea[] | null>(null);
  const [items, setItems] = useState<ResearchItem[]>([]);
  const [sources, setSources] = useState<ResearchSources | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .ideasPage({ projectId, status, sort, offset: page * PAGE_SIZE, limit: PAGE_SIZE })
      .then((res) => {
        // a decision can empty the last page: step back instead of showing nothing
        if (res.items.length === 0 && res.total > 0 && page > 0) {
          setPage(Math.max(0, Math.ceil(res.total / PAGE_SIZE) - 1));
          return;
        }
        setTotal(res.total);
        setIdeas(res.items);
      })
      .catch((e: Error) => setError(e.message));
    api
      .researchItems(projectId, 15)
      .then(setItems)
      .catch((e: Error) => setError(e.message));
    api
      .researchSources()
      .then(setSources)
      .catch((e: Error) => setError(e.message));
  }, [projectId, status, sort, page]);

  useEffect(() => {
    api
      .projects()
      .then((all) => setProjects(all.filter((p) => p.status !== "archived")))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function startResearch() {
    setError(null);
    try {
      await api.runResearch(projectId);
      setNotice("Recherche und Ideenlabor laufen. Neue Ideen erscheinen hier in Kürze.");
      for (const ms of [3000, 8000, 15000]) setTimeout(load, ms);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Ideenlabor"
        description="Ideen aus der Recherche mit Quellen und Bewertung. Übernommene Ideen kommen auf den Redaktionsplan; produziert oder veröffentlicht wird dadurch nichts."
      />
      <div className="toolbar">
        <label className="inline-label">
          Themenbereich
          <select
            value={projectId ?? ""}
            onChange={(e) => {
              setProjectId(e.target.value ? Number(e.target.value) : undefined);
              setPage(0);
            }}
          >
            <option value="">Alle</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <div className="tabs" role="tablist" aria-label="Status der Ideen">
          {STATUS_TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={status === key}
              className={`tab${status === key ? " is-active" : ""}`}
              onClick={() => {
                setStatus(key);
                setPage(0);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="inline-label">
          Sortieren nach
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as IdeaSort);
              setPage(0);
            }}
          >
            {SORTS.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {isAdmin && (
          <button type="button" className="btn btn-primary" onClick={startResearch}>
            Recherche starten
          </button>
        )}
      </div>
      {notice && <p className="notice">{notice}</p>}
      <ErrorText error={error} />
      <div className="chat-layout">
        <div className="idea-list">
          {ideas && ideas.length === 0 && (
            <p className="muted">
              {status === "new"
                ? "Keine offenen Ideen. Starte eine Recherche oder warte auf den nächsten Lauf."
                : "Keine Ideen in dieser Ansicht."}
            </p>
          )}
          {ideas?.map((idea, i) => (
            <IdeaCard
              key={idea.id}
              idea={idea}
              rank={sort === "score" ? page * PAGE_SIZE + i + 1 : undefined}
              canDecide={canDecide}
              onChange={load}
              onError={setError}
            />
          ))}
          <Pager
            page={page}
            pages={Math.max(1, Math.ceil(total / PAGE_SIZE))}
            total={total}
            onPage={(p) => {
              setPage(p);
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          />
        </div>
        <div className="side-stack">
          <SourcesPanel
            sources={sources}
            projects={projects}
            isAdmin={isAdmin}
            onChange={load}
            onError={setError}
          />
          <Section title="Neueste Einträge">
            {items.length === 0 ? (
              <p className="muted small">Noch nichts gesammelt.</p>
            ) : (
              <ul className="source-list">
                {items.map((i) => (
                  <li key={i.id}>
                    {i.url ? (
                      <a href={i.url} target="_blank" rel="noopener noreferrer nofollow">
                        {i.title}
                      </a>
                    ) : (
                      i.title
                    )}
                    <div className="muted small">
                      {i.source ?? "Quelle gelöscht"}
                      {i.published_at && ` · ${formatDateTime(i.published_at)}`}
                      {i.used && " · verwendet"}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      </div>
    </>
  );
}
