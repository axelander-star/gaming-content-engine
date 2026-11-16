"use client";

// Comments: the engine answers harmless comments itself; criticism, sensitive
// topics and TikTok land here with a draft to check, edit, send or copy.

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS, formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  Channel,
  CommentKind,
  CommentStats,
  CommentStatus,
  ViewerComment,
} from "@/lib/types";

const TABS: [CommentStatus, string][] = [
  ["review", "Zu prüfen"],
  ["new", "Ohne Entwurf"],
  ["failed", "Fehlgeschlagen"],
  ["sent", "Beantwortet"],
  ["ignored", "Ignoriert"],
];
const KIND: Record<CommentKind, [string, "ok" | "warn" | "danger" | "info" | "neutral"]> = {
  question: ["Frage", "info"],
  praise: ["Lob", "ok"],
  criticism: ["Kritik", "warn"],
  sensitive: ["Heikel", "danger"],
  spam: ["Spam", "neutral"],
  other: ["Sonstiges", "neutral"],
};

function CommentCard({
  c,
  canAct,
  onChanged,
}: {
  c: ViewerComment;
  canAct: boolean;
  onChanged: () => Promise<void>;
}) {
  const [reply, setReply] = useState(c.reply_text ?? "");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = c.status !== "sent" && c.status !== "ignored";
  const [kindLabel, kindTone] = KIND[c.kind];

  useEffect(() => setReply(c.reply_text ?? ""), [c.reply_text]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(reply);
    } catch {
      (document.getElementById(`reply-${c.id}`) as HTMLTextAreaElement | null)?.select();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <article className="card cm-card" aria-label={`Kommentar von ${c.author ?? "unbekannt"}`}>
      <div className="cm-head">
        <div className="chip-row">
          <span className={`chip chip-${c.platform}`}>{PLATFORM_LABELS[c.platform]}</span>
          <span className="chip">{c.channel}</span>
          <Badge tone={kindTone}>{kindLabel}</Badge>
          {c.is_test && <Badge tone="info">Testkommentar</Badge>}
        </div>
        <span className="muted small">{c.written_at ? formatDateTime(c.written_at) : ""}</span>
      </div>
      {c.post_title && (
        <p className="muted small">
          Unter:{" "}
          {c.post_url ? (
            <a href={c.post_url} target="_blank" rel="noreferrer">
              {c.post_title}
            </a>
          ) : (
            c.post_title
          )}
        </p>
      )}
      <blockquote className="cm-text">
        <strong>{c.author ?? "Unbekannt"}:</strong> {c.text}
      </blockquote>
      {c.review_reason && open && <p className="small cm-reason">{c.review_reason}</p>}
      {c.error && <p className="small error">{c.error}</p>}
      {open ? (
        <>
          <label className="cm-reply">
            Antwort
            <textarea
              id={`reply-${c.id}`}
              rows={2}
              maxLength={300}
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              disabled={!canAct}
            />
          </label>
          <ErrorText error={error} />
          {canAct && (
            <div className="row-actions">
              {c.can_send ? (
                <button
                  className="btn btn-primary"
                  disabled={busy || !reply.trim()}
                  onClick={() => void run(() => api.sendComment(c.id, reply))}
                >
                  Antwort senden
                </button>
              ) : (
                <>
                  <button className="btn btn-primary" disabled={!reply.trim()} onClick={() => void copy()}>
                    {copied ? "Kopiert" : "Antwort kopieren"}
                  </button>
                  <button
                    className="btn"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        if (reply !== (c.reply_text ?? "")) await api.editCommentReply(c.id, reply);
                        await api.commentDone(c.id);
                      })
                    }
                  >
                    Erledigt
                  </button>
                </>
              )}
              <button className="btn" disabled={busy} onClick={() => void run(() => api.redraftComment(c.id))}>
                Neu formulieren
              </button>
              <button
                className="btn btn-ghost"
                disabled={busy}
                onClick={() => void run(() => api.ignoreComment(c.id))}
              >
                Ignorieren
              </button>
            </div>
          )}
        </>
      ) : (
        c.reply_text && (
          <p className="cm-sent">
            <span className="muted small">
              Antwort{c.reply_is_mock ? " (Test, nicht wirklich gesendet)" : ""}:
            </span>{" "}
            {c.reply_text}
          </p>
        )
      )}
    </article>
  );
}

function ManualForm({ channels, onAdded }: { channels: Channel[]; onAdded: () => Promise<void> }) {
  const [channelId, setChannelId] = useState<number | "">(channels[0]?.id ?? "");
  const [author, setAuthor] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (channelId === "") return;
    setError(null);
    try {
      await api.addManualComment(channelId, text, author);
      setText("");
      setAuthor("");
      await onAdded();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (channels.length === 0) return null;
  return (
    <Section title="TikTok-Kommentar einfügen">
      <p className="muted small">
        TikTok bietet keine Schnittstelle für Kommentare. Kopiere einen Kommentar hierher, dann
        schreibt die Engine eine Antwort, die du in der App einfügst.
      </p>
      <form className="cm-manual" onSubmit={submit} aria-label="TikTok-Kommentar einfügen">
        <label>
          Kanal
          <select value={channelId} onChange={(e) => setChannelId(Number(e.target.value))}>
            {channels.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Name (optional)
          <input value={author} onChange={(e) => setAuthor(e.target.value)} maxLength={200} />
        </label>
        <label className="cm-manual-text">
          Kommentar
          <textarea rows={2} required value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <button className="btn btn-primary">Antwort vorschlagen</button>
      </form>
      <ErrorText error={error} />
    </Section>
  );
}

export function CommentsView() {
  const { user } = useAuth();
  const canAct = hasRole(user?.role, "operator");
  const [tab, setTab] = useState<CommentStatus>("review");
  const [rows, setRows] = useState<ViewerComment[] | null>(null);
  const [stats, setStats] = useState<CommentStats | null>(null);
  const [tiktok, setTiktok] = useState<Channel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [list, st] = await Promise.all([api.comments(tab), api.commentStats()]);
    setRows(list);
    setStats(st);
  }, [tab]);

  useEffect(() => {
    load().catch((e: Error) => setError(e.message));
  }, [load]);

  useEffect(() => {
    api
      .channels()
      .then((all) => setTiktok(all.filter((c) => c.platform === "tiktok")))
      .catch(() => setTiktok([]));
  }, []);

  async function runNow() {
    setError(null);
    try {
      await api.runComments();
      setNotice("Abruf gestartet. Neue Kommentare erscheinen in ein bis zwei Minuten.");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Kommentare"
        description="Fragen und Lob beantwortet die Engine selbst, kurz und im Ton des Kanals. Kritik, heikle Themen und TikTok landen hier mit einem Entwurf, den du prüfst."
      />
      {stats && !stats.live && (
        <p className="small">
          <Badge tone="info">Testbetrieb</Badge> Antworten werden nur simuliert, nichts wird
          wirklich gepostet.
        </p>
      )}
      {stats && !stats.auto_reply && (
        <p className="small">
          <Badge tone="warn">Automatik aus</Badge> Alle Antworten warten auf dich.
        </p>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <ErrorText error={error} />
      <div className="cm-toolbar">
        <div className="tabs" role="tablist" aria-label="Status der Kommentare">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              className={`tab${tab === key ? " is-active" : ""}`}
              onClick={() => setTab(key)}
            >
              {label} {stats?.by_status[key] ?? 0}
            </button>
          ))}
        </div>
        {canAct && (
          <button className="btn" onClick={() => void runNow()}>
            Jetzt abrufen
          </button>
        )}
      </div>
      <div className="cm-list">
        {rows === null ? (
          <p className="muted">Lädt …</p>
        ) : rows.length === 0 ? (
          <p className="muted">
            {tab === "review" ? "Nichts zu prüfen. Alles beantwortet." : "Keine Kommentare in dieser Ansicht."}
          </p>
        ) : (
          rows.map((c) => <CommentCard key={c.id} c={c} canAct={canAct} onChanged={load} />)
        )}
      </div>
      {canAct && <ManualForm channels={tiktok} onAdded={async () => { setTab("review"); await load(); }} />}
    </>
  );
}
