import type { ChannelAuthStatus, PlatformCode } from "./types";

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
