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

// --- Agents (Phase 4) ---------------------------------------------------------

export type AgentStatus = "not_available" | "stopped" | "paused" | "running" | "error" | "ready";
export type AgentRunStatus = "running" | "succeeded" | "failed" | "skipped";
export type BudgetLevel = "normal" | "warn" | "reduced" | "priority_only" | "stop_paid";

export interface Agent {
  name: string;
  number: number;
  title: string;
  description: string;
  phase: number;
  cost_kind: "local" | "free_api" | "paid";
  stage: string | null;
  implemented: boolean;
  enabled: boolean;
  status: AgentStatus;
  can_run_manually: boolean;
  last_run_at: string | null;
  last_run_status: AgentRunStatus | null;
  last_error: string | null;
  current_task: Record<string, unknown> | null;
  runs_today: number;
  cost_month_eur: string;
}

export interface AgentRun {
  id: number;
  agent_name: string;
  status: AgentRunStatus;
  started_at: string;
  finished_at: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error: string | null;
  cost_eur: string;
}

export interface AgentDecision {
  id: number;
  agent_run_id: number | null;
  agent_name: string;
  decision_type: string;
  entity_type: string | null;
  entity_id: number | null;
  decision: Record<string, unknown>;
  reasoning: string | null;
  created_at: string;
}

export interface Budget {
  budget_eur: string;
  spent_eur: string;
  used_pct: number;
  level: BudgetLevel;
  paid_api_calls_enabled: boolean;
}
