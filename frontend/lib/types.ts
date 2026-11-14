// Types mirroring the backend response schemas (backend/api/*.py).

export type UserRole = "admin" | "operator" | "viewer";
export type Language = "de" | "en";
export type PlatformCode = "youtube" | "tiktok" | "instagram" | "facebook";
export type ChannelAuthStatus = "not_connected" | "connected_restricted" | "authorized" | "expired";

export interface User {
  id: number;
  email: string;
  display_name: string | null;
  role: UserRole;
  is_active: boolean;
  last_login_at: string | null;
}

export interface EffectiveControls {
  emergency_stop: boolean;
  auto_publish_enabled: boolean;
  publishing_mode: "mock" | "live";
  publishing_allowed: boolean;
  paid_api_calls_enabled: boolean;
  env_auto_publish_enabled: boolean;
  env_emergency_stop: boolean;
}

export interface OperationsSettings {
  monthly_budget_eur: number;
  max_daily_production_jobs: number;
  max_parallel_render_jobs: number;
  min_quality_score: number;
  min_publish_interval_minutes: number;
  languages: Language[];
  platforms: PlatformCode[];
  ai_provider: string;
  tts_provider: string;
  notifications_enabled: boolean;
}

export interface SettingsResponse {
  controls: EffectiveControls;
  operations: OperationsSettings;
}

export interface Channel {
  id: number;
  name: string;
  language: Language;
  platform: PlatformCode;
  auth_status: ChannelAuthStatus;
  is_paused: boolean;
  min_posts_per_day: number;
  max_posts_per_day: number;
  min_interval_minutes: number;
}

export interface Overview {
  published_videos: number;
  videos_in_production: number;
  videos_in_quality_check: number;
  videos_ready_to_publish: number;
  videos_failed: number;
  channels_total: number;
  channels_active: number;
  controls: EffectiveControls;
}

export interface Readiness {
  status: "ok" | "degraded";
  database: boolean;
  redis: boolean;
}
