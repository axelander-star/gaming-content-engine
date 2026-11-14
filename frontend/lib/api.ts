// Thin, typed client for the backend API.
// Sessions live in an HttpOnly cookie; state-changing requests send the
// CSRF token from the readable `gce_csrf` cookie as `X-CSRF-Token` header.

import type {
  Channel,
  EffectiveControls,
  OperationsSettings,
  Overview,
  Readiness,
  SettingsResponse,
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

export const api = {
  login: (email: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: json({ email, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),

  readiness: () => request<Readiness>("/health/ready"),
  overview: () => request<Overview>("/overview"),

  settings: () => request<SettingsResponse>("/settings"),
  updateControls: (changes: Partial<Pick<EffectiveControls, "emergency_stop" | "auto_publish_enabled">>) =>
    request<EffectiveControls>("/settings/controls", { method: "PATCH", body: json(changes) }),
  updateOperations: (changes: Partial<OperationsSettings>) =>
    request<OperationsSettings>("/settings/operations", { method: "PATCH", body: json(changes) }),

  channels: () => request<Channel[]>("/channels"),
  pauseChannel: (id: number) => request<Channel>(`/channels/${id}/pause`, { method: "POST" }),
  resumeChannel: (id: number) => request<Channel>(`/channels/${id}/resume`, { method: "POST" }),
  setChannelLimits: (
    id: number,
    limits: Pick<Channel, "min_posts_per_day" | "max_posts_per_day" | "min_interval_minutes">,
  ) => request<Channel>(`/channels/${id}/limits`, { method: "PUT", body: json(limits) }),

  users: () => request<User[]>("/users"),
  createUser: (data: { email: string; password: string; role: UserRole; display_name?: string }) =>
    request<User>("/users", { method: "POST", body: json(data) }),
  updateUser: (
    id: number,
    data: Partial<{ role: UserRole; is_active: boolean; display_name: string; password: string }>,
  ) => request<User>(`/users/${id}`, { method: "PATCH", body: json(data) }),
};
