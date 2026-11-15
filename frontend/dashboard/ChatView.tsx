"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { hasRole } from "@/lib/roles";
import type { AIStatus, ChatAction, ChatMessage, WeekPlan } from "@/lib/types";

const SUGGESTIONS = [
  "Status",
  "Diese Woche GTA 6",
  "Mittwoch zusätzlich Ernährung",
  "Freitag kein Gaming",
  "Zeig mir die Ideen",
];

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
  const endRef = useRef<HTMLDivElement>(null);

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
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const exchange = await api.sendChat(trimmed);
      setMessages((prev) => [...prev, exchange.question, exchange.answer]);
      setText("");
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
        description="Plan per Chat steuern: Schwerpunkte setzen, Tage planen, Bereiche pausieren. Veröffentlichen kann der Assistent nicht."
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
          </div>
          <div className="chat-log" aria-live="polite">
            {messages.length === 0 && (
              <p className="muted">
                Noch keine Nachrichten. Schreib zum Beispiel „Diese Woche GTA 6“
                oder „Mittwoch zusätzlich Ernährung“.
              </p>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`chat-msg chat-${m.role}`}>
                <div className="chat-bubble">{m.text}</div>
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
          <ErrorText error={error} />
          {canWrite ? (
            <>
              <div className="chip-row" aria-label="Vorschläge">
                {SUGGESTIONS.map((s) => (
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
              <form className="chat-form" onSubmit={onSubmit}>
                <textarea
                  aria-label="Nachricht an den Assistenten"
                  rows={2}
                  maxLength={2000}
                  value={text}
                  placeholder="Was soll ich am Plan ändern?"
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={onKeyDown}
                />
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={busy || !text.trim()}
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
