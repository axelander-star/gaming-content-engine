"use client";

// Channel assistant: which topic area still lacks a channel on YouTube, TikTok or
// Instagram, and "create channel" tasks with everything to copy. The engine never
// creates platform accounts itself; the operator signs up, confirms phone/captcha
// and connects the account afterwards.

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  ChannelSetupTask,
  CoverageSlot,
  MailRoutingStatus,
  ProjectCoverage,
  SlotState,
} from "@/lib/types";

const LANG: Record<string, string> = { de: "DE", en: "EN" };
const SLOT: Record<SlotState, [string, "ok" | "warn" | "info" | "danger"]> = {
  connected: ["Verbunden", "ok"],
  added: ["Angelegt, nicht verbunden", "warn"],
  prepared: ["Vorbereitet", "info"],
  missing: ["Fehlt", "danger"],
};

function CopyField({
  label,
  value,
  id,
  multiline = false,
}: {
  label: string;
  value: string;
  id: string;
  multiline?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      (document.getElementById(id) as HTMLInputElement | null)?.select();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }
  return (
    <div className="cs-copy">
      <label htmlFor={id} className="muted small">
        {label}
      </label>
      <div className="cs-copy-row">
        {multiline ? (
          <textarea id={id} readOnly value={value} rows={3} onFocus={(e) => e.currentTarget.select()} />
        ) : (
          <input id={id} readOnly value={value} onFocus={(e) => e.currentTarget.select()} />
        )}
        <button type="button" className="btn btn-small" onClick={() => void copy()}>
          {copied ? "Kopiert" : "Kopieren"}
        </button>
      </div>
    </div>
  );
}

function SlotChip({ slot }: { slot: CoverageSlot }) {
  const [text, tone] = SLOT[slot.state];
  return (
    <li className="cs-slot">
      <span className="cs-slot-name">
        {PLATFORM_LABELS[slot.platform]} {LANG[slot.language]}
      </span>
      <Badge tone={tone}>{text}</Badge>
    </li>
  );
}

function handleHint(task: ChannelSetupTask, handle: string): string {
  const state = task.handle_check[handle];
  if (state === "free") return "frei";
  if (state === "taken") return "vergeben";
  return task.platform === "youtube" ? "nicht geprüft" : "bei der Anmeldung prüfen";
}

function TaskCard({
  task,
  canEdit,
  onChanged,
}: {
  task: ChannelSetupTask;
  canEdit: boolean;
  onChanged: (connectChannel?: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(task.display_name);
  const [handle, setHandle] = useState(task.handle);
  const [bio, setBio] = useState(task.bio);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stamp, setStamp] = useState(0);
  const title = `${task.platform_label} ${LANG[task.language]}: ${task.content_project}`;

  async function run(
    fn: () => Promise<unknown>,
    connect?: () => number | undefined,
  ): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setStamp(Date.now());
      await onChanged(connect?.());
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void run(() => api.updateChannelSetup(task.id, { display_name: name, handle, bio })).then(
      (ok) => {
        if (ok) setEditing(false);
      },
    );
  }

  function done() {
    let channelId: number | undefined;
    void run(
      async () => {
        channelId = (await api.completeChannelSetup(task.id)).channel_id;
      },
      () => channelId,
    );
  }

  const img = (kind: "avatar" | "banner") => `${api.channelSetupImage(task.id, kind)}?v=${stamp}`;

  return (
    <article className="card cs-task" aria-label={`Aufgabe ${title}`}>
      <div className="cs-task-head">
        <div className="chip-row">
          <span className={`chip chip-${task.platform}`}>{task.platform_label}</span>
          <span className="chip">{LANG[task.language]}</span>
          <span className="chip">{task.content_project}</span>
          {task.text_source === "mock" && <Badge tone="info">Testtexte</Badge>}
        </div>
        <a className="btn btn-primary" href={task.signup_url} target="_blank" rel="noreferrer">
          {task.platform === "youtube" ? "Kanal bei YouTube erstellen" : `Bei ${task.platform_label} registrieren`}
        </a>
      </div>

      <div className="cs-task-body">
        <div className="cs-images">
          {task.has_avatar && (
            <figure>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className="cs-avatar" src={img("avatar")} alt={`Profilbild ${task.display_name}`} />
              <figcaption>
                <a href={img("avatar")} download className="small">
                  Profilbild laden
                </a>
              </figcaption>
            </figure>
          )}
          {task.has_banner && (
            <figure>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className="cs-banner" src={img("banner")} alt={`Banner ${task.display_name}`} />
              <figcaption>
                <a href={img("banner")} download className="small">
                  Banner laden (2560 × 1440)
                </a>
              </figcaption>
            </figure>
          )}
        </div>

        {editing ? (
          <form className="cs-fields" onSubmit={save} aria-label={`Werte ${title}`}>
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
            </label>
            <label>
              Benutzername
              <input value={handle} onChange={(e) => setHandle(e.target.value)} maxLength={40} />
            </label>
            <label>
              Bio ({bio.length}/{task.bio_max})
              <textarea value={bio} onChange={(e) => setBio(e.target.value)} rows={3} maxLength={task.bio_max} />
            </label>
            <div className="form-actions">
              <button className="btn btn-primary" disabled={busy}>
                Speichern
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setEditing(false)}>
                Abbrechen
              </button>
            </div>
          </form>
        ) : (
          <div className="cs-fields">
            <CopyField id={`cs-name-${task.id}`} label="Name" value={task.display_name} />
            <CopyField
              id={`cs-handle-${task.id}`}
              label={`Benutzername (${handleHint(task, task.handle)})`}
              value={task.handle}
            />
            {task.alt_handles.length > 0 && (
              <p className="muted small">
                Falls vergeben:{" "}
                {task.alt_handles.map((h) => `${h} (${handleHint(task, h)})`).join(", ")}
              </p>
            )}
            <CopyField id={`cs-bio-${task.id}`} label="Bio" value={task.bio} multiline />
            {task.email ? (
              <CopyField
                id={`cs-mail-${task.id}`}
                label={
                  task.email_status === "created"
                    ? "E-Mail-Adresse (leitet an dein Postfach weiter)"
                    : "E-Mail-Adresse (noch nicht angelegt)"
                }
                value={task.email}
              />
            ) : (
              task.email_status === "not_needed" && (
                <p className="muted small">Keine eigene E-Mail nötig: Brand-Kanal unter dem Geschäftskonto.</p>
              )
            )}
            {task.email_status === "mock" && (
              <p className="small">
                <Badge tone="info">Testmodus</Badge> Die Weiterleitung wird erst angelegt, wenn der
                Cloudflare-Zugang eingerichtet ist.
                {task.email_error ? ` ${task.email_error}` : ""}
              </p>
            )}
            {task.email_status === "failed" && (
              <p className="small">
                <Badge tone="danger">E-Mail fehlgeschlagen</Badge> {task.email_error}{" "}
                {canEdit && (
                  <button
                    type="button"
                    className="btn btn-small"
                    disabled={busy}
                    onClick={() => void run(() => api.retryChannelSetupEmail(task.id))}
                  >
                    Erneut versuchen
                  </button>
                )}
              </p>
            )}
          </div>
        )}
      </div>

      <details className="cs-steps">
        <summary>So geht es ({task.steps.length} Schritte)</summary>
        <ol>
          {task.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      </details>

      <ErrorText error={error} />
      {canEdit && (
        <div className="row-actions">
          <button className="btn btn-primary" disabled={busy} onClick={done}>
            Kanal ist angelegt
          </button>
          {!editing && (
            <button className="btn" disabled={busy} onClick={() => setEditing(true)}>
              Werte ändern
            </button>
          )}
          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => void run(() => api.dismissChannelSetup(task.id))}
          >
            Nicht gebraucht
          </button>
        </div>
      )}
    </article>
  );
}

export function ChannelSetupView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "admin");
  const [coverage, setCoverage] = useState<ProjectCoverage[] | null>(null);
  const [tasks, setTasks] = useState<ChannelSetupTask[]>([]);
  const [mail, setMail] = useState<MailRoutingStatus | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [cov, open, m] = await Promise.all([
      api.channelCoverage(),
      api.channelSetupTasks("open"),
      api.mailRoutingStatus(),
    ]);
    setCoverage(cov);
    setTasks(open);
    setMail(m);
  }, []);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  async function changed(connectChannel?: number) {
    await load();
    if (connectChannel !== undefined) {
      setNotice(
        "Kanal angelegt. Jetzt noch verbinden, damit die Engine posten und Zahlen lesen kann.",
      );
      try {
        const { url } = await api.connectChannel(connectChannel);
        window.location.assign(url);
      } catch (e) {
        setNotice(
          `Kanal angelegt. Verbinden ist noch nicht möglich: ${(e as Error).message} ` +
            "Du findest ihn unter Einstellungen, Kanäle.",
        );
      }
    }
  }

  async function prepare(projectId: number) {
    setBusy(projectId);
    setError(null);
    try {
      const made = await api.prepareChannels(projectId);
      setNotice(made.length ? `${made.length} Kanäle vorbereitet.` : "Es fehlt kein Kanal.");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const missingTotal = coverage?.reduce((n, c) => n + c.missing, 0) ?? 0;

  return (
    <>
      <PageHeader
        title="Kanal-Assistent"
        description="Prüft je Themenbereich, ob es Kanäle auf YouTube, TikTok und Instagram gibt, und bereitet fehlende vor. Du legst das Konto mit den Werten selbst an und bestätigst Telefon und Captcha."
      />
      <ErrorText error={error} />
      {notice && (
        <p className="card cs-notice" role="status">
          {notice}
        </p>
      )}
      {mail && mail.mode === "mock" && (
        <p className="muted small">
          E-Mail-Weiterleitungen laufen im Testmodus{mail.domain ? ` (Domain ${mail.domain})` : ""}. Es
          wird noch nichts bei Cloudflare angelegt.
        </p>
      )}
      {mail?.problem && (
        <p className="small">
          <Badge tone="danger">E-Mail</Badge> {mail.problem}
        </p>
      )}

      <Section title={`Offene Aufgaben „Kanal erstellen“ (${tasks.length})`}>
        {tasks.length === 0 ? (
          <p className="muted">Keine offenen Aufgaben.</p>
        ) : (
          <div className="cs-tasks">
            {tasks.map((t) => (
              <TaskCard key={t.id} task={t} canEdit={canEdit} onChanged={changed} />
            ))}
          </div>
        )}
      </Section>

      <Section title={`Kanäle je Themenbereich${missingTotal ? ` (${missingTotal} fehlen)` : ""}`}>
        {coverage === null ? (
          <p className="muted">Lädt …</p>
        ) : (
          <div className="cs-coverage">
            {coverage.map((c) => (
              <article key={c.project_id} className="card" aria-label={`Themenbereich ${c.project}`}>
                <div className="cs-task-head">
                  <h3>{c.project}</h3>
                  {canEdit && c.missing > 0 && (
                    <button
                      className="btn btn-primary btn-small"
                      disabled={busy !== null}
                      onClick={() => void prepare(c.project_id)}
                    >
                      {busy === c.project_id ? "Bereite vor …" : `${c.missing} fehlende vorbereiten`}
                    </button>
                  )}
                </div>
                <ul className="cs-slots">
                  {c.slots.map((s) => (
                    <SlotChip key={`${s.platform}-${s.language}`} slot={s} />
                  ))}
                </ul>
              </article>
            ))}
          </div>
        )}
      </Section>
    </>
  );
}
