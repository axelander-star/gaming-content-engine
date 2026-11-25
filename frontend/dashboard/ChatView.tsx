"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, KeyboardEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Icon } from "@/components/icons";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { hasRole } from "@/lib/roles";
import { useDictation, useSpeaker } from "@/lib/speech";
import type {
  AIStatus,
  ChatAction,
  ChatAttachment,
  ChatMessage,
  WeekPlan,
} from "@/lib/types";

const AUTO_READ_KEY = "gce:chat:autoread";
const FILE_TYPES = "image/png,image/jpeg,application/pdf";

/** The question keeps "[PDF „x“ (3 Seiten)]" lines for the AI; the chips show them here. */
function visibleText(m: ChatMessage): string {
  if (m.attachments.length === 0) return m.text;
  return m.text
    .split("\n")
    .filter((line) => !/^\[(Bild|PDF) „.*\]$/.test(line))
    .join("\n");
}

function fileLabel(a: ChatAttachment): string {
  if (a.content_type === "application/pdf") return `${a.filename} · ${a.pages ?? 0} S.`;
  return a.filename;
}

function AttachmentChips({ files }: { files: ChatAttachment[] }) {
  return (
    <div className="chat-files">
      {files.map((a) =>
        a.content_type.startsWith("image/") ? (
          <a key={a.id} href={api.chatFileUrl(a.id)} target="_blank" rel="noreferrer">
            <img src={api.chatFileUrl(a.id)} alt={a.filename} className="chat-thumb" />
          </a>
        ) : (
          <a
            key={a.id}
            className="chip"
            href={api.chatFileUrl(a.id)}
            target="_blank"
            rel="noreferrer"
          >
            PDF {fileLabel(a)}
          </a>
        ),
      )}
    </div>
  );
}

/** Quick prompts built from the operator's own topic areas, never from preset topics. */
function suggestions(areas: string[]): string[] {
  const [first, second] = areas;
  const out = ["Status"];
  if (first) out.push(`Mittwoch zusätzlich ${first}`);
  if (second ?? first) out.push(`Freitag kein ${second ?? first}`);
  out.push("Zeig mir die Ideen");
  return out;
}

const ACTION_STATUS: Record<
  ChatAction["status"],
  [string, "ok" | "neutral" | "danger"]
> = {
  done: ["Ausgeführt", "ok"],
  undone: ["Rückgängig gemacht", "neutral"],
  failed: ["Nicht ausgeführt", "danger"],
};

const shortDate = (iso: string) =>
  new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit" }).format(
    new Date(`${iso}T12:00:00`),
  );

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function ActionCard({
  action,
  canUndo,
  onUndo,
}: {
  action: ChatAction;
  canUndo: boolean;
  onUndo: (id: number) => void;
}) {
  const [label, tone] = ACTION_STATUS[action.status];
  return (
    <div
      className={`action-card action-${action.status}`}
      role="group"
      aria-label="Aktion"
    >
      <div className="action-main">
        <Badge tone={tone}>{label}</Badge>
        <span>
          {action.status === "failed" ? action.error : action.summary}
        </span>
      </div>
      {action.undoable && canUndo && (
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={() => onUndo(action.id)}
        >
          Rückgängig
        </button>
      )}
    </div>
  );
}

function WeekPanel({
  plan,
  onWeek,
}: {
  plan: WeekPlan | null;
  onWeek: (start: string) => void;
}) {
  if (!plan) return null;
  return (
    <Section title="Redaktionsplan">
      <div className="week-nav">
        <button
          type="button"
          className="btn btn-ghost btn-small"
          aria-label="Vorige Woche"
          onClick={() => onWeek(addDays(plan.start, -7))}
        >
          ‹
        </button>
        <span>
          {shortDate(plan.start)} – {shortDate(plan.end)}
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-small"
          aria-label="Nächste Woche"
          onClick={() => onWeek(addDays(plan.start, 7))}
        >
          ›
        </button>
      </div>
      <ul className="week-days" aria-label="Wochenplan">
        {plan.days.map((d) => (
          <li key={d.day} className={d.is_today ? "is-today" : undefined}>
            <span className="week-day">
              {d.weekday.slice(0, 2)}{" "}
              <span className="muted small">{shortDate(d.day)}</span>
            </span>
            <span className="week-projects">
              {d.projects.length === 0 ? (
                <span className="muted small">frei</span>
              ) : (
                d.projects.map((p) => (
                  <span key={p.id} className="chip" title={p.note ?? undefined}>
                    {p.name}
                  </span>
                ))
              )}
            </span>
          </li>
        ))}
      </ul>
      <div>
        <h3 className="small-heading">Schwerpunkte</h3>
        {plan.focus.length === 0 ? (
          <p className="muted small">Keine Schwerpunkte in dieser Woche.</p>
        ) : (
          <ul className="focus-list">
            {plan.focus.map((f) => (
              <li key={f.id}>
                <strong>{f.topic}</strong>{" "}
                <span className="muted small">
                  {f.project} · {shortDate(f.starts_on)}–{shortDate(f.ends_on)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="muted small">
        Der Plan legt Themen und Tage fest. Wie viele Videos ein Kanal bekommt,
        entscheidet die Publishing-Strategie anhand der Daten.
      </p>
    </Section>
  );
}

/** Chat assistant with action cards and the editorial week plan (extension E4). */
export function ChatView() {
  const { user } = useAuth();
  const canWrite = hasRole(user?.role, "operator");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [plan, setPlan] = useState<WeekPlan | null>(null);
  const [week, setWeek] = useState<string | undefined>(undefined);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [files, setFiles] = useState<ChatAttachment[]>([]);
  const [areas, setAreas] = useState<string[]>([]);
  const [uploading, setUploading] = useState(0);
  const [autoRead, setAutoRead] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const speaker = useSpeaker();
  const dictation = useDictation((spoken) =>
    setText((prev) => (prev.trim() ? `${prev.trim()} ${spoken}` : spoken)),
  );

  useEffect(() => {
    api
      .projects()
      .then((all) => setAreas(all.filter((p) => p.status === "active").map((p) => p.name)))
      .catch(() => setAreas([]));
  }, []);

  useEffect(() => {
    try {
      setAutoRead(window.localStorage.getItem(AUTO_READ_KEY) === "1");
    } catch {
      setAutoRead(false);
    }
  }, []);

  function toggleAutoRead() {
    const next = !autoRead;
    setAutoRead(next);
    if (!next) speaker.stop();
    try {
      window.localStorage.setItem(AUTO_READ_KEY, next ? "1" : "0");
    } catch {
      // private mode: keep it for this visit only
    }
  }

  async function onPickFiles(e: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(e.target.files ?? []);
    e.target.value = "";
    setError(null);
    for (const file of picked) {
      setUploading((n) => n + 1);
      try {
        const att = await api.uploadChatFile(file);
        setFiles((prev) => [...prev, att]);
      } catch (err) {
        setError(`${file.name}: ${(err as Error).message}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  }

  const loadPlan = useCallback(() => {
    api
      .weekPlan(week)
      .then(setPlan)
      .catch((e: Error) => setError(e.message));
  }, [week]);

  useEffect(() => {
    api
      .chatMessages()
      .then(setMessages)
      .catch((e: Error) => setError(e.message));
    api
      .aiStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  useEffect(loadPlan, [loadPlan]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [messages]);

  async function send(value: string) {
    const trimmed = value.trim();
    if ((!trimmed && files.length === 0) || busy || uploading > 0) return;
    if (dictation.listening) dictation.stop();
    setBusy(true);
    setError(null);
    try {
      const exchange =
        files.length > 0
          ? await api.sendChatWithFiles(trimmed, files.map((f) => f.id))
          : await api.sendChat(trimmed);
      setMessages((prev) => [...prev, exchange.question, exchange.answer]);
      setText("");
      setFiles([]);
      if (autoRead) void speaker.speak(exchange.answer.id, exchange.answer.text);
      loadPlan();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void send(text);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(text);
    }
  }

  async function undo(id: number) {
    setError(null);
    try {
      const updated = await api.undoChatAction(id);
      setMessages((prev) =>
        prev.map((m) => ({
          ...m,
          actions: m.actions.map((a) => (a.id === id ? updated : a)),
        })),
      );
      loadPlan();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Assistent"
        description="Plan per Chat steuern, Bilder und PDFs zeigen, per Sprache fragen und Antworten vorlesen lassen. Veröffentlichen kann der Assistent nicht."
      />
      <div className="chat-layout">
        <section className="card chat-panel" aria-label="Chat">
          <div className="ai-head">
            {status && (
              <Badge tone={status.live ? "warn" : "neutral"}>
                {status.live
                  ? "Claude live: zählt zur KI-Monatsgrenze"
                  : "Test (Mock): Befehlserkennung, keine Kosten"}
              </Badge>
            )}
            <label className="chat-toggle">
              <input type="checkbox" checked={autoRead} onChange={toggleAutoRead} />
              Antworten vorlesen
            </label>
          </div>
          <div className="chat-log" aria-live="polite">
            {messages.length === 0 && (
              <p className="muted">
                Noch keine Nachrichten. Schreib zum Beispiel „Status“ oder „Mittwoch
                zusätzlich {areas[0] ?? "<Themenbereich>"}“.
              </p>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`chat-msg chat-${m.role}`}>
                {m.attachments.length > 0 && <AttachmentChips files={m.attachments} />}
                {visibleText(m).trim() && (
                  <div className="chat-bubble">
                    {visibleText(m)}
                    {m.role === "assistant" && (
                      <button
                        type="button"
                        className="icon-btn chat-speak"
                        aria-label={speaker.playing === m.id ? "Vorlesen stoppen" : "Vorlesen"}
                        title={speaker.playing === m.id ? "Stopp" : "Vorlesen"}
                        onClick={() =>
                          speaker.playing === m.id
                            ? speaker.stop()
                            : void speaker.speak(m.id, m.text)
                        }
                      >
                        <Icon name={speaker.playing === m.id ? "stop" : "speaker"} size={16} />
                      </button>
                    )}
                  </div>
                )}
                {m.actions.length > 0 && (
                  <div className="chat-actions">
                    {m.actions.map((a) => (
                      <ActionCard
                        key={a.id}
                        action={a}
                        canUndo={canWrite}
                        onUndo={undo}
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}
            <div ref={endRef} />
          </div>
          <ErrorText error={error ?? dictation.error ?? speaker.error} />
          {canWrite ? (
            <>
              <div className="chip-row" aria-label="Vorschläge">
                {suggestions(areas).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="chip chip-btn"
                    onClick={() => setText(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
              {(files.length > 0 || uploading > 0) && (
                <div className="chat-pending" aria-label="Angehängte Dateien">
                  {files.map((f) => (
                    <span key={f.id} className="chip">
                      {fileLabel(f)}
                      <button
                        type="button"
                        className="chip-x"
                        aria-label={`${f.filename} entfernen`}
                        onClick={() => setFiles((prev) => prev.filter((x) => x.id !== f.id))}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  {uploading > 0 && <span className="muted small">Lädt hoch …</span>}
                </div>
              )}
              <form className="chat-form" onSubmit={onSubmit}>
                <div className="chat-tools">
                  <input
                    ref={fileRef}
                    type="file"
                    accept={FILE_TYPES}
                    multiple
                    hidden
                    onChange={(e) => void onPickFiles(e)}
                    data-testid="chat-file"
                  />
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label="Bild oder PDF anhängen"
                    title="Bild oder PDF anhängen"
                    onClick={() => fileRef.current?.click()}
                  >
                    <Icon name="paperclip" />
                  </button>
                  {dictation.supported && (
                    <button
                      type="button"
                      className={`icon-btn${dictation.listening ? " is-recording" : ""}`}
                      aria-label={dictation.listening ? "Aufnahme beenden" : "Sprechen"}
                      aria-pressed={dictation.listening}
                      title={dictation.listening ? "Aufnahme beenden" : "Sprechen"}
                      onClick={() => (dictation.listening ? dictation.stop() : dictation.start())}
                    >
                      <Icon name={dictation.listening ? "stop" : "mic"} />
                    </button>
                  )}
                </div>
                <textarea
                  aria-label="Nachricht an den Assistenten"
                  rows={2}
                  maxLength={2000}
                  value={text}
                  placeholder={
                    dictation.listening ? "Ich höre zu …" : "Schreib, sprich oder häng eine Datei an"
                  }
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={onKeyDown}
                />
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={busy || uploading > 0 || (!text.trim() && files.length === 0)}
                >
                  {busy ? "…" : "Senden"}
                </button>
              </form>
            </>
          ) : (
            <p className="muted small">
              Mit der Rolle Betrachter kannst du den Chat nur lesen.
            </p>
          )}
        </section>
        <WeekPanel plan={plan} onWeek={setWeek} />
      </div>
    </>
  );
}
