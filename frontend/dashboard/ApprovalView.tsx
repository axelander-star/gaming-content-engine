"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { PLATFORM_LABELS, formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  ApprovalInfo,
  ApprovalPost,
  Channel,
  ContentProject,
  LibraryItem,
  VideoStatus,
} from "@/lib/types";

type Tab = "review" | "approved" | "published" | "all";

const TABS: { key: Tab; label: string; statuses: VideoStatus[] | null }[] = [
  { key: "review", label: "Zu prüfen", statuses: ["QUALITY_APPROVED"] },
  { key: "approved", label: "Freigegeben", statuses: ["READY_TO_PUBLISH", "SCHEDULED"] },
  {
    key: "published",
    label: "Veröffentlicht",
    statuses: ["PUBLISHED", "ANALYTICS_PENDING", "ANALYZED"],
  },
  { key: "all", label: "Alle", statuses: null },
];

const STATUS_TEXT: Partial<Record<VideoStatus, { label: string; tone: "ok" | "warn" | "neutral" | "danger" }>> = {
  QUALITY_APPROVED: { label: "Wartet auf Freigabe", tone: "warn" },
  READY_TO_PUBLISH: { label: "Freigegeben", tone: "ok" },
  SCHEDULED: { label: "Eingeplant", tone: "ok" },
  PUBLISHED: { label: "Veröffentlicht", tone: "neutral" },
  ANALYTICS_PENDING: { label: "Veröffentlicht", tone: "neutral" },
  ANALYZED: { label: "Veröffentlicht", tone: "neutral" },
  ARCHIVED: { label: "Verworfen", tone: "neutral" },
};

const PRIVACY_LABELS: Record<string, string> = {
  private: "Privat",
  unlisted: "Nicht gelistet",
  public: "Öffentlich",
};

function toLocalInput(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function PlatformOptions({
  post,
  info,
  disabled,
  onChange,
}: {
  post: ApprovalPost;
  info: ApprovalInfo | null;
  disabled: boolean;
  onChange: (options: Record<string, unknown>) => void;
}) {
  const o = post.options;
  if (post.platform === "youtube") {
    return (
      <div className="appr-options">
        <label>
          Sichtbarkeit
          <select
            value={String(o.privacy ?? "private")}
            disabled={disabled || Boolean(o.publish_at)}
            onChange={(e) => onChange({ privacy: e.target.value })}
          >
            {(info?.youtube_privacy ?? ["private", "unlisted", "public"]).map((p) => (
              <option key={p} value={p}>
                {PRIVACY_LABELS[p] ?? p}
              </option>
            ))}
          </select>
        </label>
        <label>
          Format
          <select
            value={String(o.format ?? "short")}
            disabled={disabled}
            onChange={(e) => onChange({ format: e.target.value })}
          >
            <option value="short">Short (Hochformat, bis 3 min)</option>
            <option value="video">Normales Video</option>
          </select>
        </label>
        <label>
          Geplante Veröffentlichung auf YouTube (optional)
          <input
            type="datetime-local"
            value={toLocalInput(o.publish_at)}
            disabled={disabled}
            onChange={(e) =>
              onChange({
                publish_at: e.target.value ? new Date(e.target.value).toISOString() : null,
              })
            }
          />
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={Boolean(o.made_for_kids)}
            disabled={disabled}
            onChange={(e) => onChange({ made_for_kids: e.target.checked })}
          />
          <span>Speziell für Kinder</span>
        </label>
      </div>
    );
  }
  if (post.platform === "tiktok") {
    return (
      <div className="appr-options">
        <label>
          Art
          <select
            value={String(o.mode ?? "inbox")}
            disabled={disabled}
            onChange={(e) => onChange({ mode: e.target.value })}
          >
            <option value="inbox">Entwurf in die TikTok-App (empfohlen)</option>
            <option value="direct">Direkt posten (privat, bis die App geprüft ist)</option>
          </select>
        </label>
        {o.mode !== "direct" && (
          <p className="muted small">
            Das Video landet als Entwurf im TikTok-Postfach. Text und Veröffentlichung schließt du
            in der App ab; höchstens fünf offene Entwürfe pro Tag.
          </p>
        )}
      </div>
    );
  }
  if (post.platform === "instagram") {
    return (
      <div className="appr-options">
        <label className="check-label">
          <input
            type="checkbox"
            checked={Boolean(o.share_to_feed ?? true)}
            disabled={disabled}
            onChange={(e) => onChange({ share_to_feed: e.target.checked })}
          />
          <span>Reel auch im Feed zeigen</span>
        </label>
      </div>
    );
  }
  return null;
}

function PostCard({
  post,
  info,
  canEdit,
  onChanged,
  onError,
}: {
  post: ApprovalPost;
  info: ApprovalInfo | null;
  canEdit: boolean;
  onChanged: (p: ApprovalPost) => void;
  onError: (msg: string | null) => void;
}) {
  const [title, setTitle] = useState(post.title);
  const [description, setDescription] = useState(post.description);
  const [hashtags, setHashtags] = useState(post.hashtags.map((t) => `#${t}`).join(" "));
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);
  const editable = canEdit && post.status === "QUALITY_APPROVED";
  const rules = info?.platforms.find((p) => p.code === post.platform);
  const dirty =
    title !== post.title ||
    description !== post.description ||
    hashtags !== post.hashtags.map((t) => `#${t}`).join(" ");

  useEffect(() => {
    setTitle(post.title);
    setDescription(post.description);
    setHashtags(post.hashtags.map((t) => `#${t}`).join(" "));
  }, [post]);

  async function run(fn: () => Promise<ApprovalPost>) {
    setBusy(true);
    onError(null);
    try {
      onChanged(await fn());
    } catch (err) {
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function tagList(): string[] {
    return hashtags
      .split(/[\s,]+/)
      .map((t) => t.replace(/^#/, "").trim())
      .filter(Boolean);
  }

  async function save(e?: FormEvent) {
    e?.preventDefault();
    await run(() => api.updatePost(post.id, { title, description, hashtags: tagList() }));
  }

  async function approve() {
    if (dirty) {
      await run(() => api.updatePost(post.id, { title, description, hashtags: tagList() }));
    }
    await run(() => api.approvePost(post.id));
  }

  const status = STATUS_TEXT[post.status] ?? { label: post.status, tone: "neutral" as const };
  const captionLength = post.caption.length;

  return (
    <article className="card appr-card" aria-label={`Beitrag ${post.channel}`}>
      <div className="appr-media">
        {preview ? (
          <video
            controls
            autoPlay
            preload="metadata"
            poster={api.libraryFileUrl(post.item_id, "thumb")}
            src={api.libraryFileUrl(post.item_id, "rendition")}
            onError={(e) => {
              const v = e.currentTarget;
              const original = api.libraryFileUrl(post.item_id, "original");
              if (!v.src.endsWith(original)) v.src = original;
            }}
          />
        ) : (
          <button
            type="button"
            className="appr-poster"
            onClick={() => setPreview(true)}
            aria-label={`Vorschau ${post.item_title} abspielen`}
          >
            <img src={api.libraryFileUrl(post.item_id, "thumb")} alt="" loading="lazy" />
            <span className="appr-play" aria-hidden="true">
              ▶
            </span>
          </button>
        )}
      </div>
      <div className="appr-body">
        <div className="idea-meta">
          <span className={`chip chip-${post.platform}`}>{PLATFORM_LABELS[post.platform]}</span>
          <span className="chip">{post.channel}</span>
          <span className="chip">{post.project}</span>
          <Badge tone={status.tone}>{status.label}</Badge>
        </div>
        <p className="muted small">Video: {post.item_title}</p>
        {editable ? (
          <form className="appr-form" onSubmit={save} aria-label={`Texte ${post.channel}`}>
            <label>
              Titel
              <input
                value={title}
                maxLength={rules?.title_max ?? 300}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label>
              Beschreibung
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
          <div className="appr-caption">
            <p className="appr-title">{post.title}</p>
            {post.description && <p>{post.description}</p>}
            {post.hashtags.length > 0 && (
              <p className="muted">{post.hashtags.map((t) => `#${t}`).join(" ")}</p>
            )}
          </div>
        )}
        <PlatformOptions
          post={post}
          info={info}
          disabled={!editable || busy}
          onChange={(options) => run(() => api.updatePost(post.id, { options }))}
        />
        <details className="appr-details">
          <summary>
            Prüfung: {post.checks.filter((c) => c.passed).length}/{post.checks.length} technisch in
            Ordnung · Text {captionLength}
            {rules ? `/${rules.caption_max}` : ""} Zeichen
          </summary>
          <ul className="appr-checks">
            {post.checks.map((c) => (
              <li key={c.name} className={c.passed ? "ok" : "bad"}>
                {c.passed ? "✓" : "✗"} {c.detail}
              </li>
            ))}
          </ul>
          <pre className="appr-preview-text">{post.caption}</pre>
        </details>
        {post.problems.length > 0 && (
          <ul className="appr-problems" aria-label="Offene Punkte">
            {post.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        {post.scheduled_for && (
          <p className="small">Eingeplant für {formatDateTime(post.scheduled_for)}</p>
        )}
        {post.published_mock !== null && (
          <p className="small">
            {post.published_mock
              ? "Testveröffentlichung (Mock), nichts wurde hochgeladen."
              : post.published_url?.startsWith("https://")
                ? (
                    <a href={post.published_url} target="_blank" rel="noreferrer">
                      Beitrag ansehen
                    </a>
                  )
                : "Hochgeladen (Entwurf oder in Prüfung)."}
          </p>
        )}
        {canEdit && (
          <div className="row-actions">
            {post.status === "QUALITY_APPROVED" && (
              <>
                <button
                  type="button"
                  className="btn btn-primary btn-small"
                  disabled={busy || post.problems.length > 0}
                  onClick={approve}
                >
                  Freigeben
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  disabled={busy}
                  onClick={() => run(() => api.discardPost(post.id))}
                >
                  Verwerfen
                </button>
              </>
            )}
            {(post.status === "READY_TO_PUBLISH" || post.status === "SCHEDULED") && (
              <button
                type="button"
                className="btn btn-small"
                disabled={busy}
                onClick={() => run(() => api.withdrawPost(post.id))}
              >
                Freigabe zurückziehen
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

function PreparePanel({
  projects,
  info,
  onDone,
}: {
  projects: ContentProject[];
  info: ApprovalInfo | null;
  onDone: (posts: ApprovalPost[]) => void;
}) {
  const [projectId, setProjectId] = useState<number | "">("");
  const [videos, setVideos] = useState<LibraryItem[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [itemId, setItemId] = useState<number | "">("");
  const [picked, setPicked] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .channels()
      .then(setChannels)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    setItemId("");
    setPicked([]);
    if (projectId === "") {
      setVideos([]);
      return;
    }
    api
      .library({ projectId, kind: "video" })
      .then((items) => setVideos(items.filter((i) => i.status === "ready")))
      .catch((e: Error) => setError(e.message));
  }, [projectId]);

  const projectChannels = channels.filter((c) => c.content_project_id === projectId);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (itemId === "" || picked.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await api.preparePosts(itemId, picked));
      setPicked([]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Neuer Beitrag">
      <p className="muted small">
        Ein fertiges Video aus der Mediathek für Kanäle desselben Themenbereichs vorbereiten. Titel,
        Beschreibung und Hashtags schlägt die KI vor; du prüfst und gibst frei.
      </p>
      <form className="source-form" aria-label="Beitrag vorbereiten" onSubmit={submit}>
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
          Video
          <select
            value={itemId}
            onChange={(e) => setItemId(e.target.value ? Number(e.target.value) : "")}
            required
            disabled={projectId === ""}
          >
            <option value="">{videos.length ? "Bitte wählen" : "Keine fertigen Videos"}</option>
            {videos.map((v) => (
              <option key={v.id} value={v.id}>
                {v.title}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="appr-channels">
          <legend>Kanäle</legend>
          {projectId !== "" && projectChannels.length === 0 && (
            <p className="muted small">Dieser Themenbereich hat noch keine Kanäle.</p>
          )}
          {projectChannels.map((c) => (
            <label key={c.id} className="check-label">
              <input
                type="checkbox"
                checked={picked.includes(c.id)}
                onChange={(e) =>
                  setPicked(e.target.checked ? [...picked, c.id] : picked.filter((x) => x !== c.id))
                }
              />
              <span>
                {c.name} · {PLATFORM_LABELS[c.platform]}
              </span>
            </label>
          ))}
        </fieldset>
        <button
          className="btn btn-primary"
          type="submit"
          disabled={busy || itemId === "" || picked.length === 0}
        >
          {busy ? "Wird vorbereitet …" : "Beiträge vorbereiten"}
        </button>
      </form>
      <ErrorText error={error} />
      {info && <p className="muted small appr-twitch">Twitch: {info.twitch_note}</p>}
    </Section>
  );
}

/** Approval center: check texts, platforms and options, then release posts (E8). */
export function ApprovalView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "operator");
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [info, setInfo] = useState<ApprovalInfo | null>(null);
  const [projectId, setProjectId] = useState<number | undefined>(undefined);
  const [tab, setTab] = useState<Tab>("review");
  const [posts, setPosts] = useState<ApprovalPost[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .approvalPosts({ projectId })
      .then(setPosts)
      .catch((e: Error) => setError(e.message));
  }, [projectId]);

  useEffect(() => {
    api
      .projects()
      .then((all) => setProjects(all.filter((p) => p.status !== "archived")))
      .catch((e: Error) => setError(e.message));
    api
      .approvalInfo()
      .then(setInfo)
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const shown = useMemo(() => {
    const statuses = TABS.find((t) => t.key === tab)?.statuses;
    return (posts ?? []).filter((p) => !statuses || statuses.includes(p.status));
  }, [posts, tab]);

  function replace(updated: ApprovalPost) {
    setPosts((prev) =>
      prev
        ? updated.status === "ARCHIVED"
          ? prev.filter((p) => p.id !== updated.id)
          : prev.map((p) => (p.id === updated.id ? updated : p))
        : prev,
    );
  }

  return (
    <>
      <PageHeader
        title="Freigabecenter"
        description="Beiträge aus der Mediathek prüfen und freigeben. Wann ein freigegebener Beitrag erscheint, entscheidet die Veröffentlichungsstrategie je Kanal."
      />
      {info?.publishing_mode === "mock" && (
        <p className="notice">
          Testbetrieb: Freigegebene Beiträge werden nur simuliert, auf keiner Plattform erscheint
          etwas.
        </p>
      )}
      <div className="toolbar">
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
        <div className="tabs" role="tablist" aria-label="Status der Beiträge">
          {TABS.map((t) => {
            const count = (posts ?? []).filter(
              (p) => !t.statuses || t.statuses.includes(p.status),
            ).length;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={tab === t.key}
                className={`tab${tab === t.key ? " is-active" : ""}`}
                onClick={() => setTab(t.key)}
              >
                {t.label} ({count})
              </button>
            );
          })}
        </div>
      </div>
      <ErrorText error={error} />
      <div className="chat-layout">
        <div className="appr-list">
          {posts && shown.length === 0 && <p className="muted">Keine Beiträge in dieser Ansicht.</p>}
          {shown.map((post) => (
            <PostCard
              key={post.id}
              post={post}
              info={info}
              canEdit={canEdit}
              onChanged={replace}
              onError={setError}
            />
          ))}
        </div>
        {canEdit && (
          <div className="side-stack">
            <PreparePanel
              projects={projects}
              info={info}
              onDone={(created) => {
                setPosts((prev) => [...created, ...(prev ?? [])]);
                setTab("review");
              }}
            />
          </div>
        )}
      </div>
    </>
  );
}
