// Resumable uploads in parts (backend: api/uploads.py, protocol: docs/UPLOADS.md).
//
// Cloudflare passes at most 100 MB per request, so files go up in parts of
// `chunk_bytes`. After a dropped connection, a reload or a closed tab the upload
// continues where it stopped: the session id is remembered per file in
// localStorage and the server reports how many bytes it already has.

import { ApiError, readCookie, request } from "./api";

export type UploadStatus = "UPLOADING" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";

export interface UploadSession {
  id: string;
  purpose: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  received_bytes: number;
  chunk_bytes: number;
  status: UploadStatus;
  result: Record<string, unknown> | null;
  error_message: string | null;
  expires_at: string;
  created_at: string;
}

export interface UploadProgress {
  sent: number;
  total: number;
  /** True while waiting before a retry after a network error. */
  retrying: boolean;
}

export interface ResumableUploadOptions {
  purpose: string;
  params: Record<string, unknown>;
  onProgress?: (p: UploadProgress) => void;
  signal?: AbortSignal;
  /** Attempts per part before giving up (network errors and 5xx answers). */
  maxRetries?: number;
}

const STORAGE_PREFIX = "gce-upload:";
const OFFSET_HEADER = "Upload-Offset";

/** Stable key for "the same file again": name, size and modification time. */
function fileKey(purpose: string, file: File): string {
  return `${STORAGE_PREFIX}${purpose}:${file.name}:${file.size}:${file.lastModified}`;
}

function remember(key: string, id: string | null): void {
  try {
    if (id) localStorage.setItem(key, id);
    else localStorage.removeItem(key);
  } catch {
    // Private mode or blocked storage: the upload still works, only without resume.
  }
}

function recall(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Upload abgebrochen", "AbortError"));
    });
  });

function csrfHeaders(): Headers {
  const headers = new Headers();
  const csrf = readCookie("gce_csrf");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  return headers;
}

async function sendPart(
  id: string,
  offset: number,
  blob: Blob,
  signal?: AbortSignal,
): Promise<{ session?: UploadSession; expectedOffset?: number }> {
  const headers = csrfHeaders();
  headers.set(OFFSET_HEADER, String(offset));
  headers.set("Content-Type", "application/octet-stream");
  const res = await fetch(`/api/uploads/${id}`, {
    method: "PATCH",
    body: blob,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    signal,
  });
  if (res.status === 409 && res.headers.get(OFFSET_HEADER) !== null) {
    // The server has a different offset (e.g. a part arrived but the answer got lost).
    return { expectedOffset: Number(res.headers.get(OFFSET_HEADER)) };
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body ? String(body.detail) : "";
    throw new ApiError(res.status, detail || `Teil-Upload fehlgeschlagen (${res.status})`);
  }
  return { session: body as UploadSession };
}

function retryable(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "AbortError") return false;
  if (err instanceof ApiError) return err.status >= 500 || err.status === 408 || err.status === 429;
  return true; // network error (TypeError from fetch)
}

async function openSession(
  file: File,
  opts: ResumableUploadOptions,
  key: string,
): Promise<UploadSession> {
  const known = recall(key);
  if (known) {
    try {
      const s = await request<UploadSession>(`/uploads/${known}`);
      if (s.status === "UPLOADING" || s.status === "COMPLETED") return s;
    } catch {
      // expired, cancelled or from another account: start fresh
    }
    remember(key, null);
  }
  const s = await request<UploadSession>("/uploads", {
    method: "POST",
    body: JSON.stringify({
      purpose: opts.purpose,
      filename: file.name,
      size_bytes: file.size,
      content_type: file.type || "application/octet-stream",
      params: opts.params,
    }),
  });
  remember(key, s.id);
  return s;
}

/**
 * Upload `file` in parts and hand it to the consumer `purpose`. Resumes an earlier
 * attempt for the same file automatically. Resolves with the finished session
 * (status COMPLETED, see `result`); rejects with the server's message otherwise.
 */
export async function resumableUpload(
  file: File,
  opts: ResumableUploadOptions,
): Promise<UploadSession> {
  const key = fileKey(opts.purpose, file);
  const maxRetries = opts.maxRetries ?? 8;
  let session = await openSession(file, opts, key);
  let offset = session.received_bytes;
  let failures = 0;
  const report = (retrying: boolean) =>
    opts.onProgress?.({ sent: offset, total: file.size, retrying });
  report(false);

  while (session.status === "UPLOADING" && offset < file.size) {
    const end = Math.min(offset + session.chunk_bytes, file.size);
    try {
      const r = await sendPart(session.id, offset, file.slice(offset, end), opts.signal);
      if (r.expectedOffset !== undefined) {
        offset = r.expectedOffset;
      } else if (r.session) {
        session = r.session;
        offset = session.received_bytes;
      }
      failures = 0;
      report(false);
    } catch (err) {
      failures += 1;
      if (!retryable(err) || failures > maxRetries) throw err;
      report(true);
      await sleep(Math.min(30_000, 1000 * 2 ** (failures - 1)), opts.signal);
      // Ask the server where to continue; the last part may have arrived.
      try {
        session = await request<UploadSession>(`/uploads/${session.id}`);
        offset = session.received_bytes;
      } catch {
        // still offline: the next loop iteration retries the same part
      }
    }
  }

  let done = session;
  for (let attempt = 0; done.status !== "COMPLETED" && done.status !== "FAILED"; attempt++) {
    try {
      done = await request<UploadSession>(`/uploads/${session.id}/complete`, {
        method: "POST",
      });
    } catch (err) {
      // A long check can outlast a proxy timeout; completing again is safe.
      if (!retryable(err) || attempt >= maxRetries) throw err;
      await sleep(Math.min(30_000, 2000 * 2 ** attempt), opts.signal);
    }
  }
  remember(key, null);
  if (done.status === "FAILED") {
    throw new ApiError(422, done.error_message ?? "Verarbeitung fehlgeschlagen");
  }
  return done;
}

/** Cancel an upload and forget it (the partial file is deleted on the server). */
export async function cancelUpload(id: string): Promise<UploadSession> {
  return request<UploadSession>(`/uploads/${id}`, { method: "DELETE" });
}
