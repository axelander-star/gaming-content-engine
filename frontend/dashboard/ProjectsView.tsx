"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  Channel,
  ContentProject,
  ContentProjectInput,
  ContentProjectStatus,
  Language,
  PlatformCode,
  TopicSuggestion,
  TopicSuggestions,
} from "@/lib/types";

const STATUS_LABELS: Record<ContentProjectStatus, string> = {
  active: "Aktiv",
  paused: "Pausiert",
  archived: "Archiviert",
};
const STATUS_TONES: Record<ContentProjectStatus, "ok" | "warn" | "neutral"> = {
  active: "ok",
  paused: "warn",
  archived: "neutral",
};
const LANGUAGES: Language[] = ["de", "en"];
const PLATFORMS: PlatformCode[] = [
  "youtube",
  "instagram",
  "tiktok",
  "facebook",
];

interface Draft {
  name: string;
  description: string;
  audience: string;
  tone: string;
  subtopics: string;
  languages: Language[];
  priority: number;
}

const EMPTY_DRAFT: Draft = {
  name: "",
  description: "",
  audience: "",
  tone: "",
  subtopics: "",
  languages: ["de"],
  priority: 100,
};

function toDraft(p: ContentProject): Draft {
  return {
    name: p.name,
    description: p.description ?? "",
    audience: p.audience ?? "",
    tone: p.tone ?? "",
    subtopics: p.subtopics.join(", "),
    languages: p.languages,
    priority: p.priority,
  };
}

function fromDraft(d: Draft): ContentProjectInput {
  const text = (v: string) => (v.trim() ? v.trim() : null);
  return {
    name: d.name.trim(),
    description: text(d.description),
    audience: text(d.audience),
    tone: text(d.tone),
    subtopics: d.subtopics
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean),
    languages: d.languages,
    priority: d.priority,
  };
}

function ProjectForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: Draft;
  submitLabel: string;
  onSubmit: (input: ContentProjectInput) => Promise<void>;
  onCancel?: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (draft.languages.length === 0) {
      setError("Mindestens eine Sprache auswählen.");
      return;
    }
    setBusy(true);
    try {
      await onSubmit(fromDraft(draft));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="project-form" onSubmit={(e) => void submit(e)}>
      <div className="form-grid">
        <label>
          Name
          <input
            required
            maxLength={120}
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
          />
        </label>
        <label>
          Unterthemen (mit Komma getrennt)
          <input
            value={draft.subtopics}
            placeholder="z. B. Rezepte, Lebensmittelwissen"
            onChange={(e) => set("subtopics", e.target.value)}
          />
        </label>
        <label>
          Zielgruppe
          <input
            value={draft.audience}
            onChange={(e) => set("audience", e.target.value)}
          />
        </label>
        <label>
          Tonalität
          <input
            value={draft.tone}
            placeholder="z. B. locker, sachlich"
            onChange={(e) => set("tone", e.target.value)}
          />
        </label>
        <label>
          Priorität (kleiner = wichtiger)
          <input
            type="number"
            min={0}
            max={1000}
            value={draft.priority}
            onChange={(e) => set("priority", Number(e.target.value))}
          />
        </label>
        <fieldset className="lang-choice">
          <legend>Sprachen</legend>
          {LANGUAGES.map((lang) => (
            <label key={lang} className="check">
              <input
                type="checkbox"
                checked={draft.languages.includes(lang)}
                onChange={(e) =>
                  set(
                    "languages",
                    e.target.checked
                      ? [...draft.languages, lang]
                      : draft.languages.filter((l) => l !== lang),
                  )
                }
              />
              {lang.toUpperCase()}
            </label>
          ))}
        </fieldset>
      </div>
      <label>
        Beschreibung
        <textarea
          rows={2}
          maxLength={2000}
          value={draft.description}
          onChange={(e) => set("description", e.target.value)}
        />
      </label>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Abbrechen
          </button>
        )}
        <ErrorText error={error} />
      </div>
    </form>
  );
}

function ProjectCard({
  project,
  isAdmin,
  onChanged,
}: {
  project: ContentProject;
  isAdmin: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function setStatus(status: ContentProjectStatus) {
    try {
      await api.updateProject(project.id, { status });
      setError(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <article
      className="card project-card"
      aria-label={`Themenbereich ${project.name}`}
    >
      <header className="project-head">
        <h3>{project.name}</h3>
        <Badge tone={STATUS_TONES[project.status]}>
          {STATUS_LABELS[project.status]}
        </Badge>
        {project.is_default && <Badge>Standard</Badge>}
      </header>
      {project.description && <p className="muted">{project.description}</p>}
      {project.subtopics.length > 0 && (
        <ul className="chips" aria-label="Unterthemen">
          {project.subtopics.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      )}
      <dl className="project-stats">
        <div>
          <dt>Kanäle</dt>
          <dd>{project.channels}</dd>
        </div>
        <div>
          <dt>Material</dt>
          <dd>{project.materials}</dd>
        </div>
        <div>
          <dt>Videos</dt>
          <dd>{project.videos}</dd>
        </div>
        <div>
          <dt>Veröffentlicht</dt>
          <dd>{project.published}</dd>
        </div>
      </dl>
      <p className="muted small">
        Sprachen: {project.languages.map((l) => l.toUpperCase()).join(", ")}
        {project.tone ? ` · Ton: ${project.tone}` : ""}
        {project.audience ? ` · Zielgruppe: ${project.audience}` : ""}
      </p>
      {isAdmin && !editing && (
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setEditing(true)}
          >
            Bearbeiten
          </button>
          {project.status === "active" ? (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => void setStatus("paused")}
              title="Stoppt Produktion und Veröffentlichung dieses Themenbereichs"
            >
              Pausieren
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => void setStatus("active")}
            >
              Aktivieren
            </button>
          )}
          {(!project.is_default || project.channels === 0) &&
            project.status !== "archived" && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => void setStatus("archived")}
              >
                Archivieren
              </button>
            )}
        </div>
      )}
      {editing && (
        <ProjectForm
          initial={toDraft(project)}
          submitLabel="Speichern"
          onCancel={() => setEditing(false)}
          onSubmit={async (input) => {
            await api.updateProject(project.id, input);
            setEditing(false);
            onChanged();
          }}
        />
      )}
      <ErrorText error={error} />
    </article>
  );
}

function ChannelAssignment({
  channels,
  projects,
  isAdmin,
  onChanged,
}: {
  channels: Channel[];
  projects: ContentProject[];
  isAdmin: boolean;
  onChanged: () => void;
}) {
  const usable = projects.filter((p) => p.status !== "archived");
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    platform: "youtube" as PlatformCode,
    language: "de" as Language,
    name: "",
    content_project_id: usable[0]?.id ?? 0,
  });

  async function move(channel: Channel, projectId: number) {
    try {
      await api.moveChannel(channel.id, projectId);
      setError(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.createChannel({
        ...form,
        content_project_id: form.content_project_id || (usable[0]?.id ?? 0),
      });
      setForm({ ...form, name: "" });
      setError(null);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <Section title="Kanäle nach Themenbereich">
      <p className="muted small">
        Jeder Kanal gehört zu genau einem Themenbereich. Inhalte eines
        Themenbereichs können nur auf dessen Kanälen erscheinen; das prüft das
        System bei jedem Speichern und vor jeder Veröffentlichung. Ein Kanal mit
        Videos kann den Themenbereich nicht mehr wechseln.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Kanal</th>
              <th>Plattform</th>
              <th>Sprache</th>
              <th>Themenbereich</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{PLATFORM_LABELS[c.platform]}</td>
                <td>{c.language.toUpperCase()}</td>
                <td>
                  {isAdmin ? (
                    <select
                      aria-label={`Themenbereich von ${c.name}`}
                      value={c.content_project_id}
                      onChange={(e) => void move(c, Number(e.target.value))}
                    >
                      {projects
                        .filter(
                          (p) =>
                            p.status !== "archived" ||
                            p.id === c.content_project_id,
                        )
                        .map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                    </select>
                  ) : (
                    c.content_project
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {isAdmin && usable.length > 0 && (
        <form
          className="inline-form"
          onSubmit={(e) => void create(e)}
          aria-label="Neuer Kanal"
        >
          <select
            aria-label="Plattform"
            value={form.platform}
            onChange={(e) =>
              setForm({ ...form, platform: e.target.value as PlatformCode })
            }
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {PLATFORM_LABELS[p]}
              </option>
            ))}
          </select>
          <select
            aria-label="Sprache"
            value={form.language}
            onChange={(e) =>
              setForm({ ...form, language: e.target.value as Language })
            }
          >
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>
                {l.toUpperCase()}
              </option>
            ))}
          </select>
          <input
            aria-label="Kanalname"
            required
            maxLength={120}
            placeholder="Kanalname"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <select
            aria-label="Themenbereich des neuen Kanals"
            value={form.content_project_id || usable[0]?.id}
            onChange={(e) =>
              setForm({ ...form, content_project_id: Number(e.target.value) })
            }
          >
            {usable.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button type="submit" className="btn btn-primary">
            Kanal anlegen
          </button>
        </form>
      )}
      {isAdmin && (
        <p className="muted small">
          Neue Kanäle starten pausiert, nicht verbunden und mit Obergrenze 0.
          Verbinden und Grenzen setzen unter Einstellungen.
        </p>
      )}
      <ErrorText error={error} />
    </Section>
  );
}

export function ProjectsView() {
  const { user } = useAuth();
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<Draft | null>(null);
  const [suggestions, setSuggestions] = useState<TopicSuggestions | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [created, setCreated] = useState<string | null>(null);

  async function suggest() {
    setSuggesting(true);
    setCreated(null);
    try {
      setSuggestions(await api.suggestTopics());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSuggesting(false);
    }
  }

  const load = useCallback(() => {
    Promise.all([api.projects(), api.channels()])
      .then(([p, c]) => {
        setProjects(p);
        setChannels(c);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  if (!user) return null;
  const isAdmin = hasRole(user.role, "admin");
  const active = projects.filter((p) => p.status !== "archived");
  const archived = projects.filter((p) => p.status === "archived");

  return (
    <>
      <PageHeader
        title="Themenbereiche"
        description="Deine Themen mit eigenen Kanälen, Themen und Einstellungen. Es erscheint nur, was du selbst anlegst."
      />
      <ErrorText error={error} />
      {isAdmin && (
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={suggesting}
            onClick={() => void suggest()}
          >
            {suggesting ? "Trends werden ausgewertet …" : "Themen vorschlagen"}
          </button>
          {!creating && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => setCreating(EMPTY_DRAFT)}
            >
              Neuer Themenbereich
            </button>
          )}
        </div>
      )}
      {created && (
        <p role="status" className="muted">
          „{created}“ ist angelegt. Weiter geht es im{" "}
          <a href="/kanal-assistent">Kanal-Assistenten</a>: dort bekommst du
          Name, Beschreibung, Profilbild und Banner für den ersten Kanal.
        </p>
      )}
      {suggestions && !creating && (
        <SuggestionList
          result={suggestions}
          onTake={(s) => {
            setCreating(suggestionDraft(s));
            window.scrollTo({ top: 0, behavior: "smooth" });
          }}
          onClose={() => setSuggestions(null)}
        />
      )}
      {creating && (
        <Section title="Neuer Themenbereich">
          <ProjectForm
            key={creating.name}
            initial={creating}
            submitLabel="Anlegen"
            onCancel={() => setCreating(null)}
            onSubmit={async (input) => {
              await api.createProject(input);
              setCreating(null);
              setSuggestions(null);
              setCreated(input.name);
              load();
            }}
          />
        </Section>
      )}
      {active.length === 0 && !creating && (
        <p className="muted">
          Noch kein Themenbereich angelegt. Mit „Neuer Themenbereich“ legst du
          deinen ersten an.
        </p>
      )}
      <div className="grid two">
        {active.map((p) => (
          <ProjectCard
            key={p.id}
            project={p}
            isAdmin={isAdmin}
            onChanged={load}
          />
        ))}
      </div>
      {archived.length > 0 && (
        <details>
          <summary className="muted small">
            Archivierte Themenbereiche ({archived.length})
          </summary>
          <div className="grid two">
            {archived.map((p) => (
              <ProjectCard
                key={p.id}
                project={p}
                isAdmin={isAdmin}
                onChanged={load}
              />
            ))}
          </div>
        </details>
      )}
      <ChannelAssignment
        channels={channels}
        projects={projects}
        isAdmin={isAdmin}
        onChanged={load}
      />
    </>
  );
}

function suggestionDraft(s: TopicSuggestion): Draft {
  return {
    ...EMPTY_DRAFT,
    name: s.name,
    description: s.description,
    audience: s.audience,
    tone: s.tone,
    subtopics: s.subtopics.join(", "),
  };
}

/** Topic ideas from current trends, each with the numbers behind it. */
function SuggestionList({
  result,
  onTake,
  onClose,
}: {
  result: TopicSuggestions;
  onTake: (s: TopicSuggestion) => void;
  onClose: () => void;
}) {
  return (
    <Section title="Themenvorschläge aus aktuellen Trends">
      {result.sample && (
        <p className="muted small">
          Beispieldaten: Ohne Live-Zugang sind die Zahlen erfunden und nur zum
          Ausprobieren.
        </p>
      )}
      {result.hint && <p className="muted">{result.hint}</p>}
      {result.sources.length > 0 && (
        <p className="muted small">
          Quellen: {result.sources.join(", ")} · Stand{" "}
          {new Date(result.generated_at).toLocaleString("de-DE")}
        </p>
      )}
      <div className="grid two">
        {result.suggestions.map((s) => (
          <article
            key={s.name}
            className="card"
            aria-label={`Vorschlag ${s.name}`}
          >
            <header className="project-head">
              <h3>{s.name}</h3>
              {s.score > 0 && <Badge tone="ok">{s.score} / 100</Badge>}
            </header>
            {s.description && <p>{s.description}</p>}
            {s.reason && <p className="muted">{s.reason}</p>}
            {s.subtopics.length > 0 && (
              <ul className="chips" aria-label="Unterthemen">
                {s.subtopics.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            )}
            {s.facts.length > 0 && (
              <details>
                <summary className="small">Zahlen dahinter</summary>
                <ul className="small">
                  {s.facts.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
                {s.examples.length > 0 && (
                  <p className="small muted">
                    Beispiele aus den Trends: {s.examples.join(" · ")}
                  </p>
                )}
              </details>
            )}
            <div className="form-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => onTake(s)}
              >
                Übernehmen
              </button>
            </div>
          </article>
        ))}
      </div>
      <div className="form-actions">
        <button type="button" className="btn btn-ghost" onClick={onClose}>
          Schließen
        </button>
      </div>
    </Section>
  );
}
