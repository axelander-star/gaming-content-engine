"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { useAuth } from "@/components/AuthProvider";
import { Badge, ErrorText, PageHeader, Section } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/labels";
import { hasRole } from "@/lib/roles";
import type {
  ContentProject,
  LibraryInfo,
  LibraryItem,
  LibraryKind,
  LibraryOrigin,
} from "@/lib/types";
import { resumableUpload } from "@/lib/upload";
import type { UploadProgress } from "@/lib/upload";

const KIND_LABELS: Record<LibraryKind, string> = { video: "Video", image: "Bild", audio: "Audio" };
const ORIGIN_LABELS: Record<LibraryOrigin, string> = {
  upload: "Eigene Aufnahme",
  generated: "Selbst erzeugt",
};

export function formatBytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  if (n >= 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1024))} KB`;
}

export function formatSeconds(s: number | null): string {
  if (s === null) return "–";
  const m = Math.floor(s / 60);
  const rest = Math.round(s % 60);
  return m > 0 ? `${m}:${String(rest).padStart(2, "0")} min` : `${s.toFixed(1)} s`;
}

function UploadPanel({
  projects,
  info,
  onDone,
}: {
  projects: ContentProject[];
  info: LibraryInfo | null;
  onDone: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [projectId, setProjectId] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file || projectId === "" || !confirmed) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setError(null);
    setMessage(null);
    setProgress({ sent: 0, total: file.size, retrying: false });
    try {
      const done = await resumableUpload(file, {
        purpose: "library",
        params: {
          project_id: projectId,
          rights_confirmed: true,
          ...(title ? { title } : {}),
        },
        onProgress: setProgress,
        signal: controller.signal,
      });
      setMessage(
        `Datei #${String(done.result?.library_item_id ?? "?")} gespeichert. ` +
          "Vorschau und Hochformat entstehen gleich im Hintergrund.",
      );
      setTitle("");
      setConfirmed(false);
      if (fileRef.current) fileRef.current.value = "";
      onDone();
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError("Upload angehalten. Dieselbe Datei erneut wählen, um fortzusetzen.");
      } else {
        setError((err as Error).message);
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
      setProgress(null);
    }
  }

  const percent =
    progress && progress.total > 0 ? Math.floor((progress.sent / progress.total) * 100) : 0;
  const accept = info ? Object.keys(info.allowed_types).join(",") : "video/*,image/*,audio/*";

  return (
    <Section title="Datei hochladen">
      <p className="muted small">
        Eigene Videos (MP4, MOV, MKV), Bilder (PNG, JPEG, WebP) oder Ton (MP3, WAV, M4A). Das
        Original bleibt unverändert; Videos bis{" "}
        {info ? Math.round(info.max_rendition_s / 60) : 3} Minuten bekommen zusätzlich eine
        Fassung im Hochformat 9:16.
      </p>
      <form className="source-form" aria-label="Datei hochladen" onSubmit={submit}>
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
          Datei
          <input ref={fileRef} type="file" accept={accept} required />
        </label>
        <label>
          Titel (optional)
          <input value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            required
          />
          <span>{info?.rights_statement ?? "Eigene Aufnahme bestätigen"}</span>
        </label>
        <div className="row-actions">
          <button className="btn btn-primary" type="submit" disabled={busy || !confirmed}>
            {busy ? "Wird hochgeladen …" : "Hochladen"}
          </button>
          {busy && (
            <button className="btn" type="button" onClick={() => abortRef.current?.abort()}>
              Anhalten
            </button>
          )}
        </div>
      </form>
      {progress && (
        <div className="meter" role="progressbar" aria-valuenow={percent} aria-label="Fortschritt">
          <span style={{ width: `${percent}%` }} />
        </div>
      )}
      {message && <p className="notice">{message}</p>}
      <ErrorText error={error} />
    </Section>
  );
}

function ItemCard({
  item,
  canEdit,
  onChange,
  onError,
}: {
  item: LibraryItem;
  canEdit: boolean;
  onChange: () => void;
  onError: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn();
      onChange();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  const layout = typeof item.rendition.layout === "string" ? item.rendition.layout : null;
  const skipped = typeof item.rendition.skipped === "string" ? item.rendition.skipped : null;

  return (
    <article className="card lib-card" aria-label={`Datei ${item.title}`}>
      <button
        type="button"
        className="lib-thumb"
        onClick={() => setOpen(!open)}
        aria-label={`${item.title} ${open ? "schließen" : "ansehen"}`}
      >
        {item.has_thumb ? (
          <img src={api.libraryFileUrl(item.id, "thumb")} alt="" loading="lazy" />
        ) : (
          <span className="muted small">{KIND_LABELS[item.kind]}</span>
        )}
        {item.duration_s !== null && (
          <span className="lib-duration">{formatSeconds(item.duration_s)}</span>
        )}
      </button>
      <div className="lib-body">
        <h3>{item.title}</h3>
        <div className="idea-meta">
          <span className="chip">{item.project}</span>
          <Badge tone={item.origin === "generated" ? "ok" : "neutral"}>
            {ORIGIN_LABELS[item.origin]}
          </Badge>
          {item.status === "processing" && <Badge tone="warn">Wird verarbeitet</Badge>}
          {item.status === "failed" && <Badge tone="danger">Fehler</Badge>}
        </div>
        <p className="muted small">
          {KIND_LABELS[item.kind]}
          {item.width && item.height ? ` · ${item.width}×${item.height}` : ""}
          {item.fps ? ` · ${item.fps} fps` : ""}
          {item.video_codec ? ` · ${item.video_codec}` : ""} · {formatBytes(item.size_bytes)}
        </p>
        {item.status === "ready" && (
          <p className="muted small">
            {item.has_rendition
              ? layout === "original"
                ? "Schon Hochformat, Original wird verwendet"
                : `Hochformat 9:16 fertig${item.render_seconds !== null ? ` (${item.render_seconds.toFixed(1)} s)` : ""}`
              : (skipped ?? "Keine Hochformat-Fassung")}
          </p>
        )}
        {item.error_message && <p className="feed-error small">{item.error_message}</p>}
        {open && (
          <div className="lib-preview">
            {item.kind === "video" && (
              <video
                controls
                preload="metadata"
                poster={item.has_thumb ? api.libraryFileUrl(item.id, "thumb") : undefined}
                src={api.libraryFileUrl(item.id, item.has_rendition ? "rendition" : "original")}
              />
            )}
            {item.kind === "image" && (
                  <img src={api.libraryFileUrl(item.id, "rendition")} alt={item.title} />
            )}
            {item.kind === "audio" && (
              <audio controls src={api.libraryFileUrl(item.id, "original")} />
            )}
            <p className="muted small">
              {item.origin === "upload"
                ? `Rechte bestätigt am ${formatDateTime(String(item.rights.confirmed_at ?? ""))}`
                : `Selbst erzeugt, Stimme: ${String(item.rights.voice_provider ?? "–")}, kein fremdes Video`}
            </p>
            <a className="btn btn-ghost btn-small" href={api.libraryFileUrl(item.id, "original")}>
              Original herunterladen
            </a>
          </div>
        )}
        {canEdit && (
          <div className="row-actions">
            {item.status === "failed" && (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                onClick={() => act(() => api.reprocessLibraryItem(item.id))}
              >
                Erneut verarbeiten
              </button>
            )}
            {item.archived ? (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                onClick={() => act(() => api.restoreLibraryItem(item.id))}
              >
                Zurückholen
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-ghost btn-small"
                aria-label={`${item.title} archivieren`}
                onClick={() => act(() => api.archiveLibraryItem(item.id))}
              >
                Archivieren
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

/** Media library: own uploads and generated videos per topic area (extension E7). */
export function LibraryView() {
  const { user } = useAuth();
  const canEdit = hasRole(user?.role, "operator");
  const [projects, setProjects] = useState<ContentProject[]>([]);
  const [info, setInfo] = useState<LibraryInfo | null>(null);
  const [projectId, setProjectId] = useState<number | undefined>(undefined);
  const [kind, setKind] = useState<LibraryKind | undefined>(undefined);
  const [archived, setArchived] = useState(false);
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .library({ projectId, kind, archived })
      .then(setItems)
      .catch((e: Error) => setError(e.message));
  }, [projectId, kind, archived]);

  useEffect(() => {
    api
      .projects()
      .then((all) => setProjects(all.filter((p) => p.status !== "archived")))
      .catch((e: Error) => setError(e.message));
    api
      .libraryInfo()
      .then(setInfo)
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  // refresh while files are still being processed
  const processing = items?.some((i) => i.status === "processing") ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [processing, load]);

  return (
    <>
      <PageHeader
        title="Mediathek"
        description="Eigene Aufnahmen und selbst erzeugte Videos je Themenbereich. Das Original bleibt unverändert; veröffentlicht wird von hier aus nichts."
      />
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
        <div className="tabs" role="tablist" aria-label="Art der Dateien">
          {([undefined, "video", "image", "audio"] as (LibraryKind | undefined)[]).map((k) => (
            <button
              key={k ?? "all"}
              type="button"
              role="tab"
              aria-selected={kind === k}
              className={`tab${kind === k ? " is-active" : ""}`}
              onClick={() => setKind(k)}
            >
              {k ? KIND_LABELS[k] : "Alle"}
            </button>
          ))}
        </div>
        <label className="check-label">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => setArchived(e.target.checked)}
          />
          Archiv
        </label>
      </div>
      <ErrorText error={error} />
      <div className="chat-layout">
        <div className="lib-grid">
          {items && items.length === 0 && (
            <p className="muted">Noch keine Dateien in dieser Ansicht.</p>
          )}
          {items?.map((item) => (
            <ItemCard
              key={item.id}
              item={item}
              canEdit={canEdit}
              onChange={load}
              onError={setError}
            />
          ))}
        </div>
        {canEdit && (
          <div className="side-stack">
            <UploadPanel projects={projects} info={info} onDone={load} />
          </div>
        )}
      </div>
    </>
  );
}
