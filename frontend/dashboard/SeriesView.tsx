"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, Section } from "@/components/ui";
import { formatSeconds } from "@/dashboard/LibraryView";
import { Editor, STATUS } from "@/dashboard/OwnProductionView";
import { api } from "@/lib/api";
import { hasRole } from "@/lib/roles";
import type {
  ContentProject,
  Language,
  LibraryItem,
  Production,
  Series,
  SeriesChannelPlan,
  SeriesSuggestion,
  VideoStatus,
} from "@/lib/types";

const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

function formatDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y ?? 2000, (m ?? 1) - 1, d ?? 1);
  return `${WEEKDAYS[date.getDay()]} ${String(d).padStart(2, "0")}.${String(m).padStart(2, "0")}.`;
}

const POST_LABELS: Partial<
  Record<VideoStatus, [string, "neutral" | "ok" | "warn" | "info"]>
> = {
  QUALITY_APPROVED: ["wartet auf Freigabe", "neutral"],
  READY_TO_PUBLISH: ["freigegeben", "info"],
  SCHEDULED: ["geplant", "warn"],
  PUBLISHED: ["veröffentlicht", "ok"],
  ANALYTICS_PENDING: ["veröffentlicht", "ok"],
  ANALYZED: ["veröffentlicht", "ok"],
};

type Scope = "auto" | "parts" | "minutes";

function NewSeries({
  projects,
  prefill,
  onCreated,
  onError,
  onProject,
}: {
  projects: ContentProject[];
  prefill: SeriesSuggestion | null;
  onCreated: (s: Series) => void;
  onError: (msg: string) => void;
  onProject: (id: number | "", language: Language) => void;
}) {
  const [projectId, setProjectId] = useState<number | "">("");
  const [topic, setTopic] = useState("");
  const [pitch, setPitch] = useState("");
  const [ideaId, setIdeaId] = useState<number | null>(null);
  const [language, setLanguage] = useState<Language>("de");
  const [scope, setScope] = useState<Scope>("auto");
  const [amount, setAmount] = useState(10);
  const [partSeconds, setPartSeconds] = useState(90);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!prefill) return;
    setTopic(prefill.title);
    setPitch(prefill.pitch);
    setIdeaId(prefill.idea_id);
    setScope("parts");
    setAmount(prefill.parts);
  }, [prefill]);

  useEffect(
    () => onProject(projectId, language),
    [projectId, language, onProject],
  );

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (projectId === "") return;
    setBusy(true);
    try {
      const created = await api.createSeries({
        project_id: projectId,
        topic,
        pitch: pitch || null,
        idea_id: ideaId,
        language,
        parts: scope === "parts" ? amount : null,
        total_minutes: scope === "minutes" ? amount : null,
        part_seconds: partSeconds,
      });
      setTopic("");
      setPitch("");
      setIdeaId(null);
      onCreated(created);
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Neue Serie">
      <p className="muted small">
        Ein großes Thema, viele kurze Teile. Die KI teilt das Thema auf,
        schreibt jedes Skript und alle Videos werden vorab fertig produziert.
        Hochgeladen wird nach Plan, nicht alles an einem Tag.
      </p>
      <form className="source-form" aria-label="Neue Serie" onSubmit={submit}>
        <label>
          Themenbereich
          <select
            value={projectId}
            onChange={(e) =>
              setProjectId(e.target.value ? Number(e.target.value) : "")
            }
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
          Thema der Serie
          <input
            value={topic}
            maxLength={300}
            minLength={3}
            placeholder="z. B. Wie entsteht die Welt"
            onChange={(e) => {
              setTopic(e.target.value);
              setIdeaId(null);
            }}
            required
          />
        </label>
        <label>
          Worauf es ankommt (optional)
          <textarea
            value={pitch}
            maxLength={2000}
            rows={2}
            placeholder="z. B. vom Urknall bis heute, verständlich für Jugendliche"
            onChange={(e) => setPitch(e.target.value)}
          />
        </label>
        <label>
          Umfang
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as Scope)}
          >
            <option value="auto">KI entscheidet</option>
            <option value="parts">Anzahl Teile</option>
            <option value="minutes">Gesamtlänge in Minuten</option>
          </select>
        </label>
        {scope !== "auto" && (
          <label>
            {scope === "parts"
              ? "Teile (2 bis 30)"
              : "Minuten insgesamt (bis 120)"}
            <input
              type="number"
              min={scope === "parts" ? 2 : 1}
              max={scope === "parts" ? 30 : 120}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
              required
            />
          </label>
        )}
        <label>
          Länge je Teil
          <select
            value={partSeconds}
            onChange={(e) => setPartSeconds(Number(e.target.value))}
          >
            <option value={60}>etwa 1 Minute</option>
            <option value={90}>etwa 1,5 Minuten</option>
            <option value={120}>etwa 2 Minuten</option>
          </select>
        </label>
        <label>
          Sprache
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as Language)}
          >
            <option value="de">Deutsch</option>
            <option value="en">Englisch</option>
          </select>
        </label>
        {scope === "minutes" && (
          <p className="muted small">
            Ergibt etwa{" "}
            {Math.min(30, Math.max(2, Math.ceil((amount * 60) / partSeconds)))}{" "}
            Teile.
          </p>
        )}
        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy || projectId === ""}
        >
          {busy ? "KI plant die Teile …" : "Serie planen"}
        </button>
      </form>
    </Section>
  );
}

function Suggestions({
  projectId,
  language,
  canEdit,
  onPick,
}: {
  projectId: number | "";
  language: Language;
  canEdit: boolean;
  onPick: (s: SeriesSuggestion) => void;
}) {
  const [items, setItems] = useState<SeriesSuggestion[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setItems(null);
    if (projectId === "") return;
    api
      .seriesSuggestions(projectId, language)
      .then(setItems)
      .catch((e: Error) => setError(e.message));
  }, [projectId, language]);

  async function askAi() {
    if (projectId === "") return;
    setBusy(true);
    setError(null);
    try {
      setItems(await api.seriesAiSuggestions(projectId, language));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Ideen für Serien">
      {projectId === "" ? (
        <p className="muted small">
          Wähle oben einen Themenbereich, dann kommen hier Vorschläge.
        </p>
      ) : (
        <>
          <p className="muted small">
            Aus dem Ideenlabor, deinen Schwerpunkten im Redaktionsplan und
            bewährten Serienformaten.
          </p>
          <ErrorText error={error} />
          <ul className="feed series-sugg" aria-label="Serienvorschläge">
            {items?.map((s) => (
              <li key={s.title}>
                <span className="feed-title">{s.title}</span>
                <span className="muted small">
                  {s.parts} Teile · {s.reason}
                </span>
                {canEdit && (
                  <div className="row-actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-small"
                      onClick={() => onPick(s)}
                      aria-label={`Übernehmen: ${s.title}`}
                    >
                      Übernehmen
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {canEdit && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={askAi}
              disabled={busy}
            >
              {busy ? "KI denkt nach …" : "Neue Ideen von der KI"}
            </button>
          )}
        </>
      )}
    </Section>
  );
}

function Plan({ series }: { series: Series }) {
  const [plans, setPlans] = useState<SeriesChannelPlan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = `${series.id}-${series.counts.approved}-${series.counts.scheduled}-${series.counts.published}-${series.paused}`;

  useEffect(() => {
    api
      .seriesPlan(series.id)
      .then(setPlans)
      .catch((e: Error) => setError(e.message));
    // reload when the series state changes
  }, [series.id, key]);

  if (error) return <ErrorText error={error} />;
  if (!plans) return null;
  if (plans.length === 0)
    return (
      <p className="muted small">
        In diesem Themenbereich gibt es noch keinen Kanal in der Sprache der
        Serie. Lege ihn im Kanal-Assistenten an.
      </p>
    );
  return (
    <div className="series-plans">
      {plans.map((p) => (
        <div
          key={p.channel_id}
          className="series-plan"
          aria-label={`Plan ${p.channel}`}
        >
          <strong className="small">
            {p.platform} · {p.channel}
          </strong>
          {p.days.length === 0 ? (
            <p className="muted small">
              {series.paused ? "Serie ist pausiert." : "Nichts offen."}
            </p>
          ) : (
            <ol className="series-days">
              {p.days.map((d) => (
                <li key={d.day} title={d.reasons.join(" · ")}>
                  <span className="series-day">{formatDay(d.day)}</span>
                  <span>
                    {d.parts.length === 1 ? "Teil " : "Teile "}
                    {d.parts.join(", ")}
                  </span>
                  {d.fixed ? (
                    <Badge tone="ok">fest</Badge>
                  ) : (
                    <span className="muted small">
                      {d.reasons[d.reasons.length - 1]}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      ))}
      <p className="muted small">
        Vorschau mit den heutigen Zahlen. Jeden Tag entscheidet der
        Publishing-Agent neu: Laufen die Teile gut oder ist ein Wochentag stark,
        kommen mehr Teile; laufen sie schwach, wird der Abstand größer. Die
        Reihenfolge bleibt immer gleich.
      </p>
    </div>
  );
}

function SeriesDetail({
  series,
  canEdit,
  onChange,
  onDeleted,
}: {
  series: Series;
  canEdit: boolean;
  onChange: (s: Series) => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [part, setPart] = useState<number | null>(null);
  const [images, setImages] = useState<LibraryItem[]>([]);
  const c = series.counts;
  const pendingScripts = c.parts - c.scripted;
  const toRender = series.parts.filter(
    (p) => p.production.status === "draft" || p.production.status === "failed",
  ).length;

  useEffect(() => {
    api
      .library({ projectId: series.project_id, kind: "image", status: "ready" })
      .then(setImages)
      .catch(() => setImages([]));
  }, [series.project_id]);

  const run = useCallback(async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    setNote(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }, []);

  async function writeScripts(then?: boolean) {
    await run("scripts", async () => {
      let out = await api.writeSeriesScripts(series.id);
      onChange(out.series);
      while (out.remaining > 0) {
        out = await api.writeSeriesScripts(series.id);
        onChange(out.series);
      }
      if (then) {
        const r = await api.renderSeries(series.id);
        onChange(r.series);
        setNote(`${r.queued} Videos werden erzeugt.`);
      }
    });
  }

  // a new series writes its scripts and starts the videos right away
  useEffect(() => {
    if (canEdit && c.scripted === 0 && c.parts > 0 && busy === null && !error) {
      void writeScripts(true);
    }
    // only for a fresh series
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series.id]);

  const current = series.parts.find((p) => p.part === part)?.production ?? null;

  return (
    <Section title={series.title}>
      <div className="idea-meta">
        <span className="chip">{series.project}</span>
        <span className="muted small">
          {c.parts} Teile à etwa {formatSeconds(series.part_seconds)} ·{" "}
          {series.language.toUpperCase()} · Gliederung:{" "}
          {series.script_source === "mock"
            ? "Testskript"
            : series.script_source}
        </span>
        {series.paused && <Badge tone="warn">pausiert</Badge>}
      </div>
      <ErrorText error={error} />
      {note && <p className="notice small">{note}</p>}

      <ol className="series-steps" aria-label="Schritte der Serie">
        <li className={pendingScripts === 0 ? "is-done" : ""}>
          <strong>1. Skripte</strong>
          <span className="muted small">
            {c.scripted} von {c.parts} geschrieben
          </span>
          {canEdit && pendingScripts > 0 && (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              disabled={busy !== null}
              onClick={() => writeScripts(false)}
            >
              {busy === "scripts" ? "KI schreibt …" : "Skripte schreiben"}
            </button>
          )}
        </li>
        <li className={c.done === c.parts ? "is-done" : ""}>
          <strong>2. Videos</strong>
          <span className="muted small">
            {c.done} von {c.parts} fertig
            {c.rendering > 0 ? `, ${c.rendering} in Arbeit` : ""}
            {c.failed > 0 ? `, ${c.failed} mit Fehler` : ""}
          </span>
          {canEdit && pendingScripts === 0 && toRender > 0 && (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              disabled={busy !== null}
              onClick={() =>
                run("render", async () => {
                  const r = await api.renderSeries(series.id);
                  onChange(r.series);
                  setNote(`${r.queued} Videos werden erzeugt.`);
                })
              }
            >
              Alle Videos erzeugen
            </button>
          )}
        </li>
        <li className={c.done > 0 && c.approved >= c.done ? "is-done" : ""}>
          <strong>3. Freigabe</strong>
          <span className="muted small">
            {c.approved} Beiträge freigegeben, {c.scheduled} geplant,{" "}
            {c.published} veröffentlicht
          </span>
          {canEdit && c.done > 0 && (
            <button
              type="button"
              className="btn btn-primary btn-small"
              disabled={busy !== null}
              title="Bereitet jeden fertigen Teil für alle Kanäle in der Sprache der Serie vor und gibt ihn frei. Wann was hochgeladen wird, entscheidet der Planer."
              onClick={() =>
                run("approve", async () => {
                  const r = await api.prepareSeries(series.id, true);
                  onChange(r.series);
                  setNote(
                    `${r.prepared} Beiträge vorbereitet, ${r.approved} freigegeben.` +
                      (r.skipped.length
                        ? ` Übersprungen: ${r.skipped.join("; ")}`
                        : ""),
                  );
                })
              }
            >
              Alle fertigen Teile freigeben
            </button>
          )}
        </li>
      </ol>

      <h3 className="series-h">Veröffentlichungsplan</h3>
      <Plan series={series} />

      <h3 className="series-h">Teile</h3>
      <ol className="series-parts" aria-label="Teile der Serie">
        {series.parts.map((p) => {
          const [label, tone] = STATUS[p.production.status];
          const pending = p.production.script_source === "pending";
          return (
            <li key={p.part} aria-label={`Teil ${p.part}`}>
              <button
                type="button"
                className={`prod-pick${p.part === part ? " is-active" : ""}`}
                onClick={() => setPart(p.part === part ? null : p.part)}
              >
                <span className="feed-title">{p.production.title}</span>
                <span className="muted small">
                  {pending ? (
                    <Badge tone="neutral">Skript fehlt</Badge>
                  ) : (
                    <Badge tone={tone}>{label}</Badge>
                  )}
                  {p.production.duration_s
                    ? ` ${formatSeconds(p.production.duration_s)}`
                    : ""}
                  {p.posts.map((post) => {
                    const [text, t] = POST_LABELS[post.status] ?? [
                      post.status,
                      "neutral",
                    ];
                    return (
                      <span key={post.variant_id}>
                        {" · "}
                        {post.channel}: <Badge tone={t}>{text}</Badge>
                      </span>
                    );
                  })}
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {current && current.script_source !== "pending" && (
        <Editor
          production={current}
          images={images}
          canEdit={canEdit}
          onSaved={(prod: Production) =>
            onChange({
              ...series,
              parts: series.parts.map((x) =>
                x.production.id === prod.id ? { ...x, production: prod } : x,
              ),
            })
          }
          onCreated={() =>
            setNote(
              "Fassung in der anderen Sprache liegt unter „Einzelvideos“.",
            )
          }
          onError={setError}
        />
      )}

      {canEdit && (
        <div className="row-actions">
          <button
            type="button"
            className="btn btn-ghost btn-small"
            disabled={busy !== null}
            onClick={() =>
              run("pause", async () =>
                onChange(
                  await api.updateSeries(series.id, { paused: !series.paused }),
                ),
              )
            }
          >
            {series.paused ? "Serie fortsetzen" : "Serie pausieren"}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-small"
            disabled={busy !== null}
            onClick={() =>
              run("delete", async () => {
                await api.deleteSeries(series.id);
                onDeleted();
              })
            }
          >
            Serie löschen
          </button>
        </div>
      )}
    </Section>
  );
}

/** Series: one big topic as many short parts, released in order over the days. */
export function SeriesView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "operator");
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [list, setList] = useState<Series[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prefill, setPrefill] = useState<SeriesSuggestion | null>(null);
  const [formProject, setFormProject] = useState<number | "">("");
  const [formLanguage, setFormLanguage] = useState<Language>("de");

  const load = useCallback(() => {
    api
      .seriesList()
      .then((all) => {
        setList(all);
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

  const running = list?.some((s) => s.counts.rendering > 0);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [running, load]);

  const onProject = useCallback((id: number | "", language: Language) => {
    setFormProject(id);
    setFormLanguage(language);
  }, []);

  const current = list?.find((s) => s.id === selected) ?? null;

  function changed(s: Series) {
    setError(null);
    setList((all) => (all ? all.map((x) => (x.id === s.id ? s : x)) : [s]));
  }

  return (
    <>
      <ErrorText error={error} />
      <div className="chat-layout">
        <div className="side-stack">
          {current ? (
            <SeriesDetail
              key={current.id}
              series={current}
              canEdit={canEdit}
              onChange={changed}
              onDeleted={() => {
                setList((all) =>
                  all ? all.filter((x) => x.id !== current.id) : all,
                );
                setSelected(null);
              }}
            />
          ) : (
            <p className="muted">
              Noch keine Serie. Lege rechts eine an, zum Beispiel „Wie entsteht
              die Welt“.
            </p>
          )}
        </div>
        <div className="side-stack">
          {canEdit && (
            <NewSeries
              projects={projects}
              prefill={prefill}
              onProject={onProject}
              onCreated={(s) => {
                setError(null);
                setList((all) => [s, ...(all ?? [])]);
                setSelected(s.id);
              }}
              onError={setError}
            />
          )}
          <Suggestions
            projectId={formProject}
            language={formLanguage}
            canEdit={canEdit}
            onPick={setPrefill}
          />
          <Section title="Serien">
            {list && list.length === 0 && (
              <p className="muted small">Noch keine.</p>
            )}
            <ul className="feed">
              {list?.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className={`prod-pick${s.id === selected ? " is-active" : ""}`}
                    onClick={() => setSelected(s.id)}
                  >
                    <span className="feed-title">{s.title}</span>
                    <span className="muted small">
                      {s.project} · {s.counts.done}/{s.counts.parts} fertig ·{" "}
                      {s.counts.published} veröffentlicht
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      </div>
    </>
  );
}
