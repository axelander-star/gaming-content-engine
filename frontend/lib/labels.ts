import type {
  Agent,
  AgentRunStatus,
  AgentStatus,
  BudgetLevel,
  ChannelAuthStatus,
  PlatformCode,
} from "./types";

export const PLATFORM_LABELS: Record<PlatformCode, string> = {
  youtube: "YouTube Shorts",
  tiktok: "TikTok",
  instagram: "Instagram Reels",
  facebook: "Facebook Reels",
};

export const AUTH_STATUS_LABELS: Record<ChannelAuthStatus, string> = {
  not_connected: "Nicht verbunden",
  connected_restricted: "Eingeschränkt",
  authorized: "Autorisiert",
  expired: "Abgelaufen",
};

export function formatDateTime(iso: string | null): string {
  if (!iso) return "–";
  return new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(
    new Date(iso),
  );
}

export const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  not_available: "Folgt in Phase",
  stopped: "Not-Aus",
  paused: "Pausiert",
  running: "Läuft",
  error: "Fehler",
  ready: "Bereit",
};

export const RUN_STATUS_LABELS: Record<AgentRunStatus, string> = {
  running: "Läuft",
  succeeded: "Erfolgreich",
  failed: "Fehlgeschlagen",
  skipped: "Übersprungen",
};

export const COST_KIND_LABELS: Record<Agent["cost_kind"], string> = {
  local: "Lokal",
  free_api: "Kostenlose API",
  paid: "Kostenpflichtig",
};

export const BUDGET_LEVEL_LABELS: Record<BudgetLevel, string> = {
  normal: "Normal",
  warn: "Warnung",
  reduced: "Reduziert",
  priority_only: "Nur Priorität",
  stop_paid: "Kostenpflichtig gestoppt",
};

export function formatEur(value: string | number): string {
  return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(
    Number(value),
  );
}
