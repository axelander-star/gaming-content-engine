"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { formatSeconds } from "@/dashboard/LibraryView";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  ContentProject,
  Idea,
  Language,
  LibraryItem,
  Production,
  ProductionSegment,
  ProductionStatus,
} from "@/lib/types";

const STATUS: Record<ProductionStatus, [string, "neutral" | "ok" | "warn" | "danger" | "info"]> =
  {
    draft: ["Entwurf", "neutral"],
    queued: ["Wartet", "info"],
    rendering: ["Wird gerendert", "warn"],
    done: ["Fertig", "ok"],
    failed: ["Fehler", "danger"],
  };

const SOURCE_LABELS: Record<string, string> = {
  mock: "Testskript",
  claude: "Claude",
  manual: "von Hand",
};

function sourceLabel(source: string): string {
  return source
    .split("+")
    .map((s) => SOURCE_LABELS[s] ?? s)
    .join(", bearbeitet ");
}

function NewProduction({
  projects,
  onCreated,
  onError,
}: {
  projects: ContentProject[];
  onCreated: (p: Production) => void;
  onError: (msg: string) => void;
}) {
  const [projectId, setProjectId] = useState<number | "">("");
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [ideaId, setIdeaId] = useState<number | "">("");
  const [topic, setTopic] = useState("");
  const [language, setLanguage] = useState<Language>("de");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (projectId === "") {
      setIdeas([]);
      return;
    }
    api
      .ideas({ projectId, status: "accepted" })
      .then(setIdeas)
      .catch(() => setIdeas([]));
  }, [projectId]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (projectId === "") return;
    setBusy(true);
    try {
      const created = await api.createProduction({
        project_id: projectId,
        idea_id: ideaId === "" ? null : ideaId,
        topic: ideaId === "" ? topic : null,
        language,
      });
      setTopic("");
      setIdeaId("");
      onCreated(created);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Neue Produktion">
      <p className="muted small">
        Das Skript entsteht aus einer übernommenen Idee oder einem Thema. Danach kannst du jeden
        Abschnitt ändern und eigene Bilder aus der Mediathek zuordnen.
      </p>
      <form className="source-form" aria-label="Neue Produktion" onSubmit={submit}>
        <label>
          Themenbereich
          <select
            value={projectId}
            onChange={(e) => {
              setProjectId(e.target.value ? Number(e.target.value) : "");
              setIdeaId("");
            }}
            required
          >
            <option value="">Bitte wählen</option>
            {projects
              .filter((p) => p.status === "active")
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Übernommene Idee (optional)
          <select
            value={ideaId}
            onChange={(e) => setIdeaId(e.target.value ? Number(e.target.value) : "")}
          >
            <option value="">Keine, eigenes Thema</option>
            {ideas.map((i) => (
              <option key={i.id} value={i.id}>
                {i.title}
              </option>
            ))}
          </select>
        </label>
        {ideaId === "" && (
          <label>
            Thema
            <input
              value={topic}
              maxLength={300}
              placeholder="z. B. Haferflocken richtig lagern"
              onChange={(e) => setTopic(e.target.value)}
              required
            />
          </label>
        )}
        <label>
          Sprache
          <select value={language} onChange={(e) => setLanguage(e.target.value as Language)}>
            <option value="de">Deutsch</option>
            <option value="en">Englisch</option>
          </select>
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Skript entsteht …" : "Skript erstellen"}
        </button>
      </form>
    </Section>
  );
}

function Editor({
  production,
  images,
  canEdit,
  onSaved,
  onError,
}: {
  production: Production;
  images: LibraryItem[];
  canEdit: boolean;
  onSaved: (p: Production) => void;
  onError: (msg: string) => void;
}) {
  const [title, setTitle] = useState(production.title);
  const [segments, setSegments] = useState<ProductionSegment[]>(production.segments);
  const [busy, setBusy] = useState(false);
  const busyState = production.status === "queued" || production.status === "rendering";
  const editable = canEdit && !busyState;
  const dirty =
    title !== production.title || JSON.stringify(segments) !== JSON.stringify(production.segments);

  useEffect(() => {
    setTitle(production.title);
    setSegments(production.segments);
  }, [production]);

  function change(i: number, patch: Partial<ProductionSegment>) {
    setSegments(segments.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  }

  function move(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= segments.length) return;
    const next = [...segments];
    const [moved] = next.splice(i, 1);
    if (moved) next.splice(j, 0, moved);
    setSegments(next);
  }

  async function run(fn: () => Promise<Production>) {
    setBusy(true);
    try {
      onSaved(await fn());
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    await run(() => api.updateProduction(production.id, { title, segments }));
  }

  async function render() {
    await run(async () => {
      if (dirty) await api.updateProduction(production.id, { title, segments });
      return api.renderProduction(production.id);
    });
  }

  const [label, tone] = STATUS[production.status];
  const result = production.result;

  return (
    <Section title={production.title}>
      <div className="idea-meta">
        <span className="chip">{production.project}</span>
        <Badge tone={tone}>{label}</Badge>
        <span className="muted small">
          Skript: {sourceLabel(production.script_source)} · {production.language.toUpperCase()}
        </span>
      </div>
      {production.error_message && <p className="feed-error small">{production.error_message}</p>}

      {production.status === "done" && production.output_item_id !== null && (
        <div className="prod-result">
          <video
            controls
            preload="metadata"
            aria-label="Fertiges Video"
            poster={api.libraryFileUrl(production.output_item_id, "thumb")}
            src={api.libraryFileUrl(production.output_item_id, "original")}
          />
          <div>
            <p className="small">
              {formatSeconds(production.duration_s)} Video, gerendert in{" "}
              {production.render_seconds?.toFixed(1)} s
              {result.realtime_factor ? ` (${result.realtime_factor}× Echtzeit)` : ""}.
            </p>
            <p className="muted small">
              Stimme: {result.voice?.provider === "mock" ? "Test (stumm)" : result.voice?.provider}{" "}
              · {result.cues ?? 0} Untertitel
              {production.rendered_at && ` · ${formatDateTime(production.rendered_at)}`}
            </p>
            {(result.subtitle_issues ?? []).length > 0 && (
              <ul className="small">
                {(result.subtitle_issues ?? []).map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            )}
            <div className="row-actions">
              <a className="btn btn-ghost btn-small" href={api.productionSubtitlesUrl(production.id, "srt")}>
                SRT
              </a>
              <a className="btn btn-ghost btn-small" href={api.productionSubtitlesUrl(production.id, "vtt")}>
                WebVTT
              </a>
            </div>
            <p className="muted small">
              Liegt in der Mediathek. Freigabe und Veröffentlichung folgen im Freigabecenter.
            </p>
          </div>
        </div>
      )}

      <label className="stack-label">
        Titel
        <input
          value={title}
          maxLength={200}
          disabled={!editable}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <ol className="seg-list">
        {segments.map((s, i) => (
          <li key={i} className="seg" aria-label={`Abschnitt ${i + 1}`}>
            <div className="seg-head">
              <strong>Abschnitt {i + 1}</strong>
              {editable && (
                <div className="row-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    aria-label={`Abschnitt ${i + 1} nach oben`}
                    onClick={() => move(i, -1)}
                    disabled={i === 0}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    aria-label={`Abschnitt ${i + 1} nach unten`}
                    onClick={() => move(i, 1)}
                    disabled={i === segments.length - 1}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    aria-label={`Abschnitt ${i + 1} entfernen`}
                    onClick={() => setSegments(segments.filter((_, j) => j !== i))}
                    disabled={segments.length === 1}
                  >
                    Entfernen
                  </button>
                </div>
              )}
            </div>
            <label>
              Überschrift im Bild
              <input
                value={s.headline}
                maxLength={60}
                disabled={!editable}
                onChange={(e) => change(i, { headline: e.target.value })}
              />
            </label>
            <label>
              Sprechtext (wird zu Untertiteln)
              <textarea
                value={s.text}
                maxLength={400}
                rows={2}
                disabled={!editable}
                onChange={(e) => change(i, { text: e.target.value })}
              />
            </label>
            <label>
              Bild
              <select
                value={s.image_item_id ?? ""}
                disabled={!editable}
                onChange={(e) =>
                  change(i, { image_item_id: e.target.value ? Number(e.target.value) : null })
                }
              >
                <option value="">Farbfläche</option>
                {images.map((img) => (
                  <option key={img.id} value={img.id}>
                    {img.title}
                  </option>
                ))}
              </select>
            </label>
          </li>
        ))}
      </ol>
      {editable && (
        <div className="row-actions">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={segments.length >= 12}
            onClick={() => setSegments([...segments, { headline: "", text: "", image_item_id: null }])}
          >
            Abschnitt hinzufügen
          </button>
          <button type="button" className="btn btn-ghost" disabled={busy || !dirty} onClick={save}>
            Speichern
          </button>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={render}>
            Video erzeugen
          </button>
        </div>
      )}
    </Section>
  );
}

/** Own production: script, voice, own pictures and subtitles into a 9:16 video (extension E7). */
export function OwnProductionView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "operator");
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [productions, setProductions] = useState<Production[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [images, setImages] = useState<LibraryItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .productions()
      .then((all) => {
        setProductions(all);
        setSelected((cur) => cur ?? all[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    api
      .projects()
      .then((all) => setProjects(all.filter((p) => p.status !== "archived")))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const current = productions?.find((p) => p.id === selected) ?? null;
  const currentProject = current?.project_id;

  useEffect(() => {
    if (currentProject === undefined) return;
    api
      .library({ projectId: currentProject, kind: "image", status: "ready" })
      .then(setImages)
      .catch(() => setImages([]));
  }, [currentProject]);

  const running = productions?.some((p) => p.status === "queued" || p.status === "rendering");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [running, load]);

  function saved(p: Production) {
    setError(null);
    setProductions((all) => (all ? all.map((x) => (x.id === p.id ? p : x)) : [p]));
  }

  return (
    <>
      <PageHeader
        title="Eigenproduktion"
        description="Videos ohne fremdes Material: Skript, Stimme, eigene Bilder oder Farbflächen, Untertitel. Fertige Videos landen in der Mediathek; veröffentlicht wird nichts."
      />
      <ErrorText error={error} />
      <div className="chat-layout">
        <div className="side-stack">
          {current ? (
            <Editor
              production={current}
              images={images}
              canEdit={canEdit}
              onSaved={saved}
              onError={setError}
            />
          ) : (
            <p className="muted">Noch keine Produktion. Lege rechts eine an.</p>
          )}
        </div>
        <div className="side-stack">
          {canEdit && (
            <NewProduction
              projects={projects}
              onCreated={(p) => {
                setError(null);
                setProductions((all) => [p, ...(all ?? [])]);
                setSelected(p.id);
              }}
              onError={setError}
            />
          )}
          <Section title="Produktionen">
            {productions && productions.length === 0 && <p className="muted small">Noch keine.</p>}
            <ul className="feed">
              {productions?.map((p) => {
                const [label, tone] = STATUS[p.status];
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      className={`prod-pick${p.id === selected ? " is-active" : ""}`}
                      onClick={() => setSelected(p.id)}
                    >
                      <span className="feed-title">{p.title}</span>
                      <span className="muted small">
                        {p.project} · <Badge tone={tone}>{label}</Badge>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Section>
        </div>
      </div>
    </>
  );
}
