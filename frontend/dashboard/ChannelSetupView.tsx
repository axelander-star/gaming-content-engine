"use client";

// Channel assistant: which topic area still lacks a channel on YouTube, TikTok or
// Instagram, and "create channel" tasks with everything to copy. The engine never
// creates platform accounts itself; the operator signs up, confirms phone/captcha
// and connects the account afterwards.

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Icon } from "@/components/icons";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  ChannelSetupAiPart,
  ChannelSetupTask,
  CoverageSlot,
  MailRoutingCheck,
  MailRoutingStatus,
  ProjectCoverage,
  SlotState,
} from "@/lib/types";

const LANG: Record<string, string> = { de: "DE", en: "EN" };
const SLOT: Record<SlotState, [string, "ok" | "warn" | "info" | "danger"]> = {
  connected: ["Verbunden", "ok"],
  added: ["Angelegt, nicht verbunden", "warn"],
  placeholder: ["Platzhalter, noch kein Konto", "danger"],
  prepared: ["Vorbereitet", "info"],
  missing: ["Fehlt", "danger"],
};

/** Small AI symbol: renews only the value next to it. */
function AiButton({
  label,
  hint,
  thinking,
  disabled,
  onClick,
}: {
  label: string;
  hint: string;
  thinking: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="btn cs-ai-btn"
      aria-label={label}
      aria-busy={thinking}
      title={hint}
      disabled={disabled}
      onClick={onClick}
    >
      {thinking ? (
        <span className="run-spinner" aria-hidden="true" />
      ) : (
        <Icon name="wand" />
      )}
      <span className="cs-ai-tag" aria-hidden="true">
        KI
      </span>
    </button>
  );
}

/** Value to copy; with ``onSave`` it is also editable: type or paste, saved on leaving the field. */
function CopyField({
  label,
  value,
  id,
  multiline = false,
  ai,
  onSave,
  maxLength,
}: {
  label: string;
  value: string;
  id: string;
  multiline?: boolean;
  ai?: ReactNode;
  onSave?: (value: string) => Promise<boolean>;
  maxLength?: number;
}) {
  const [copied, setCopied] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saved, setSaved] = useState(false);
  useEffect(() => setDraft(value), [value]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(draft);
    } catch {
      (document.getElementById(id) as HTMLInputElement | null)?.select();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }
  async function commit() {
    if (!onSave || draft.trim() === value.trim()) return;
    if (!draft.trim()) {
      setDraft(value); // empty is not allowed: keep the last value
      return;
    }
    if (await onSave(draft)) {
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1800);
    } else {
      setDraft(value);
    }
  }
  const editable = Boolean(onSave);
  const common = {
    id,
    value: draft,
    readOnly: !editable,
    maxLength,
    onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
    onBlur: () => void commit(),
    onFocus: editable
      ? undefined
      : (e: { currentTarget: { select: () => void } }) =>
          e.currentTarget.select(),
  };
  return (
    <div className="cs-copy">
      <div className="cs-copy-label">
        <label htmlFor={id} className="muted small">
          {label}
        </label>
        {multiline && maxLength ? (
          <span className="muted small">
            {" "}
            ({draft.length}/{maxLength})
          </span>
        ) : null}
        {saved && (
          <span role="status" className="small cs-saved">
            {" "}
            Gespeichert
          </span>
        )}
      </div>
      <div className="cs-copy-row">
        {multiline ? (
          <textarea {...common} rows={3} />
        ) : (
          <input
            {...common}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
          />
        )}
        {ai}
        <button
          type="button"
          className="btn btn-small"
          onClick={() => void copy()}
        >
          {copied ? "Kopiert" : "Kopieren"}
        </button>
      </div>
    </div>
  );
}

/** "Eigenes Bild hochladen": a file picker styled as a small button. */
function UploadButton({
  label,
  hint,
  disabled,
  onFile,
}: {
  label: string;
  hint: string;
  disabled: boolean;
  onFile: (file: File) => void;
}) {
  return (
    <label
      className={`cs-upload${disabled ? " is-disabled" : ""}`}
      title={`${label}: ${hint}`}
    >
      <Icon name="upload" />
      <span className="sr-only">{label}</span>
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        disabled={disabled}
        aria-label={label}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) onFile(file);
        }}
      />
    </label>
  );
}

function SlotChip({
  slot,
  onPrepare,
  busy,
}: {
  slot: CoverageSlot;
  onPrepare?: (channelId: number) => void;
  busy?: boolean;
}) {
  const [text, tone] = SLOT[slot.state];
  const label = `${PLATFORM_LABELS[slot.platform]} ${LANG[slot.language]}`;
  return (
    <li className="cs-slot">
      <span className="cs-slot-name">{label}</span>
      <Badge tone={tone}>{text}</Badge>
      {onPrepare &&
        (slot.state === "added" || slot.state === "placeholder") &&
        slot.channel_id !== null && (
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            aria-label={`${label} vorbereiten`}
            title="Name, Beschreibung und Bilder für das echte Konto vorbereiten"
            onClick={() => onPrepare(slot.channel_id as number)}
          >
            Vorbereiten
          </button>
        )}
    </li>
  );
}

function handleHint(task: ChannelSetupTask, handle: string): string {
  const state = task.handle_check[handle];
  if (state === "free") return "frei";
  if (state === "taken") return "vergeben";
  return task.platform === "youtube"
    ? "nicht geprüft"
    : "bei der Anmeldung prüfen";
}

function TaskCard({
  task,
  canEdit,
  mailLive,
  onChanged,
}: {
  task: ChannelSetupTask;
  canEdit: boolean;
  mailLive: boolean;
  onChanged: (connectChannel?: number) => Promise<void>;
}) {
  const [testMail, setTestMail] = useState<string | null>(null);
  const [idea, setIdea] = useState("");
  const [uploadHint, setUploadHint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState<ChannelSetupAiPart | null>(null);
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

  // own picture from the PC: cut to the platform size, replaces the AI version
  function uploadImage(kind: "avatar" | "banner", file: File) {
    setUploadHint(null);
    void run(async () => {
      const res = await api.uploadChannelSetupImage(task.id, kind, file);
      setUploadHint(res.hint);
    });
  }

  // own text: saved as typed (name changes redraw the lettering on the pictures)
  const saveField =
    (field: "display_name" | "handle" | "bio") =>
    (value: string): Promise<boolean> =>
      run(() => api.updateChannelSetup(task.id, { [field]: value }));

  function done() {
    let channelId: number | undefined;
    void run(
      async () => {
        channelId = (await api.completeChannelSetup(task.id)).channel_id;
      },
      () => channelId,
    );
  }

  // one AI symbol per field: only that value is created anew (pictures together)
  function aiRedo(part: ChannelSetupAiPart) {
    setThinking(part);
    void run(async () => {
      await api.researchChannelSetup(task.id, part, idea);
    }).finally(() => setThinking(null));
  }

  const aiFor = (part: ChannelSetupAiPart, label: string, hint: string) =>
    canEdit ? (
      <AiButton
        label={label}
        hint={hint}
        thinking={thinking === part}
        disabled={busy}
        onClick={() => aiRedo(part)}
      />
    ) : null;

  const img = (kind: "avatar" | "banner") =>
    `${api.channelSetupImage(task.id, kind)}?v=${stamp}`;

  return (
    <article className="card cs-task" aria-label={`Aufgabe ${title}`}>
      <div className="cs-task-head">
        <div className="chip-row">
          <span className={`chip chip-${task.platform}`}>
            {task.platform_label}
          </span>
          <span className="chip">{LANG[task.language]}</span>
          <span className="chip">{task.content_project}</span>
          {task.text_source === "mock" && <Badge tone="info">Testtexte</Badge>}
        </div>
        <div className="row-actions">
          <a
            className="btn btn-primary"
            href={task.signup_url}
            target="_blank"
            rel="noreferrer"
          >
            {task.platform === "youtube"
              ? "Kanal bei YouTube erstellen"
              : `Bei ${task.platform_label} registrieren`}
          </a>
        </div>
      </div>

      <div className="cs-task-body">
        <div className="cs-images">
          <div className="cs-avatar-row">
            {task.has_avatar && (
              <figure>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <div className="cs-pic">
                  <img
                    className="cs-avatar"
                    src={img("avatar")}
                    alt={`Profilbild ${task.display_name}`}
                  />
                  {canEdit && (
                    <UploadButton
                      label="Eigenes Profilbild hochladen"
                      hint="PNG, JPG oder WebP, quadratisch, mindestens 800 × 800 Pixel. Wichtiges in die Mitte, die Plattform schneidet einen Kreis aus."
                      disabled={busy}
                      onFile={(f) => uploadImage("avatar", f)}
                    />
                  )}
                </div>
                <figcaption>
                  <a href={img("avatar")} download className="small">
                    Profilbild laden
                  </a>
                  {task.uploaded.includes("avatar") && (
                    <Badge tone="ok">Eigenes Bild</Badge>
                  )}
                </figcaption>
              </figure>
            )}
            {(task.has_avatar || task.has_banner) &&
              aiFor(
                "images",
                task.has_banner
                  ? "Profilbild und Banner von der KI neu gestalten"
                  : "Profilbild von der KI neu gestalten",
                task.has_banner
                  ? "Die KI gestaltet Profilbild und Banner zusammen neu: neue Farben und neues Muster, beide passend zueinander. Jeder Klick gibt einen neuen Entwurf."
                  : "Die KI gestaltet das Profilbild neu: neue Farben und neues Muster. Jeder Klick gibt einen neuen Entwurf.",
              )}
          </div>
          <p className="muted small cs-art-source">
            {task.uploaded.includes("avatar") &&
            (!task.has_banner || task.uploaded.includes("banner")) ? (
              <Badge tone="ok">Eigene Bilder</Badge>
            ) : task.image_source === "ai" ? (
              <Badge tone="ok">Von der Bild-KI gestaltet</Badge>
            ) : (
              <Badge tone="info">Einfache Grafik</Badge>
            )}
            {task.image_note && <span> {task.image_note}</span>}
            {uploadHint && <span role="status"> {uploadHint}</span>}
          </p>
          {task.has_banner && (
            <figure>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <div className="cs-pic">
                <img
                  className="cs-banner"
                  src={img("banner")}
                  alt={`Banner ${task.display_name}`}
                />
                {canEdit && (
                  <UploadButton
                    label="Eigenen Banner hochladen"
                    hint="PNG, JPG oder WebP, ideal 2560 × 1440 Pixel (16:9). Schrift und Logo in die Mitte (1546 × 423), dieser Bereich ist auf jedem Gerät sichtbar."
                    disabled={busy}
                    onFile={(f) => uploadImage("banner", f)}
                  />
                )}
              </div>
              <figcaption>
                <a href={img("banner")} download className="small">
                  Banner laden (2560 × 1440)
                </a>
                {task.uploaded.includes("banner") && (
                  <Badge tone="ok">Eigenes Bild</Badge>
                )}
              </figcaption>
            </figure>
          )}
        </div>

        <div className="cs-fields">
          {canEdit && (
            <div className="cs-copy">
              <label htmlFor={`cs-idea-${task.id}`} className="muted small">
                Deine Idee für die KI (optional)
              </label>
              <input
                id={`cs-idea-${task.id}`}
                value={idea}
                maxLength={300}
                placeholder="z. B. „Name mit Gehirn oder Explosion, frech und jung“"
                onChange={(e) => setIdea(e.target.value)}
              />
              <span className="muted small">
                Die KI-Symbole bauen deine Idee ein. Eigene Texte kannst du
                direkt in die Felder tippen oder einfügen, sie werden beim
                Verlassen des Felds gespeichert.
              </span>
            </div>
          )}
          <CopyField
            id={`cs-name-${task.id}`}
            label="Name"
            value={task.display_name}
            maxLength={120}
            onSave={canEdit ? saveField("display_name") : undefined}
            ai={aiFor(
              "name",
              "Neuen Namen von der KI erstellen",
              "Die KI sucht mit aktuellen Trends einen neuen Namen passend zu Themenbereich und Unterthemen. Profilbild und Banner zeigen danach den neuen Namen.",
            )}
          />
          <CopyField
            id={`cs-handle-${task.id}`}
            label={`Benutzername (${handleHint(task, task.handle)})`}
            value={task.handle}
            maxLength={40}
            onSave={canEdit ? saveField("handle") : undefined}
            ai={aiFor(
              "handle",
              "Neuen Benutzernamen von der KI erstellen",
              "Die KI schlägt einen neuen Benutzernamen vor, der zum Namen passt.",
            )}
          />
          {task.alt_handles.length > 0 && (
            <p className="muted small">
              Falls vergeben:{" "}
              {task.alt_handles
                .map((h) => `${h} (${handleHint(task, h)})`)
                .join(", ")}
            </p>
          )}
          <CopyField
            id={`cs-bio-${task.id}`}
            label="Bio"
            value={task.bio}
            multiline
            maxLength={task.bio_max}
            onSave={canEdit ? saveField("bio") : undefined}
            ai={aiFor(
              "bio",
              "Neue Bio von der KI erstellen",
              "Die KI schreibt eine neue Bio passend zu Themenbereich und Unterthemen.",
            )}
          />
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
              <p className="muted small">
                Keine eigene E-Mail nötig: Brand-Kanal unter dem Geschäftskonto.
              </p>
            )
          )}
          {task.email_status === "mock" && (
            <p className="small">
              <Badge tone="warn">Noch nicht angelegt</Badge> Diese Adresse
              empfängt noch keine Mails. Nicht für die Anmeldung verwenden,
              solange die Weiterleitung fehlt.
              {task.email_error ? ` ${task.email_error}` : ""}{" "}
              {canEdit && mailLive && (
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={busy}
                  onClick={() =>
                    void run(() => api.retryChannelSetupEmail(task.id))
                  }
                >
                  Weiterleitung jetzt anlegen
                </button>
              )}
            </p>
          )}
          {task.email_status === "created" && canEdit && (
            <p className="small">
              <button
                type="button"
                className="btn btn-small"
                disabled={busy}
                onClick={() => {
                  setTestMail(null);
                  api
                    .sendAliasTestMail(task.id)
                    .then((r) => setTestMail(r.message))
                    .catch((e: Error) => setTestMail(e.message));
                }}
              >
                Testmail senden
              </button>{" "}
              <span className="muted">
                Kommt sie in deinem Postfach an, funktioniert die Adresse.
              </span>
              {testMail && (
                <span role="status" className="cs-testmail">
                  {" "}
                  {testMail}
                </span>
              )}
            </p>
          )}
          {task.email_status === "failed" && (
            <p className="small">
              <Badge tone="danger">E-Mail fehlgeschlagen</Badge>{" "}
              {task.email_error}{" "}
              {canEdit && (
                <button
                  type="button"
                  className="btn btn-small"
                  disabled={busy}
                  onClick={() =>
                    void run(() => api.retryChannelSetupEmail(task.id))
                  }
                >
                  Erneut versuchen
                </button>
              )}
            </p>
          )}
        </div>
      </div>

      {(task.name_options.length > 0 || task.research_facts.length > 0) && (
        <section className="cs-research" aria-label={`Namensideen ${title}`}>
          {task.name_options.length > 0 && (
            <>
              <h4>Weitere Namensideen</h4>
              <ul className="cs-options">
                {task.name_options.map((o) => (
                  <li key={o.name}>
                    <span>
                      <strong>{o.name}</strong>
                      {o.reason && (
                        <span className="muted small"> – {o.reason}</span>
                      )}
                    </span>
                    {canEdit && (
                      <button
                        type="button"
                        className="btn btn-small"
                        disabled={busy}
                        aria-label={`${o.name} übernehmen`}
                        onClick={() => {
                          void run(() =>
                            api.updateChannelSetup(task.id, {
                              display_name: o.name,
                            }),
                          );
                        }}
                      >
                        Übernehmen
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          {task.research_facts.length > 0 && (
            <details>
              <summary>
                Datengrundlage{" "}
                <Badge tone={task.research_live ? "ok" : "info"}>
                  {task.research_live
                    ? "mit YouTube-Live-Daten"
                    : "ohne YouTube-Live-Daten"}
                </Badge>
              </summary>
              <ul className="small">
                {task.research_facts.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}

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
  const [mailCheck, setMailCheck] = useState<MailRoutingCheck | null>(null);
  const [checking, setChecking] = useState(false);

  async function checkMail() {
    setChecking(true);
    setError(null);
    try {
      setMailCheck(await api.checkMailRouting());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  }
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
      setNotice(
        made.length
          ? `${made.length} Kanäle vorbereitet.`
          : "Es fehlt kein Kanal.",
      );
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function prepareFor(channelId: number) {
    setBusy(-channelId);
    setError(null);
    try {
      await api.prepareChannelSetupFor(channelId);
      setNotice("Kanal vorbereitet. Die Aufgabe steht oben.");
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
          E-Mail-Weiterleitungen laufen im Testmodus
          {mail.domain ? ` (Domain ${mail.domain})` : ""}. Es wird noch nichts
          bei Cloudflare angelegt.
        </p>
      )}
      {mail?.problem && (
        <p className="small">
          <Badge tone="danger">E-Mail</Badge> {mail.problem}
        </p>
      )}
      {mail && canEdit && (
        <div className="small cs-mailcheck">
          <button
            type="button"
            className="btn btn-small"
            disabled={checking}
            onClick={() => void checkMail()}
          >
            {checking ? "Prüft …" : "E-Mail-Weiterleitung prüfen"}
          </button>
          {mailCheck && (
            <div role="status">
              <Badge tone={mailCheck.ok ? "ok" : "danger"}>
                {mailCheck.ok
                  ? "Weiterleitung bereit"
                  : "Weiterleitung nicht bereit"}
              </Badge>
              {mailCheck.rules_used !== null &&
                ` ${mailCheck.rules_used} von ${mailCheck.rule_limit} Regeln belegt.`}
              {mailCheck.findings.length > 0 && (
                <ul>
                  {mailCheck.findings.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      <Section title={`Offene Aufgaben „Kanal erstellen“ (${tasks.length})`}>
        {tasks.length === 0 ? (
          <p className="muted">Keine offenen Aufgaben.</p>
        ) : (
          <div className="cs-tasks">
            {tasks.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                canEdit={canEdit}
                mailLive={mail?.mode === "live"}
                onChanged={changed}
              />
            ))}
          </div>
        )}
      </Section>

      <Section
        title={`Kanäle je Themenbereich${missingTotal ? ` (${missingTotal} fehlen)` : ""}`}
      >
        {coverage === null ? (
          <p className="muted">Lädt …</p>
        ) : (
          <div className="cs-coverage">
            {coverage.map((c) => (
              <article
                key={c.project_id}
                className="card"
                aria-label={`Themenbereich ${c.project}`}
              >
                <div className="cs-task-head">
                  <h3>{c.project}</h3>
                  {canEdit && c.missing > 0 && (
                    <button
                      className="btn btn-primary btn-small"
                      disabled={busy !== null}
                      onClick={() => void prepare(c.project_id)}
                    >
                      {busy === c.project_id
                        ? "Bereite vor …"
                        : `${c.missing} fehlende vorbereiten`}
                    </button>
                  )}
                </div>
                <ul className="cs-slots">
                  {c.slots.map((s) => (
                    <SlotChip
                      key={`${s.platform}-${s.language}`}
                      slot={s}
                      busy={busy !== null}
                      onPrepare={
                        canEdit ? (id) => void prepareFor(id) : undefined
                      }
                    />
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
