"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { DragEvent, FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { hasRole } from "@/lib/roles";
import type { Calendar, CalendarDay, CalendarEntry, ContentProject } from "@/lib/types";

type Mode = "week" | "month";

const TZ = "Europe/Berlin";

function iso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function parse(day: string): Date {
  return new Date(`${day}T12:00:00Z`);
}

function addDays(day: string, n: number): string {
  const d = parse(day);
  d.setUTCDate(d.getUTCDate() + n);
  return iso(d);
}

function monday(day: string): string {
  const d = parse(day);
  return addDays(day, -((d.getUTCDay() + 6) % 7));
}

function todayBerlin(): string {
  return new Date().toLocaleDateString("sv-SE", { timeZone: TZ });
}

function range(mode: Mode, anchor: string): [string, string] {
  if (mode === "week") {
    const start = monday(anchor);
    return [start, addDays(start, 6)];
  }
  const first = `${anchor.slice(0, 7)}-01`;
  const d = parse(first);
  d.setUTCMonth(d.getUTCMonth() + 1, 0);
  return [monday(first), addDays(monday(iso(d)), 6)];
}

function shift(mode: Mode, anchor: string, dir: number): string {
  if (mode === "week") return addDays(anchor, 7 * dir);
  const d = parse(`${anchor.slice(0, 7)}-01`);
  d.setUTCMonth(d.getUTCMonth() + dir);
  return iso(d);
}

const fmtDay = (day: string, opts: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat("de-DE", { ...opts, timeZone: "UTC" }).format(parse(day));

const fmtTime = (at: string) =>
  new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit", timeZone: TZ }).format(
    new Date(at),
  );

const VIDEO_STATUS: Record<string, string> = {
  scheduled: "geplant",
  running: "läuft",
  succeeded: "veröffentlicht",
  failed: "Fehler",
};

function EntryEditor({
  entry,
  day,
  onDone,
  onError,
}: {
  entry: CalendarEntry;
  day: string;
  onDone: () => void;
  onError: (msg: string) => void;
}) {
  const [target, setTarget] = useState(day);
  const [note, setNote] = useState(entry.note ?? "");

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    try {
      await api.updatePlanDay(entry.id, { day: target, note: note || null });
      onDone();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  async function remove() {
    try {
      await api.deletePlanDay(entry.id);
      onDone();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <form className="card entry-editor" aria-label={`${entry.project} bearbeiten`} onSubmit={save}>
      <strong>
        {entry.project} · {fmtDay(day, { weekday: "long", day: "2-digit", month: "2-digit" })}
      </strong>
      <label>
        Verschieben auf
        <input type="date" value={target} onChange={(e) => setTarget(e.target.value)} required />
      </label>
      <label>
        Notiz
        <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="idea-actions">
        <button type="submit" className="btn btn-primary">
          Speichern
        </button>
        <button type="button" className="btn btn-ghost" onClick={remove}>
          Aus dem Plan nehmen
        </button>
        <button type="button" className="btn btn-ghost" onClick={onDone}>
          Schließen
        </button>
      </div>
    </form>
  );
}

function DayCell({
  day,
  mode,
  inMonth,
  projects,
  canEdit,
  selected,
  onSelect,
  onChange,
  onError,
}: {
  day: CalendarDay;
  mode: Mode;
  inMonth: boolean;
  projects: ContentProject[];
  canEdit: boolean;
  selected: number | null;
  onSelect: (entry: CalendarEntry, day: string) => void;
  onChange: () => void;
  onError: (msg: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [projectId, setProjectId] = useState<number | "">("");
  const [over, setOver] = useState(false);
  const free = projects.filter(
    (p) => p.status === "active" && !day.entries.some((e) => e.project_id === p.id),
  );
  const label = fmtDay(day.day, { weekday: "long", day: "2-digit", month: "2-digit" });

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (projectId === "") return;
    try {
      await api.addPlanDay({ day: day.day, project_id: projectId });
      setAdding(false);
      setProjectId("");
      onChange();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  async function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setOver(false);
    const id = Number(e.dataTransfer.getData("text/plain"));
    if (!id) return;
    try {
      await api.updatePlanDay(id, { day: day.day });
      onChange();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <div
      role="group"
      aria-label={label}
      className={[
        "cal-day",
        day.is_today ? "is-today" : "",
        inMonth ? "" : "is-outside",
        over ? "is-over" : "",
      ].join(" ")}
      onDragOver={(e) => {
        if (!canEdit) return;
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={canEdit ? onDrop : undefined}
    >
      <div className="cal-day-head">
        <span>
          <span className="cal-weekday">{day.weekday.slice(0, 2)}</span>{" "}
          {fmtDay(day.day, { day: "2-digit", month: "2-digit" })}
        </span>
        {canEdit && free.length > 0 && (
          <button
            type="button"
            className="icon-add"
            aria-label={`Bereich am ${label} einplanen`}
            onClick={() => setAdding((v) => !v)}
          >
            +
          </button>
        )}
      </div>
      <div className="cal-entries">
        {day.entries.map((e) => (
          <button
            key={e.id}
            type="button"
            draggable={canEdit}
            onDragStart={(ev) => ev.dataTransfer.setData("text/plain", String(e.id))}
            className={`chip cal-entry${selected === e.id ? " is-selected" : ""}`}
            title={e.note ?? undefined}
            aria-label={`Eintrag ${e.project}`}
            onClick={() => canEdit && onSelect(e, day.day)}
          >
            {e.project}
            {e.note && mode === "week" ? <span className="cal-note"> · {e.note}</span> : null}
          </button>
        ))}
      </div>
      {adding && (
        <form className="cal-add" onSubmit={add}>
          <select
            aria-label={`Themenbereich für ${label}`}
            value={projectId}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
            required
          >
            <option value="">Bereich wählen</option>
            {free.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <button type="submit" className="btn btn-primary btn-small">
            Einplanen
          </button>
        </form>
      )}
      {mode === "week" ? (
        <ul className="cal-videos">
          {day.videos.map((v) => (
            <li key={v.job_id} className={`cal-video status-${v.status}`}>
              <span className="cal-time">{fmtTime(v.at)}</span>
              <span className="cal-video-title">{v.title}</span>
              <span className="muted small">
                {v.channel} · {VIDEO_STATUS[v.status] ?? v.status}
                {v.is_mock ? " · Test" : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        day.videos.length > 0 && (
          <span className="muted small">
            {day.videos.length} Video{day.videos.length === 1 ? "" : "s"}
          </span>
        )
      )}
    </div>
  );
}

function FocusPanel({
  calendar,
  projects,
  canEdit,
  onChange,
  onError,
}: {
  calendar: Calendar;
  projects: ContentProject[];
  canEdit: boolean;
  onChange: () => void;
  onError: (msg: string) => void;
}) {
  const [projectId, setProjectId] = useState<number | "">("");
  const [topic, setTopic] = useState("");
  const [from, setFrom] = useState(calendar.start);
  const [to, setTo] = useState(calendar.end);

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (projectId === "") return;
    try {
      await api.addFocus({ project_id: projectId, topic, starts_on: from, ends_on: to });
      setTopic("");
      onChange();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  async function remove(id: number) {
    try {
      await api.deleteFocus(id);
      onChange();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  return (
    <Section title="Schwerpunkte">
      {calendar.focus.length === 0 ? (
        <p className="muted small">Keine Schwerpunkte in diesem Zeitraum.</p>
      ) : (
        <ul className="feed">
          {calendar.focus.map((f) => (
            <li key={f.id}>
              <div className="feed-body">
                <div className="feed-title">
                  {f.topic} <span className="chip">{f.project}</span>
                </div>
                <div className="muted small">
                  {fmtDay(f.starts_on, { day: "2-digit", month: "2-digit" })} –{" "}
                  {fmtDay(f.ends_on, { day: "2-digit", month: "2-digit", year: "numeric" })}
                </div>
              </div>
              {canEdit && (
                <div className="row-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    aria-label={`Schwerpunkt ${f.topic} entfernen`}
                    onClick={() => remove(f.id)}
                  >
                    Entfernen
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form className="focus-form" aria-label="Neuer Schwerpunkt" onSubmit={add}>
          <label>
            Themenbereich
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
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
            Thema
            <input value={topic} maxLength={200} onChange={(e) => setTopic(e.target.value)} required />
          </label>
          <label>
            Von
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
          </label>
          <label>
            Bis
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} required />
          </label>
          <button type="submit" className="btn btn-ghost">
            Schwerpunkt setzen
          </button>
        </form>
      )}
      <p className="muted small">
        Videos zu einem Schwerpunkt bekommen bei der Auswahl einen Vorrang. Die Menge je Kanal
        bestimmt weiterhin die Publishing-Strategie.
      </p>
    </Section>
  );
}

/** Editorial calendar: topic areas per day, focus topics and the planned videos (extension E6). */
export function CalendarView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "operator");
  const [mode, setMode] = useState<Mode>("week");
  const [anchor, setAnchor] = useState(todayBerlin);
  const [projectId, setProjectId] = useState<number | undefined>(undefined);
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [calendar, setCalendar] = useState<Calendar | null>(null);
  const [selected, setSelected] = useState<{ entry: CalendarEntry; day: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [start, end] = useMemo(() => range(mode, anchor), [mode, anchor]);

  const load = useCallback(() => {
    api
      .calendar(start, end, projectId)
      .then(setCalendar)
      .catch((e: Error) => setError(e.message));
  }, [start, end, projectId]);

  useEffect(() => {
    api
      .projects()
      .then((all) => setProjects(all.filter((p) => p.status !== "archived")))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  function changed() {
    setSelected(null);
    setError(null);
    load();
  }

  const title =
    mode === "week"
      ? `${fmtDay(start, { day: "2-digit", month: "2-digit" })} – ${fmtDay(end, {
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
        })}`
      : fmtDay(`${anchor.slice(0, 7)}-01`, { month: "long", year: "numeric" });

  return (
    <>
      <PageHeader
        title="Redaktionsplan"
        description="Welcher Themenbereich an welchem Tag läuft und welche Themen Vorrang haben. Ist ein Tag verplant, posten nur dessen Bereiche; wie viel, entscheidet die Publishing-Strategie."
      />
      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label="Ansicht">
          {(
            [
              ["week", "Woche"],
              ["month", "Monat"],
            ] as [Mode, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={mode === key}
              className={`tab${mode === key ? " is-active" : ""}`}
              onClick={() => setMode(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="cal-nav">
          <button
            type="button"
            className="btn btn-ghost btn-small"
            aria-label="Zurück"
            onClick={() => setAnchor((a) => shift(mode, a, -1))}
          >
            ‹
          </button>
          <button type="button" className="btn btn-ghost btn-small" onClick={() => setAnchor(todayBerlin())}>
            Heute
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-small"
            aria-label="Weiter"
            onClick={() => setAnchor((a) => shift(mode, a, 1))}
          >
            ›
          </button>
          <strong className="cal-title">{title}</strong>
        </div>
        <label className="inline-label">
          Themenbereich
          <select
            value={projectId ?? ""}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">Alle</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <Badge>Tage ohne Eintrag sind für alle Bereiche offen</Badge>
      </div>
      <ErrorText error={error} />
      {selected && (
        <EntryEditor
          key={selected.entry.id}
          entry={selected.entry}
          day={selected.day}
          onDone={changed}
          onError={setError}
        />
      )}
      {calendar && (
        <div className={`cal-grid cal-${mode}`}>
          {calendar.days.map((d) => (
            <DayCell
              key={d.day}
              day={d}
              mode={mode}
              inMonth={mode === "week" || d.day.slice(0, 7) === anchor.slice(0, 7)}
              projects={projects}
              canEdit={canEdit}
              selected={selected?.entry.id ?? null}
              onSelect={(entry, day) => setSelected({ entry, day })}
              onChange={changed}
              onError={setError}
            />
          ))}
        </div>
      )}
      {calendar && (
        <FocusPanel
          calendar={calendar}
          projects={projects}
          canEdit={canEdit}
          onChange={changed}
          onError={setError}
        />
      )}
    </>
  );
}
