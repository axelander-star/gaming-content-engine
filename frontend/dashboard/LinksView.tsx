"use client";

// Ausbau A8: one public link page per channel ("Link in Bio"), affiliate links with
// the label "Anzeige", newsletter sign-ups (double opt-in) and the mail outbox.

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS, formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  AffiliateLink,
  BioPage,
  ContentProject,
  NewsletterOverview,
  Outbox,
  PlatformCode,
} from "@/lib/types";

const STATUS_LABEL = { pending: "unbestätigt", confirmed: "bestätigt", unsubscribed: "abgemeldet" };
const MAIL_LABEL = { mock: "nur Postausgang", sent: "gesendet", failed: "fehlgeschlagen" };

function PageEditor({
  page,
  canEdit,
  onSaved,
}: {
  page: BioPage;
  canEdit: boolean;
  onSaved: (p: BioPage) => void;
}) {
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState(page.slug);
  const [headline, setHeadline] = useState(page.headline);
  const [intro, setIntro] = useState(page.intro ?? "");
  const [links, setLinks] = useState(page.links.map((l) => `${l.title} | ${l.url}`).join("\n"));
  const [error, setError] = useState<string | null>(null);

  async function patch(data: Parameters<typeof api.updateBioPage>[1]) {
    setError(null);
    try {
      onSaved(await api.updateBioPage(page.id, data));
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    }
  }

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const parsed = links
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [title, ...rest] = line.split("|");
        return { title: (title ?? "").trim(), url: rest.join("|").trim() };
      });
    if (await patch({ slug, headline, intro: intro.trim() || null, links: parsed })) setOpen(false);
  }

  const platform = PLATFORM_LABELS[page.platform as PlatformCode] ?? page.platform;
  return (
    <li>
      <div className="feed-body">
        <div className="feed-title">
          {page.headline} <span className="chip">{page.project}</span>{" "}
          {page.enabled ? <Badge tone="ok">online</Badge> : <Badge>aus</Badge>}
        </div>
        <div className="muted small">
          {platform} · {page.language.toUpperCase()} · /l/{page.slug} · {page.views} Aufrufe ·{" "}
          {page.subscribers} Newsletter
          {page.public_url ? (
            <>
              {" · "}
              <a href={page.public_url} target="_blank" rel="noreferrer">
                {page.public_url}
              </a>
            </>
          ) : null}
        </div>
        <ErrorText error={error} />
        {open && (
          <form className="focus-form" onSubmit={save} aria-label={`Linkseite ${page.channel}`}>
            <label>
              Adresse
              <input value={slug} onChange={(e) => setSlug(e.target.value)} maxLength={60} />
            </label>
            <label>
              Überschrift
              <input value={headline} onChange={(e) => setHeadline(e.target.value)} maxLength={120} />
            </label>
            <label>
              Kurzer Text
              <textarea rows={2} value={intro} onChange={(e) => setIntro(e.target.value)} maxLength={600} />
            </label>
            <label>
              Eigene Links (je Zeile: Titel | https://…)
              <textarea rows={3} value={links} onChange={(e) => setLinks(e.target.value)} />
            </label>
            <button type="submit" className="btn btn-primary">
              Speichern
            </button>
          </form>
        )}
      </div>
      <div className="row-actions">
        <a className="btn btn-ghost btn-small" href={page.preview_path} target="_blank" rel="noreferrer">
          Vorschau
        </a>
        {canEdit && (
          <>
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setOpen(!open)}>
              Bearbeiten
            </button>
            <label className="check-label small">
              <input
                type="checkbox"
                checked={page.newsletter_enabled}
                onChange={(e) => void patch({ newsletter_enabled: e.target.checked })}
              />
              Newsletter
            </label>
            <button
              type="button"
              className={page.enabled ? "btn btn-ghost btn-small" : "btn btn-small"}
              aria-label={`Linkseite ${page.channel} ${page.enabled ? "ausschalten" : "einschalten"}`}
              onClick={() => void patch({ enabled: !page.enabled })}
            >
              {page.enabled ? "Ausschalten" : "Einschalten"}
            </button>
          </>
        )}
      </div>
    </li>
  );
}

export function LinksView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "operator");
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [filter, setFilter] = useState<number | undefined>(undefined);
  const [pages, setPages] = useState<BioPage[]>([]);
  const [links, setLinks] = useState<AffiliateLink[]>([]);
  const [news, setNews] = useState<NewsletterOverview | null>(null);
  const [outbox, setOutbox] = useState<Outbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  // new affiliate link
  const [projectId, setProjectId] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [program, setProgram] = useState("");
  const [language, setLanguage] = useState("");
  const [keywords, setKeywords] = useState("");
  const [inPosts, setInPosts] = useState(false);

  const load = useCallback(() => {
    const fail = (e: Error) => setError(e.message);
    api.bioPages(filter).then(setPages).catch(fail);
    api.affiliateLinks(filter).then(setLinks).catch(fail);
    if (canEdit) {
      api.newsletter(filter).then(setNews).catch(fail);
      api.outbox().then(setOutbox).catch(fail);
    }
  }, [filter, canEdit]);

  useEffect(() => {
    api
      .projects()
      .then((all) => setProjects(all.filter((p) => p.status !== "archived")))
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function addLink(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (projectId === "") return;
    await run(async () => {
      await api.createAffiliateLink({
        project_id: projectId,
        title,
        url,
        program: program.trim() || null,
        language: language || null,
        keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean),
        in_posts: inPosts,
      });
      setTitle("");
      setUrl("");
      setKeywords("");
    });
  }

  return (
    <>
      <PageHeader
        title="Linkseiten und Newsletter"
        description="Jeder Kanal bekommt eine eigene Seite für den Link in der Bio: andere Profile, neueste Videos, deine Links und die Newsletter-Anmeldung. Affiliate-Links stehen dort immer mit „Anzeige“."
      />
      <ErrorText error={error} />
      <div className="toolbar">
        <label className="inline-label">
          Themenbereich
          <select
            value={filter ?? ""}
            onChange={(e) => setFilter(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">Alle</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Section title={`Linkseiten (${pages.filter((p) => p.enabled).length} von ${pages.length} online)`}>
        {pages.length > 0 && !pages[0]?.public_url && (
          <p className="small">
            <Badge tone="info">Noch nicht öffentlich</Badge> Für die echte Adresse im Server-.env{" "}
            <code>PUBLIC_LINKS_BASE_URL</code> setzen und im Tunnel einen Hostnamen (z. B.
            links.kanalfabrik.de → caddy:8082) ohne Access-Schutz anlegen. Die Vorschau klappt
            schon jetzt.
          </p>
        )}
        <ul className="feed" aria-label="Linkseiten">
          {pages.map((p) => (
            <PageEditor
              key={p.id}
              page={p}
              canEdit={canEdit}
              onSaved={(n) => setPages((all) => all.map((x) => (x.id === n.id ? n : x)))}
            />
          ))}
        </ul>
      </Section>

      <Section title="Affiliate-Links">
        <p className="muted small">
          Auf jeder Linkseite mit „Anzeige“ gekennzeichnet. Nur wenn „In Beiträgen erwähnen“ an
          ist, beginnt ein passender Beitrag (Stichwort im Titel) mit „Anzeige: … Link in meiner
          Bio“. Dann in der App zusätzlich die Werbekennzeichnung der Plattform einschalten.
        </p>
        {links.length === 0 ? (
          <p className="muted small">Noch keine Affiliate-Links.</p>
        ) : (
          <ul className="feed" aria-label="Affiliate-Links">
            {links.map((l) => (
              <li key={l.id}>
                <div className="feed-body">
                  <div className="feed-title">
                    {l.title} <span className="chip">{l.project}</span>{" "}
                    {l.active ? <Badge tone="ok">aktiv</Badge> : <Badge>pausiert</Badge>}{" "}
                    {l.in_posts && <Badge tone="warn">in Beiträgen</Badge>}
                  </div>
                  <div className="muted small">
                    {l.program ?? "Partnerprogramm"} · {l.language ? l.language.toUpperCase() : "alle Sprachen"} ·{" "}
                    {l.clicks} Klicks
                    {l.keywords.length ? ` · Stichwörter: ${l.keywords.join(", ")}` : ""}
                  </div>
                </div>
                {canEdit && (
                  <div className="row-actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-small"
                      onClick={() => void run(() => api.updateAffiliateLink(l.id, { active: !l.active }))}
                    >
                      {l.active ? "Pausieren" : "Aktivieren"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-small"
                      aria-label={`${l.title} löschen`}
                      onClick={() => void run(() => api.deleteAffiliateLink(l.id))}
                    >
                      Löschen
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
        {canEdit && (
          <form className="focus-form" aria-label="Affiliate-Link anlegen" onSubmit={addLink}>
            <label>
              Themenbereich
              <select
                value={projectId}
                onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : "")}
                required
              >
                <option value="">Bitte wählen</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Titel
              <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} required />
            </label>
            <label>
              Link
              <input
                type="url"
                value={url}
                placeholder="https://…"
                onChange={(e) => setUrl(e.target.value)}
                required
              />
            </label>
            <label>
              Partnerprogramm
              <input value={program} onChange={(e) => setProgram(e.target.value)} maxLength={80} />
            </label>
            <label>
              Sprache
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                <option value="">alle</option>
                <option value="de">Deutsch</option>
                <option value="en">Englisch</option>
              </select>
            </label>
            <label>
              Stichwörter (mit Komma)
              <input value={keywords} onChange={(e) => setKeywords(e.target.value)} />
            </label>
            <label className="check-label">
              <input type="checkbox" checked={inPosts} onChange={(e) => setInPosts(e.target.checked)} />
              In Beiträgen erwähnen
            </label>
            <button type="submit" className="btn btn-ghost">
              Hinzufügen
            </button>
          </form>
        )}
      </Section>

      {canEdit && news && (
        <Section title={`Newsletter (${news.confirmed} bestätigt)`}>
          <p className="muted small">
            Double-Opt-in: Erst der Klick auf den Knopf in der Bestätigungsmail trägt jemanden ein.
            Unbestätigte Adressen werden nach 7 Tagen gelöscht. {news.pending} unbestätigt,{" "}
            {news.unsubscribed} abgemeldet.
          </p>
          {news.subscribers.length > 0 && (
            <ul className="feed" aria-label="Newsletter-Adressen">
              {news.subscribers.map((s) => (
                <li key={s.id}>
                  <div className="feed-body">
                    <div className="feed-title">{s.email}</div>
                    <div className="muted small">
                      {STATUS_LABEL[s.status]} · {s.language.toUpperCase()} ·{" "}
                      {formatDateTime(s.confirmed_at ?? s.created_at)}
                    </div>
                  </div>
                  <div className="row-actions">
                    <button
                      type="button"
                      className="btn btn-ghost btn-small"
                      aria-label={`${s.email} löschen`}
                      onClick={() => void run(() => api.deleteSubscriber(s.id))}
                    >
                      Löschen
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {canEdit && outbox && (
        <Section title="Postausgang">
          {outbox.problem && (
            <p className="small">
              <Badge tone="info">Testmodus</Badge> {outbox.problem}
            </p>
          )}
          {outbox.mails.length === 0 ? (
            <p className="muted small">Noch keine Mails.</p>
          ) : (
            <ul className="feed" aria-label="Postausgang">
              {outbox.mails.map((m) => (
                <li key={m.id}>
                  <details className="feed-body">
                    <summary className="feed-title">
                      {m.subject} <Badge tone={m.status === "failed" ? "danger" : "neutral"}>{MAIL_LABEL[m.status]}</Badge>
                    </summary>
                    <div className="muted small">
                      an {m.to_address} · {formatDateTime(m.created_at)}
                      {m.error ? ` · ${m.error}` : ""}
                    </div>
                    <pre className="mail-body">{m.body_text}</pre>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </>
  );
}
