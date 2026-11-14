// Thin, typed client for the backend API.
// Sessions live in an HttpOnly cookie; state-changing requests send the
// CSRF token from the readable `gce_csrf` cookie as `X-CSRF-Token` header.

import type {
  Agent,
  AgentDecision,
  AgentRun,
  Budget,
  Channel,
  Clip,
  Creator,
  EffectiveControls,
  Game,
  Language,
  License,
  LicenseDocument,
  LicenseTerms,
  Material,
  MaterialStatus,
  OperationsSettings,
  Overview,
  PolicyStatus,
  PublisherPolicy,
  Readiness,
  RenderCapacity,
  Scene,
  SettingsResponse,
  Source,
  SourceType,
  TrendHistoryPoint,
  TrendItem,
  TrendReport,
  TrendSourceStatus,
  User,
  UserRole,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d)))
        .join("; ");
    }
  }
  return `Request failed (${status})`;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (!SAFE_METHODS.has(method)) {
    const csrf = readCookie("gce_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const res = await fetch(`/api${path}`, {
    ...init,
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status));
  return body as T;
}

const json = (data: unknown): string => JSON.stringify(data);

/** Multipart upload; the browser sets the Content-Type with the boundary itself. */
async function upload<T>(
  path: string,
  file: File,
  fields: Record<string, string> = {},
): Promise<T> {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  form.append("file", file);
  const headers = new Headers();
  const csrf = readCookie("gce_csrf");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const res = await fetch(`/api${path}`, {
    method: "POST",
    body: form,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, res.status));
  return body as T;
}

export const api = {
  login: (email: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: json({ email, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),

  readiness: () => request<Readiness>("/health/ready"),
  overview: () => request<Overview>("/overview"),

  settings: () => request<SettingsResponse>("/settings"),
  updateControls: (
    changes: Partial<Pick<EffectiveControls, "emergency_stop" | "auto_publish_enabled">>,
  ) => request<EffectiveControls>("/settings/controls", { method: "PATCH", body: json(changes) }),
  updateOperations: (changes: Partial<OperationsSettings>) =>
    request<OperationsSettings>("/settings/operations", { method: "PATCH", body: json(changes) }),

  channels: () => request<Channel[]>("/channels"),
  pauseChannel: (id: number) => request<Channel>(`/channels/${id}/pause`, { method: "POST" }),
  resumeChannel: (id: number) => request<Channel>(`/channels/${id}/resume`, { method: "POST" }),
  setChannelLimits: (
    id: number,
    limits: Pick<Channel, "min_posts_per_day" | "max_posts_per_day" | "min_interval_minutes">,
  ) => request<Channel>(`/channels/${id}/limits`, { method: "PUT", body: json(limits) }),

  agents: () => request<Agent[]>("/agents"),
  agentRuns: (name: string, limit = 20) =>
    request<AgentRun[]>(`/agents/${encodeURIComponent(name)}/runs?limit=${limit}`),
  agentDecisions: (agent?: string, limit = 50) =>
    request<AgentDecision[]>(
      `/agents/decisions?limit=${limit}${agent ? `&agent=${encodeURIComponent(agent)}` : ""}`,
    ),
  budget: () => request<Budget>("/agents/budget"),
  pauseAgent: (name: string) =>
    request<void>(`/agents/${encodeURIComponent(name)}/pause`, { method: "POST" }),
  resumeAgent: (name: string) =>
    request<void>(`/agents/${encodeURIComponent(name)}/resume`, { method: "POST" }),
  runAgent: (name: string) =>
    request<{ agent: string; job_id: string }>(`/agents/${encodeURIComponent(name)}/run`, {
      method: "POST",
    }),

  trends: (language: Language, limit = 10) =>
    request<TrendItem[]>(`/trends?language=${language}&limit=${limit}`),
  trendReport: (language: Language) =>
    request<TrendReport | null>(`/trends/report?language=${language}`),
  games: () => request<Game[]>("/games"),
  game: (id: number) => request<Game>(`/games/${id}`),
  gameHistory: (id: number, language: Language, days = 30) =>
    request<TrendHistoryPoint[]>(`/games/${id}/history?language=${language}&days=${days}`),
  trendSources: () => request<TrendSourceStatus[]>("/trends/sources"),
  testTrendSource: (name: TrendSourceStatus["name"]) =>
    request<TrendSourceStatus>(`/trends/sources/${name}/test`, { method: "POST" }),

  // rights management (Phase 6)
  creators: () => request<Creator[]>("/creators"),
  createCreator: (data: { name: string; contact?: string; notes?: string }) =>
    request<Creator>("/creators", { method: "POST", body: json(data) }),
  setCreatorBlocked: (id: number, blocked: boolean) =>
    request<{ rechecked: number[] }>(`/creators/${id}/${blocked ? "block" : "unblock"}`, {
      method: "POST",
    }),
  sources: () => request<Source[]>("/sources"),
  createSource: (data: {
    creator_id: number | null;
    type: SourceType;
    name: string;
    url?: string;
    provenance_notes?: string;
  }) => request<Source>("/sources", { method: "POST", body: json(data) }),
  setSourceBlocked: (id: number, blocked: boolean) =>
    request<{ rechecked: number[] }>(`/sources/${id}/${blocked ? "block" : "unblock"}`, {
      method: "POST",
    }),
  licenses: () => request<License[]>("/licenses"),
  createLicense: (data: Partial<LicenseTerms> & { source_id: number }) =>
    request<License>("/licenses", { method: "POST", body: json(data) }),
  updateLicense: (id: number, terms: LicenseTerms) =>
    request<License>(`/licenses/${id}`, { method: "PATCH", body: json(terms) }),
  setLicenseStatus: (id: number, action: "approve" | "reject" | "revoke", note?: string) =>
    request<License>(`/licenses/${id}/${action}`, {
      method: "POST",
      body: action === "approve" ? undefined : json({ note: note ?? null }),
    }),
  licenseDocuments: (id: number) => request<LicenseDocument[]>(`/licenses/${id}/documents`),
  uploadLicenseDocument: (id: number, file: File) =>
    upload<LicenseDocument>(`/licenses/${id}/documents`, file),
  documentUrl: (licenseId: number, docId: number) =>
    `/api/licenses/${licenseId}/documents/${docId}/file`,
  createGame: (data: { name: string; publisher?: string }) =>
    request<{ id: number; name: string; slug: string }>("/games", {
      method: "POST",
      body: json(data),
    }),
  policies: () => request<PublisherPolicy[]>("/policies"),
  setPolicy: (
    gameId: number,
    data: { status: PolicyStatus; notes: string; publisher?: string; policy_url?: string },
  ) => request<PublisherPolicy>(`/games/${gameId}/policy`, { method: "PUT", body: json(data) }),
  materials: (status?: MaterialStatus) =>
    request<Material[]>(`/materials${status ? `?status=${status}` : ""}`),
  material: (id: number) => request<Material>(`/materials/${id}`),
  registerMaterial: (data: {
    source_id: number;
    license_id: number;
    game_id: number | null;
    title?: string;
    storage_uri: string;
    sha256: string;
  }) => request<Material>("/materials", { method: "POST", body: json(data) }),
  uploadMaterial: (
    file: File,
    data: { source_id: number; license_id: number; game_id: number | null; title?: string },
  ) => {
    const fields: Record<string, string> = {
      source_id: String(data.source_id),
      license_id: String(data.license_id),
    };
    if (data.game_id !== null) fields.game_id = String(data.game_id);
    if (data.title) fields.title = data.title;
    return upload<Material>("/materials/upload", file, fields);
  },
  rightsCriteria: () => request<{ key: string; label: string }[]>("/rights/criteria"),

  // video production (Phase 7)
  productionClips: (limit = 50) => request<Clip[]>(`/production/clips?limit=${limit}`),
  materialScenes: (id: number) => request<Scene[]>(`/materials/${id}/scenes`),
  clipFileUrl: (id: number) => `/api/clips/${id}/file`,
  renderCapacity: () => request<RenderCapacity>("/production/capacity"),

  users: () => request<User[]>("/users"),
  createUser: (data: { email: string; password: string; role: UserRole; display_name?: string }) =>
    request<User>("/users", { method: "POST", body: json(data) }),
  updateUser: (
    id: number,
    data: Partial<{ role: UserRole; is_active: boolean; display_name: string; password: string }>,
  ) => request<User>(`/users/${id}`, { method: "PATCH", body: json(data) }),
};
