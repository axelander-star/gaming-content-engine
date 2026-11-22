"use client";

// Clipping campaigns (Content Rewards): links to submit within the deadline,
// campaign clips to approve, campaigns with their rules and material upload.

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS, formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import { resumableUpload } from "@/lib/upload";
import type { UploadProgress } from "@/lib/upload";
import type {
  CampaignFit,
  Campaign,
  CampaignClip,
  CampaignInput,
  CampaignProposal,
  CampaignStatus,
  CampaignSubmission,
  Channel,
  ContentProject,
  Game,
  Language,
  PlatformCode,
} from "@/lib/types";

const PLATFORMS: PlatformCode[] = ["youtube", "tiktok", "instagram", "facebook"];
const LANGUAGES: Language[] = ["de", "en"];
const STATUS_LABELS: Record<CampaignStatus, [string, "ok" | "warn" | "neutral"]> = {
  active: ["Aktiv", "ok"],
  paused: ["Pausiert", "warn"],
  ended: ["Beendet", "neutral"],
};
const CLIP_STATUS: Record<string, [string, "ok" | "warn" | "neutral"]> = {
  QUALITY_APPROVED: ["Wartet auf Freigabe", "warn"],
  READY_TO_PUBLISH: ["Freigegeben", "ok"],
  SCHEDULED: ["Eingeplant", "ok"],
};

/** Seconds until `deadline` (negative when over). */
function secondsLeft(deadline: string | null, now: number): number | null {
  return deadline ? Math.floor((new Date(deadline).getTime() - now) / 1000) : null;
}

function countdown(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function money(value: number | null): string {
  return value === null ? "–" : `${value.toLocaleString("de-DE", { maximumFractionDigits: 2 })} $`;
}

// --- submissions ----------------------------------------------------------------

function SubmissionCard({
  sub,
  now,
  canEdit,
  onChanged,
}: {
  sub: CampaignSubmission;
  now: number;
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const left = secondsLeft(sub.deadline_at, now);
  const overdue = left !== null && left <= 0;
  const urgent = left !== null && left > 0 && left < 5 * 60;

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
    if (!sub.post_url) return;
    try {
      await navigator.clipboard.writeText(sub.post_url);
    } catch {
      // Clipboard blocked (http, permissions): select the text so Ctrl+C works.
      const field = document.getElementById(`sub-link-${sub.id}`) as HTMLInputElement | null;
      field?.select();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  function saveLink(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void run(() => api.setSubmissionLink(sub.id, link.trim()));
  }

  return (
    <article
      className={`card sub-card ${overdue ? "is-overdue" : urgent ? "is-urgent" : ""}`}
      aria-label={`Einreichung ${sub.title || sub.campaign}`}
    >
      <div className="sub-head">
        <div className="idea-meta">
          <span className={`chip chip-${sub.platform}`}>{PLATFORM_LABELS[sub.platform]}</span>
          <span className="chip">{sub.channel}</span>
          <span className="chip">{sub.campaign}</span>
          {sub.is_mock && <Badge tone="info">Test (Mock)</Badge>}
        </div>
        {left !== null ? (
          <div className="sub-timer" role="timer" aria-live="off">
            {overdue ? (
              <Badge tone="danger">Frist abgelaufen</Badge>
            ) : (
              <>
                <span className="sub-time">{countdown(left)}</span>
                <span className="muted small">bis {formatDateTime(sub.deadline_at)}</span>
              </>
            )}
          </div>
        ) : (
          <Badge tone="warn">Link fehlt</Badge>
        )}
      </div>
      {sub.title && <p className="appr-title">{sub.title}</p>}
      {sub.post_url ? (
        <div className="sub-link">
          <input
            id={`sub-link-${sub.id}`}
            readOnly
            value={sub.post_url}
            aria-label="Link zum Beitrag"
            onFocus={(e) => e.currentTarget.select()}
          />
          <button type="button" className="btn btn-primary btn-small" onClick={copy}>
            {copied ? "Kopiert ✓" : "Link kopieren"}
          </button>
        </div>
      ) : (
        canEdit && (
          <form className="sub-link" onSubmit={saveLink}>
            <input
              type="url"
              required
              placeholder="https://… (Link, sobald der Beitrag öffentlich ist)"
              value={link}
              onChange={(e) => setLink(e.target.value)}
              aria-label="Link zum Beitrag eintragen"
            />
            <button type="submit" className="btn btn-small" disabled={busy}>
              Link speichern
            </button>
          </form>
        )
      )}
      <div className="row-actions">
        <a
          className="btn btn-ghost btn-small"
          href={sub.campaign_url}
          target="_blank"
          rel="noreferrer"
        >
          Kampagnenseite öffnen ↗
        </a>
        {canEdit && (
          <>
            <button
              type="button"
              className="btn btn-primary btn-small"
              disabled={busy || !sub.post_url}
              onClick={() => run(() => api.markSubmitted(sub.id))}
            >
              Eingereicht ✓
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-small"
              disabled={busy}
              onClick={() => run(() => api.skipSubmission(sub.id))}
            >
              Nicht einreichen
            </button>
          </>
        )}
      </div>
      {overdue && (
        <p className="small muted">
          Die Kampagne zählt Links meist nur innerhalb der Frist. Trotzdem einreichen oder „Nicht
          einreichen“ wählen.
        </p>
      )}
      <ErrorText error={error} />
    </article>
  );
}

function DoneList({
  subs,
  canEdit,
  onChanged,
}: {
  subs: CampaignSubmission[];
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  if (subs.length === 0) return <p className="muted">Noch nichts erledigt.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Clip</th>
            <th>Kampagne</th>
            <th>Status</th>
            <th>Erledigt</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {subs.map((s) => (
            <tr key={s.id}>
              <td>
                {s.post_url ? (
                  <a href={s.post_url} target="_blank" rel="noreferrer">
                    {s.title || s.channel}
                  </a>
                ) : (
                  s.title || s.channel
                )}
                <div className="muted small">{s.channel}</div>
              </td>
              <td>{s.campaign}</td>
              <td>
                {s.state === "submitted" ? (
                  <Badge tone="ok">{s.late ? "Eingereicht (verspätet)" : "Eingereicht"}</Badge>
                ) : (
                  <Badge tone="neutral">Nicht eingereicht</Badge>
                )}
              </td>
              <td>{formatDateTime(s.submitted_at)}</td>
              <td>
                {canEdit && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    onClick={async () => {
                      await api.reopenSubmission(s.id);
                      await onChanged();
                    }}
                  >
                    Rückgängig
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- clips --------------------------------------------------------------------

function ClipCard({
  clip,
  canEdit,
  onChanged,
}: {
  clip: CampaignClip;
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  const [description, setDescription] = useState(clip.description);
  const [hashtags, setHashtags] = useState(clip.hashtags.join(" "));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editable = canEdit && clip.status === "QUALITY_APPROVED";
  const dirty = description !== clip.description || hashtags !== clip.hashtags.join(" ");
  const [label, tone] = CLIP_STATUS[clip.status] ?? [clip.status, "neutral"];

  useEffect(() => {
    setDescription(clip.description);
    setHashtags(clip.hashtags.join(" "));
  }, [clip.description, clip.hashtags]);

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

  return (
    <article className="card appr-card" aria-label={`Kampagnen-Clip ${clip.id}`}>
      <div className="appr-media">
        <video controls preload="metadata" src={api.variantFileUrl(clip.id)} />
      </div>
      <div className="appr-body">
        <div className="idea-meta">
          <span className={`chip chip-${clip.platform}`}>{PLATFORM_LABELS[clip.platform]}</span>
          <span className="chip">{clip.channel}</span>
          <span className="chip">{clip.campaign}</span>
          <Badge tone={tone}>{label}</Badge>
        </div>
        <p className="appr-title">{clip.title}</p>
        {editable ? (
          <form
            className="appr-form"
            onSubmit={(e) => {
              e.preventDefault();
              void run(() =>
                api.updateCampaignClip(clip.id, {
                  description,
                  hashtags: hashtags.split(/[\s,]+/).filter(Boolean),
                }),
              );
            }}
          >
            <label>
              Beschreibung (Werbehinweis bleibt am Anfang)
              <textarea
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label>
              Hashtags
              <input value={hashtags} onChange={(e) => setHashtags(e.target.value)} />
            </label>
            {dirty && (
              <button className="btn btn-small" type="submit" disabled={busy}>
                Texte speichern
              </button>
            )}
          </form>
        ) : (
          <pre className="appr-preview-text">{clip.caption}</pre>
        )}
        <details className="appr-details">
          <summary>
            Prüfung: {clip.checks.filter((c) => c.passed).length}/{clip.checks.length} in Ordnung
            {clip.duration_s ? ` · ${clip.duration_s.toFixed(0)} s` : ""}
          </summary>
          <ul className="appr-checks">
            {clip.checks.map((c) => (
              <li key={c.name} className={c.passed ? "ok" : "bad"}>
                {c.passed ? "✓" : "✗"} {c.detail}
              </li>
            ))}
          </ul>
        </details>
        {clip.problems.length > 0 && (
          <ul className="appr-problems" aria-label="Offene Punkte">
            {clip.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        {clip.scheduled_for && (
          <p className="small">Eingeplant für {formatDateTime(clip.scheduled_for)}</p>
        )}
        {canEdit && (
          <div className="row-actions">
            {clip.status === "QUALITY_APPROVED" ? (
              <>
                <button
                  type="button"
                  className="btn btn-primary btn-small"
                  disabled={busy || dirty}
                  onClick={() => run(() => api.approveCampaignClip(clip.id))}
                >
                  Freigeben
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  disabled={busy}
                  onClick={() => run(() => api.discardCampaignClip(clip.id))}
                >
                  Verwerfen
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                disabled={busy}
                onClick={() => run(() => api.withdrawCampaignClip(clip.id))}
              >
                Freigabe zurückziehen
              </button>
            )}
          </div>
        )}
        <ErrorText error={error} />
      </div>
    </article>
  );
}

// --- campaigns ------------------------------------------------------------------

function MaterialUpload({ campaign, onDone }: { campaign: Campaign; onDone: () => Promise<void> }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const done = await resumableUpload(file, {
        purpose: "material",
        params: {
          source_id: campaign.source_id,
          license_id: campaign.license_id,
          game_id: campaign.game_id,
          content_project_id: campaign.content_project_id,
          title: `${campaign.name}: ${file.name}`.slice(0, 300),
        },
        onProgress: setProgress,
      });
      setMessage(
        `Material #${String(done.result?.material_id ?? "?")} hochgeladen. Schnitt, Prüfung ` +
          "und Texte laufen automatisch; danach erscheinen die Clips oben zur Freigabe.",
      );
      if (fileRef.current) fileRef.current.value = "";
      await onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  const percent =
    progress && progress.total > 0 ? Math.floor((progress.sent / progress.total) * 100) : 0;
  return (
    <form className="inline-form" onSubmit={submit} aria-label={`Material für ${campaign.name}`}>
      <input
        ref={fileRef}
        type="file"
        accept="video/mp4,video/quicktime,video/x-matroska"
        required
      />
      <button className="btn btn-small" type="submit" disabled={busy}>
        {busy ? `Lädt … ${percent} %` : "Material hochladen"}
      </button>
      {message && <p className="small">{message}</p>}
      <ErrorText error={error} />
    </form>
  );
}

function ProposalList({ campaign, canEdit, onChanged }: {
  campaign: Campaign;
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<number | null>(null);

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      await api.refreshCampaignProposals(campaign.id);
      await onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function copy(p: CampaignProposal, i: number) {
    try {
      await navigator.clipboard.writeText(p.caption);
      setCopied(i);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      setError("Kopieren nicht möglich – Text bitte markieren und kopieren.");
    }
  }

  return (
    <details className="camp-proposals">
      <summary>
        Videovorschläge ({campaign.proposals.length})
        {campaign.proposals_at && (
          <span className="muted small">
            {" "}
            · Stand {formatDateTime(campaign.proposals_at)}
            {campaign.proposals_source === "template" ? " · Vorlage" : ""}
          </span>
        )}
      </summary>
      {campaign.proposals.length === 0 && (
        <p className="muted small">Noch keine Vorschläge.</p>
      )}
      <ol className="camp-proposal-list">
        {campaign.proposals.map((p, i) => (
          <li key={`${p.title}-${i}`} className="camp-proposal">
            <div className="feed-title">
              {p.title} <Badge tone="info">{p.length_s} s</Badge>
            </div>
            <p className="small">
              <strong>Einstieg:</strong> {p.hook}
            </p>
            {p.scenes.length > 0 && (
              <ul className="small">
                {p.scenes.map((sc) => (
                  <li key={sc}>{sc}</li>
                ))}
              </ul>
            )}
            {p.on_screen_text.length > 0 && (
              <p className="small">
                <strong>Text im Bild:</strong> {p.on_screen_text.join(" · ")}
              </p>
            )}
            <pre className="camp-caption">{p.caption}</pre>
            {p.why && <p className="muted small">{p.why}</p>}
            {p.facts.length > 0 && (
              <p className="muted small">Fakten: {p.facts.join(" · ")}</p>
            )}
            <button type="button" className="btn btn-ghost btn-small" onClick={() => void copy(p, i)}>
              {copied === i ? "Kopiert ✓" : "Beschreibung kopieren"}
            </button>
          </li>
        ))}
      </ol>
      {canEdit && (
        <button type="button" className="btn btn-small" onClick={() => void refresh()} disabled={busy}>
          {busy ? "Schreibt …" : "Neue Vorschläge schreiben"}
        </button>
      )}
      <ErrorText error={error} />
    </details>
  );
}

function CampaignCard({
  campaign,
  canEdit,
  onChanged,
}: {
  campaign: Campaign;
  canEdit: boolean;
  onChanged: () => Promise<void>;
}) {
  const [label, tone] = STATUS_LABELS[campaign.status];
  const [error, setError] = useState<string | null>(null);

  async function setStatus(status: CampaignStatus) {
    setError(null);
    try {
      await api.setCampaignStatus(campaign.id, status);
      await onChanged();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <article className="card camp-card" aria-label={`Kampagne ${campaign.name}`}>
      <div className="sub-head">
        <h3>
          <a href={campaign.url} target="_blank" rel="noreferrer">
            {campaign.name} ↗
          </a>
        </h3>
        <Badge tone={tone}>{label}</Badge>
      </div>
      <p className="camp-next" aria-label="Nächster Schritt">
        <strong>Nächster Schritt:</strong> {campaign.next_step}
      </p>
      <dl className="camp-facts">
        <div>
          <dt>Vergütung</dt>
          <dd>{campaign.cpm_usd !== null ? `${money(campaign.cpm_usd)} / 1.000 Aufrufe` : "–"}</dd>
        </div>
        <div>
          <dt>Budget</dt>
          <dd>{money(campaign.budget_usd)}</dd>
        </div>
        <div>
          <dt>Kanäle</dt>
          <dd>{campaign.channels.join(", ")}</dd>
        </div>
        <div>
          <dt>Länge</dt>
          <dd>
            {campaign.min_duration_s ?? 0}–{campaign.max_duration_s ?? "∞"} s
          </dd>
        </div>
        <div>
          <dt>Pflicht im Text</dt>
          <dd>
            {[
              campaign.disclosure,
              campaign.required_text,
              ...campaign.required_hashtags.map((t) => `#${t}`),
            ]
              .filter(Boolean)
              .join(" ") || "–"}
          </dd>
        </div>
        <div>
          <dt>Einreichen binnen</dt>
          <dd>{campaign.submission_window_min} Min.</dd>
        </div>
        <div>
          <dt>Stand</dt>
          <dd>
            {campaign.materials} Material · {campaign.clips_waiting} zur Freigabe ·{" "}
            {campaign.submissions_open} offen · {campaign.submissions_done} eingereicht
          </dd>
        </div>
        {campaign.ends_on && (
          <div>
            <dt>Endet</dt>
            <dd>{new Date(campaign.ends_on).toLocaleDateString("de-DE")}</dd>
          </div>
        )}
      </dl>
      {campaign.material_links.length > 0 && (
        <p className="small">
          Material laut Kampagne:{" "}
          {campaign.material_links.map((l, i) => (
            <a key={l} href={l} target="_blank" rel="noreferrer">
              Link {i + 1}{" "}
            </a>
          ))}
        </p>
      )}
      {canEdit && campaign.status === "active" && (
        <MaterialUpload campaign={campaign} onDone={onChanged} />
      )}
      <ProposalList campaign={campaign} canEdit={canEdit} onChanged={onChanged} />
      {canEdit && (
        <div className="row-actions">
          {campaign.status !== "active" && (
            <button type="button" className="btn btn-small" onClick={() => setStatus("active")}>
              Aktivieren
            </button>
          )}
          {campaign.status === "active" && (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => setStatus("paused")}
            >
              Pausieren
            </button>
          )}
          {campaign.status !== "ended" && (
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => setStatus("ended")}
            >
              Beenden (Budget leer)
            </button>
          )}
        </div>
      )}
      <ErrorText error={error} />
    </article>
  );
}

function NewCampaignForm({
  projects,
  channels,
  games,
  onCreated,
}: {
  projects: ContentProject[];
  channels: Channel[];
  games: Game[];
  onCreated: () => Promise<void>;
}) {
  const [projectId, setProjectId] = useState<number | null>(projects[0]?.id ?? null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [cpm, setCpm] = useState("");
  const [budget, setBudget] = useState("");
  const [platforms, setPlatforms] = useState<PlatformCode[]>(["youtube", "tiktok"]);
  const [languages, setLanguages] = useState<Language[]>(["en"]);
  const [channelIds, setChannelIds] = useState<number[]>([]);
  const [gameId, setGameId] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [disclosure, setDisclosure] = useState("#ad");
  const [requiredText, setRequiredText] = useState("");
  const [minS, setMinS] = useState("");
  const [maxS, setMaxS] = useState("60");
  const [windowMin, setWindowMin] = useState("30");
  const [endsOn, setEndsOn] = useState("");
  const [links, setLinks] = useState("");
  const [brief, setBrief] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fits, setFits] = useState<CampaignFit[] | null>(null);
  const [pasted, setPasted] = useState("");
  const [reading, setReading] = useState(false);
  const [readNote, setReadNote] = useState<string | null>(null);

  async function readPage() {
    setReading(true);
    setError(null);
    setReadNote(null);
    try {
      const r = await api.parseCampaignPage(pasted);
      const f = r.fields;
      if (f.name) setName(f.name);
      if (f.url) setUrl(f.url);
      if (f.cpm_usd !== null) setCpm(String(f.cpm_usd));
      if (f.budget_usd !== null) setBudget(String(f.budget_usd));
      const plats = f.platforms.filter((p): p is PlatformCode =>
        (PLATFORMS as string[]).includes(p),
      );
      if (plats.length) setPlatforms(plats);
      const langs = f.languages.filter((l): l is Language => (LANGUAGES as string[]).includes(l));
      if (langs.length) setLanguages(langs);
      if (f.game_id !== null) setGameId(String(f.game_id));
      if (f.required_hashtags.length) setHashtags(f.required_hashtags.join(" "));
      if (f.disclosure) setDisclosure(f.disclosure);
      if (f.required_text) setRequiredText(f.required_text);
      if (f.min_duration_s !== null) setMinS(String(f.min_duration_s));
      if (f.max_duration_s !== null) setMaxS(String(f.max_duration_s));
      if (f.ends_on) setEndsOn(f.ends_on);
      if (f.material_links.length) setLinks(f.material_links.join("\n"));
      if (f.brief) setBrief(f.brief);
      setReadNote(
        `${r.found.length} Angaben übernommen${r.game ? ` (Spiel: ${r.game})` : ""}.` +
          (r.missing.length
            ? ` Nicht gefunden, bitte selbst prüfen: ${r.missing.join(", ")}.`
            : " Bitte alles kurz prüfen."),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setReading(false);
    }
  }

  async function suggest() {
    setError(null);
    try {
      const game = games.find((g) => String(g.id) === gameId);
      setFits(
        await api.matchCampaign({
          name,
          brief: brief.trim() || null,
          game: game?.name ?? null,
          platforms,
          languages,
          cpm_usd: num(cpm),
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    if (projectId === null && projects[0]) setProjectId(projects[0].id);
  }, [projects, projectId]);

  const usable = channels.filter(
    (c) =>
      c.content_project_id === projectId &&
      platforms.includes(c.platform) &&
      languages.includes(c.language),
  );

  function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  const num = (v: string): number | null => (v.trim() === "" ? null : Number(v.replace(",", ".")));

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (projectId === null) return;
    const data: CampaignInput = {
      content_project_id: projectId,
      name,
      url,
      cpm_usd: num(cpm),
      budget_usd: num(budget),
      platforms,
      languages,
      channel_ids: channelIds.filter((id) => usable.some((c) => c.id === id)),
      game_id: gameId ? Number(gameId) : null,
      required_hashtags: hashtags.split(/[\s,]+/).filter(Boolean),
      disclosure: disclosure.trim() || null,
      required_text: requiredText.trim() || null,
      min_duration_s: num(minS),
      max_duration_s: num(maxS),
      submission_window_min: Number(windowMin) || 30,
      ends_on: endsOn || null,
      brief: brief.trim() || null,
      material_links: links.split(/\s+/).filter(Boolean),
      rights_confirmed: confirmed,
    };
    setBusy(true);
    setError(null);
    try {
      await api.createCampaign(data);
      setName("");
      setUrl("");
      setBrief("");
      setLinks("");
      setConfirmed(false);
      await onCreated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="camp-form" onSubmit={submit} aria-label="Neue Kampagne">
      <div className="camp-paste">
        <label>
          Text der Kampagnenseite einfügen (auf Content Rewards alles markieren, kopieren,
          hier einfügen)
          <textarea
            rows={5}
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            maxLength={20000}
            placeholder="Name, Vergütung, Plattformen, Regeln, Hashtags …"
          />
        </label>
        <button
          type="button"
          className="btn"
          onClick={() => void readPage()}
          disabled={reading || pasted.trim().length < 20}
        >
          {reading ? "Liest …" : "Formular automatisch ausfüllen"}
        </button>
        {readNote && <p className="small" role="status">{readNote}</p>}
      </div>
      <div className="form-grid">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
        </label>
        <label>
          Kampagnenseite (Content Rewards)
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://contentrewards.com/…"
            required
          />
        </label>
        <label>
          Themenbereich
          <select value={projectId ?? ""} onChange={(e) => setProjectId(Number(e.target.value))}>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Spiel (für die Publisher-Prüfung)
          <select value={gameId} onChange={(e) => setGameId(e.target.value)}>
            <option value="">– beim Hochladen wählen –</option>
            {games.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          $ pro 1.000 Aufrufe
          <input inputMode="decimal" value={cpm} onChange={(e) => setCpm(e.target.value)} />
        </label>
        <label>
          Budget ($)
          <input inputMode="decimal" value={budget} onChange={(e) => setBudget(e.target.value)} />
        </label>
        <label>
          Mindestlänge (s)
          <input inputMode="numeric" value={minS} onChange={(e) => setMinS(e.target.value)} />
        </label>
        <label>
          Höchstlänge (s)
          <input inputMode="numeric" value={maxS} onChange={(e) => setMaxS(e.target.value)} />
        </label>
        <label>
          Werbehinweis (steht am Anfang)
          <input
            value={disclosure}
            onChange={(e) => setDisclosure(e.target.value)}
            maxLength={300}
          />
        </label>
        <label>
          Pflicht-Hashtags
          <input
            value={hashtags}
            onChange={(e) => setHashtags(e.target.value)}
            placeholder="#Streamer #Clip"
          />
        </label>
        <label>
          Pflichttext (Credit, @Erwähnung)
          <input
            value={requiredText}
            onChange={(e) => setRequiredText(e.target.value)}
            maxLength={500}
          />
        </label>
        <label>
          Einreichen binnen (Minuten)
          <input
            inputMode="numeric"
            value={windowMin}
            onChange={(e) => setWindowMin(e.target.value)}
          />
        </label>
        <label>
          Endet am
          <input type="date" value={endsOn} onChange={(e) => setEndsOn(e.target.value)} />
        </label>
      </div>
      <fieldset className="appr-channels">
        <legend>Plattformen, die zählen</legend>
        <div className="chip-row">
          {PLATFORMS.map((p) => (
            <label key={p} className="check-label">
              <input
                type="checkbox"
                checked={platforms.includes(p)}
                onChange={() => setPlatforms(toggle(platforms, p))}
              />
              {PLATFORM_LABELS[p]}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="appr-channels">
        <legend>Sprachen der Clips</legend>
        <div className="chip-row">
          {LANGUAGES.map((l) => (
            <label key={l} className="check-label">
              <input
                type="checkbox"
                checked={languages.includes(l)}
                onChange={() => setLanguages(toggle(languages, l))}
              />
              {l === "de" ? "Deutsch" : "Englisch"}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="appr-channels">
        <legend>Kanäle, die du bei Content Rewards verbunden hast</legend>
        {usable.length === 0 ? (
          <p className="muted small">Kein Kanal passt zu Plattformen und Sprachen.</p>
        ) : (
          usable.map((c) => (
            <label key={c.id} className="check-label">
              <input
                type="checkbox"
                checked={channelIds.includes(c.id)}
                onChange={() => setChannelIds(toggle(channelIds, c.id))}
              />
              {c.name} ({PLATFORM_LABELS[c.platform]}, {c.language.toUpperCase()})
            </label>
          ))
        )}
      </fieldset>
      <label>
        Materiallinks (Streams, Ordner; einer pro Zeile)
        <textarea rows={2} value={links} onChange={(e) => setLinks(e.target.value)} />
      </label>
      <label>
        Kampagnenregeln (aus der Beschreibung kopieren)
        <textarea
          rows={4}
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          maxLength={10000}
        />
      </label>
      <div className="camp-fit">
        <button type="button" className="btn btn-ghost" onClick={() => void suggest()}>
          Passenden Themenbereich vorschlagen
        </button>
        {fits && (
          <ul className="feed" aria-label="Passende Themenbereiche">
            {fits.map((f) => (
              <li key={f.project_id}>
                <div className="feed-body">
                  <div className="feed-title">
                    {f.project}{" "}
                    <Badge tone={f.score >= 70 ? "ok" : f.score >= 40 ? "info" : "neutral"}>
                      {f.score} / 100
                    </Badge>
                  </div>
                  <div className="muted small">
                    {f.reasons.join(" · ")}
                    {f.usd_per_clip !== null
                      ? ` · etwa ${money(f.usd_per_clip)} je Clip (Median ${(
                          f.median_views ?? 0
                        ).toLocaleString("de-DE")} Aufrufe)`
                      : " · noch keine Aufrufzahlen für eine Schätzung"}
                  </div>
                </div>
                <div className="row-actions">
                  {f.project_id === projectId ? (
                    <Badge tone="ok">gewählt</Badge>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-ghost btn-small"
                      onClick={() => setProjectId(f.project_id)}
                    >
                      Übernehmen
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <label className="check-label">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        Ich habe die Kampagnenregeln gelesen: Das Material darf geschnitten und als bezahlter
        Kurzclip auf den gewählten Kanälen veröffentlicht werden (mit Musik und Ton).
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={busy || !confirmed}>
          Kampagne anlegen
        </button>
      </div>
      <ErrorText error={error} />
    </form>
  );
}

// --- page -----------------------------------------------------------------------

export function CampaignsView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "operator");
  const [open, setOpen] = useState<CampaignSubmission[]>([]);
  const [done, setDone] = useState<CampaignSubmission[]>([]);
  const [clips, setClips] = useState<CampaignClip[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [games, setGames] = useState<Game[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, d, c, k] = await Promise.all([
        api.submissions(false),
        api.submissions(true),
        api.campaignClips(),
        api.campaigns(),
      ]);
      setOpen(o);
      setDone(d);
      setClips(c);
      setCampaigns(k);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
    void Promise.all([api.projects(), api.channels(), api.games()])
      .then(([p, ch, g]) => {
        setProjects(p);
        setChannels(ch);
        setGames(g);
      })
      .catch((err: Error) => setError(err.message));
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    const refresh = window.setInterval(() => void load(), 30_000);
    return () => {
      window.clearInterval(tick);
      window.clearInterval(refresh);
    };
  }, [load]);

  const waiting = clips.filter((c) => c.status === "QUALITY_APPROVED");
  const approved = clips.filter((c) => c.status !== "QUALITY_APPROVED");

  return (
    <div className="page camp-page">
      <PageHeader
        title="Kampagnen"
        description="Clipping-Kampagnen (Content Rewards): Die Engine schneidet das Material, prüft die Regeln und veröffentlicht nach deiner Freigabe. Den Link reichst du auf der Kampagnenseite ein und hakst ihn hier ab."
      />
      <ErrorText error={error} />

      <Section title={`Jetzt einreichen (${open.length})`}>
        {open.length === 0 ? (
          <p className="muted">
            Keine offenen Links. Neue Beiträge erscheinen hier sofort nach dem Veröffentlichen.
          </p>
        ) : (
          <div className="sub-list">
            {open.map((s) => (
              <SubmissionCard key={s.id} sub={s} now={now} canEdit={canEdit} onChanged={load} />
            ))}
          </div>
        )}
      </Section>

      <Section title={`Clips zur Freigabe (${waiting.length})`}>
        {waiting.length === 0 ? (
          <p className="muted">
            Keine Clips warten. Material bei einer Kampagne hochladen, dann schneidet die Engine es.
          </p>
        ) : (
          <div className="appr-list">
            {waiting.map((c) => (
              <ClipCard key={c.id} clip={c} canEdit={canEdit} onChanged={load} />
            ))}
          </div>
        )}
        {approved.length > 0 && (
          <details className="appr-details">
            <summary>Freigegeben und eingeplant ({approved.length})</summary>
            <div className="appr-list">
              {approved.map((c) => (
                <ClipCard key={c.id} clip={c} canEdit={canEdit} onChanged={load} />
              ))}
            </div>
          </details>
        )}
      </Section>

      <Section title="Erledigt">
        <DoneList subs={done} canEdit={canEdit} onChanged={load} />
      </Section>

      <Section title={`Kampagnen (${campaigns.length})`}>
        {campaigns.length === 0 ? (
          <p className="muted">Noch keine Kampagne angelegt.</p>
        ) : (
          <div className="camp-list">
            {campaigns.map((c) => (
              <CampaignCard key={c.id} campaign={c} canEdit={canEdit} onChanged={load} />
            ))}
          </div>
        )}
      </Section>

      {canEdit && (
        <Section title="Neue Kampagne">
          <p className="muted small">
            Werte aus der Kampagnenbeschreibung übernehmen. Die Kampagne wird zur Lizenz: Ihr
            Material darf nur für diese Kampagne, auf den gewählten Kanälen und bis zum Enddatum
            verwendet werden.
          </p>
          <NewCampaignForm projects={projects} channels={channels} games={games} onCreated={load} />
        </Section>
      )}
    </div>
  );
}
