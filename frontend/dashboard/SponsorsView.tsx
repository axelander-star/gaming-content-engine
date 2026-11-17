"use client";

// Sponsor inbox (Ausbau A9): paste a brand's mail, get category, warnings, a price
// suggestion and a reply draft. Nothing is sent; the draft is copied by hand.

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type { ContentProject, SponsorInbox, SponsorInquiry, SponsorStatus } from "@/lib/types";

const STATUS: Record<SponsorStatus, string> = {
  new: "Neu",
  replied: "Beantwortet",
  won: "Zusage",
  declined: "Abgelehnt",
  archived: "Archiv",
};
const euro = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : `${n.toLocaleString("de-DE", { maximumFractionDigits: 0 })} €`;

function InquiryCard({
  inq,
  projects,
  onChange,
}: {
  inq: SponsorInquiry;
  projects: ContentProject[];
  onChange: () => void;
}) {
  const [draft, setDraft] = useState(inq.draft);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => setDraft(inq.draft), [inq.draft]);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
    } catch {
      setError("Kopieren nicht möglich, bitte den Text markieren.");
    }
  }

  const subject = inq.subject ? `Re: ${inq.subject}` : `Re: Kooperation ${inq.brand}`;
  const mailto = inq.contact_email
    ? `mailto:${inq.contact_email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(draft)}`
    : null;
  const b = inq.price_basis;
  return (
    <article className="card sponsor-card" aria-label={`Anfrage ${inq.brand}`}>
      <div className="feed-title">
        {inq.brand} <span className="chip">{inq.category_label}</span>{" "}
        <Badge tone={inq.status === "won" ? "ok" : inq.status === "new" ? "info" : "neutral"}>
          {STATUS[inq.status]}
        </Badge>
      </div>
      <div className="muted small">
        {inq.contact_email ?? "ohne Adresse"} · {formatDateTime(inq.received_at)} ·{" "}
        {inq.language.toUpperCase()}
        {inq.subject ? ` · „${inq.subject}“` : ""}
      </div>
      {inq.flags.length > 0 && (
        <ul className="sponsor-flags" aria-label="Warnungen">
          {inq.flags.map((f) => (
            <li key={f}>
              <Badge tone="warn">Achtung</Badge> {f}
            </li>
          ))}
        </ul>
      )}
      <details>
        <summary className="small">Anfrage lesen</summary>
        <pre className="mail-body">{inq.body}</pre>
      </details>
      {inq.category !== "spam" && (
        <>
          <p className="small">
            <strong>Preisvorschlag: {euro(inq.price_eur)} je Short</strong> (Spanne {euro(b.low)}–
            {euro(b.high)}, {b.bundle_posts ?? 3} Shorts {euro(b.bundle)}). {b.note}
          </p>
          <label className="small">
            Themenbereich{" "}
            <select
              value={inq.project_id ?? ""}
              onChange={(e) =>
                void run(() =>
                  api.updateSponsorInquiry(inq.id, {
                    project_id: e.target.value ? Number(e.target.value) : null,
                  }),
                )
              }
            >
              <option value="">keiner</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Antwortentwurf {inq.draft_source === "manual" ? "(bearbeitet)" : ""}
            <textarea rows={9} value={draft} onChange={(e) => setDraft(e.target.value)} />
          </label>
        </>
      )}
      <ErrorText error={error} />
      <div className="row-actions">
        {inq.category !== "spam" && (
          <>
            <button type="button" className="btn btn-small" onClick={() => void copy()}>
              {copied ? "Kopiert" : "Antwort kopieren"}
            </button>
            {mailto && (
              <a className="btn btn-ghost btn-small" href={mailto}>
                Im Mailprogramm öffnen
              </a>
            )}
            {draft !== inq.draft && (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                onClick={() => void run(() => api.updateSponsorInquiry(inq.id, { draft }))}
              >
                Entwurf speichern
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => void run(() => api.redraftSponsorInquiry(inq.id))}
            >
              Neu schreiben
            </button>
          </>
        )}
        {(["replied", "won", "declined", "archived"] as SponsorStatus[])
          .filter((s) => s !== inq.status)
          .map((s) => (
            <button
              key={s}
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => void run(() => api.updateSponsorInquiry(inq.id, { status: s }))}
            >
              {STATUS[s]}
            </button>
          ))}
      </div>
      {inq.status === "won" && (
        <p className="muted small">
          Zusage: Beitrag als Anzeige kennzeichnen und die Zahlung später unter „Konten“ als
          Einnahme „Sponsor“ eintragen.
        </p>
      )}
    </article>
  );
}

export function SponsorsView() {
  const { user } = useAuth();
  const allowed = hasRole(user?.role, "operator");
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [inbox, setInbox] = useState<SponsorInbox | null>(null);
  const [state, setState] = useState<SponsorStatus | undefined>(undefined);
  const [sender, setSender] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!allowed) return;
    api
      .sponsorInbox(state)
      .then(setInbox)
      .catch((e: Error) => setError(e.message));
  }, [state, allowed]);

  useEffect(() => {
    api
      .projects()
      .then((all) => setProjects(all.filter((p) => p.status !== "archived")))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.addSponsorInquiry({ sender, subject: subject || null, body });
      setSender("");
      setSubject("");
      setBody("");
      setState(undefined);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Sponsoren-Postfach"
        description="Markenanfrage einfügen: Die Engine sortiert sie, warnt bei Haken (Vorabzahlung, Glücksspiel, Krypto, nur Produkt), schlägt einen Preis aus deiner eigenen Reichweite vor und schreibt einen Antwortentwurf. Gesendet wird nichts."
      />
      <ErrorText error={error} />
      {!allowed ? (
        <p className="muted">Nur für Bediener und Admins.</p>
      ) : (
        <>
          <Section title="Anfrage einfügen">
            <form className="focus-form" aria-label="Anfrage einfügen" onSubmit={add}>
              <label>
                Absender
                <input
                  value={sender}
                  placeholder="Name <mail@marke.de>"
                  maxLength={400}
                  onChange={(e) => setSender(e.target.value)}
                />
              </label>
              <label>
                Betreff
                <input value={subject} maxLength={300} onChange={(e) => setSubject(e.target.value)} />
              </label>
              <label>
                Text der Mail
                <textarea rows={6} value={body} onChange={(e) => setBody(e.target.value)} required />
              </label>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                Einordnen und Antwort entwerfen
              </button>
            </form>
          </Section>
          <div className="toolbar" role="tablist" aria-label="Status">
            <button
              type="button"
              role="tab"
              aria-selected={state === undefined}
              className={state === undefined ? "btn btn-small" : "btn btn-ghost btn-small"}
              onClick={() => setState(undefined)}
            >
              Offen
            </button>
            {(Object.keys(STATUS) as SponsorStatus[]).map((s) => (
              <button
                key={s}
                type="button"
                role="tab"
                aria-selected={state === s}
                className={state === s ? "btn btn-small" : "btn btn-ghost btn-small"}
                onClick={() => setState(s)}
              >
                {STATUS[s]} ({inbox?.counts[s] ?? 0})
              </button>
            ))}
          </div>
          {inbox && inbox.inquiries.length === 0 && (
            <p className="muted small">Keine Anfragen in dieser Ansicht.</p>
          )}
          <div className="sponsor-list">
            {inbox?.inquiries.map((inq) => (
              <InquiryCard key={inq.id} inq={inq} projects={projects} onChange={load} />
            ))}
          </div>
        </>
      )}
    </>
  );
}
