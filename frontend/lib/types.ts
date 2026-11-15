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
  ai_monthly_cap_usd: number;
  creative_variants: number;
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
  /** Topic area; content of other projects is never published on this channel. */
  content_project_id: number;
  content_project: string;
  auth_status: ChannelAuthStatus;
  is_paused: boolean;
  min_posts_per_day: number;
  max_posts_per_day: number;
  min_interval_minutes: number;
  connected_account: string | null;
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

export type DashboardStateKey =
  | "draft"
  | "in_progress"
  | "ready"
  | "scheduled"
  | "uploading"
  | "published"
  | "failed";

export type PlatformConnection =
  | "not_connected"
  | "restricted"
  | "connected"
  | "expired"
  | "data_source_mock"
  | "data_source_ok"
  | "data_source_error";

export interface PlatformTile {
  code: PlatformCode | "twitch";
  name: string;
  can_publish: boolean;
  note: string;
  connection: PlatformConnection;
  channels: number;
  channels_connected: number;
  published: number;
  test_posts: number;
  last_published_at: string | null;
  open_jobs: number;
  failed_jobs: number;
}

export interface DashboardRecentPost {
  id: number;
  title: string | null;
  platform: PlatformCode;
  channel: string;
  content_project: string;
  published_at: string | null;
  url: string | null;
  is_mock: boolean;
}

export interface DashboardFailure {
  kind: "publishing" | "video";
  id: number;
  title: string | null;
  platform: PlatformCode | null;
  channel: string | null;
  error: string | null;
  at: string;
}

export interface DashboardActivity {
  at: string;
  kind: "audit" | "agent";
  action: string;
  actor: string | null;
  entity_type: string | null;
  entity_id: number | null;
  status_before: string | null;
  status_after: string | null;
  message: string | null;
}

export interface Dashboard {
  videos_total: number;
  published: number;
  scheduled: number;
  unpublished: number;
  failed: number;
  states: { key: DashboardStateKey; count: number }[];
  platforms: PlatformTile[];
  recent_posts: DashboardRecentPost[];
  failures: DashboardFailure[];
  activity: DashboardActivity[];
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

// --- Trends and games (Phase 5) ----------------------------------------------

export interface TrendItem {
  game_id: number;
  game: string;
  language: Language | null;
  score: number;
  growth_pct: number | null;
  components: Record<string, number>;
  unknown: string[];
  audience: string | null;
  audience_label: string;
  sources: string[];
  is_new: boolean;
  is_mock: boolean;
  detected_at: string;
  top_idea: string | null;
}

export interface TrendReport {
  id: number;
  language: Language;
  created_at: string;
  sources: string[];
  is_mock: boolean;
  summary: string;
  items: Record<string, unknown>[];
  by_audience: Record<string, { label: string; games: { game: string; score: number }[] }>;
}

export interface VideoIdea {
  format: string;
  format_label: string;
  title_de: string;
  title_en: string;
  mode: string | null;
  priority: "high" | "normal";
}

export interface Game {
  id: number;
  name: string;
  slug: string;
  categories: string[];
  publisher: string | null;
  steam_app_id: number | null;
  twitch_game_id: string | null;
  is_test_data: boolean;
  profiled_at: string | null;
  profile: {
    audience?: { key: string; de: string; en: string; secondary: string[] };
    modes?: string[];
    video_ideas?: VideoIdea[];
    rating?: number | null;
    rising?: boolean;
    rights_note?: string;
  };
}

// --- Rights management (Phase 6) ---------------------------------------------

export type SourceType =
  | "own_upload"
  | "licensed_creator"
  | "partner"
  | "contract"
  | "other_licensed";
export type LicenseStatus = "pending" | "approved" | "rejected" | "expired" | "revoked";
export type PolicyStatus = "permitted" | "license_required" | "forbidden";
export type MaterialStatus =
  | "DISCOVERED"
  | "RIGHTS_PENDING"
  | "RIGHTS_APPROVED"
  | "RIGHTS_REJECTED"
  | "ANALYZED"
  | "FAILED";
export type CheckOutcome = "ok" | "denied" | "missing";

export interface Creator {
  id: number;
  name: string;
  contact: string | null;
  notes: string | null;
  is_blocked: boolean;
}

export interface Source {
  id: number;
  creator_id: number | null;
  type: SourceType;
  name: string;
  url: string | null;
  provenance_notes: string | null;
  is_blocked: boolean;
}

export interface LicenseTerms {
  valid_from: string | null;
  valid_until: string | null;
  allows_commercial_use: boolean;
  allows_editing: boolean;
  allows_short_form: boolean;
  allows_monetization: boolean;
  music_cleared: boolean;
  allowed_platforms: string[];
  allowed_languages: string[];
  restrictions: string | null;
  publisher_permission: boolean;
}

export interface License extends LicenseTerms {
  id: number;
  source_id: number;
  status: LicenseStatus;
  document_uri: string | null;
  verified_by_user_id: number | null;
  verified_at: string | null;
  documents: number;
}

export interface LicenseDocument {
  id: number;
  license_id: number;
  version: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by_user_id: number | null;
  uploaded_at: string;
}

export interface PublisherPolicy {
  id: number;
  game_id: number;
  game: string;
  status: PolicyStatus;
  publisher: string | null;
  notes: string;
  policy_url: string | null;
  checked_at: string | null;
  checked_by_user_id: number | null;
}

export interface RightsCheckItem {
  key: string;
  label: string;
  outcome: CheckOutcome;
  reason: string;
}

export interface Material {
  id: number;
  title: string | null;
  status: MaterialStatus;
  game_id: number | null;
  game: string | null;
  content_project_id: number;
  content_project: string;
  source_id: number;
  source: string;
  license_id: number;
  storage_uri: string;
  duration_s: number | null;
  created_at: string;
  error_message: string | null;
  last_check: {
    id: number;
    checked_at: string;
    approved: boolean;
    checks: RightsCheckItem[];
    missing: string[];
    denied: string[];
  } | null;
}

// --- Trend sources and history (live integration) ----------------------------

export interface TrendSourceStatus {
  name: "youtube" | "twitch" | "steam";
  label: string;
  mode: "mock" | "live";
  configured: boolean;
  credentials: string[];
  quota_used: number;
  quota_limit: number;
  quota_unit: string;
  last: {
    state: "ok" | "partial" | "error" | "skipped" | "mock";
    mode: string;
    kind: "run" | "test";
    at: string;
    requests: number;
    observations: number;
    errors: string[];
    skipped: string | null;
    detail: string | null;
    last_ok_at: string | null;
  } | null;
}

export interface TrendHistoryPoint {
  detected_at: string;
  score: number;
  is_mock: boolean;
  metrics: Record<string, number>;
  growth_pct: Record<string, number>;
}

// --- Video production (Phase 7) ----------------------------------------------

export type VideoStatus =
  | "SCENE_SELECTED"
  | "EDITING"
  | "LOCALIZATION"
  | "VOICEOVER"
  | "SUBTITLES"
  | "QUALITY_CHECK"
  | "QUALITY_APPROVED"
  | "QUALITY_REJECTED"
  | "READY_TO_PUBLISH"
  | "SCHEDULED"
  | "PUBLISHED"
  | "ANALYTICS_PENDING"
  | "ANALYZED"
  | "ARCHIVED"
  | "FAILED";

export interface Scene {
  id: number;
  rank: number | null;
  start_s: number;
  end_s: number;
  score: number | null;
  scores: Record<string, number>;
  tags: string[];
  selected: boolean;
}

export interface ScriptBeat {
  kind: "hook" | "setup" | "buildup" | "payoff" | "cta";
  start_s: number;
  end_s: number;
  text: string;
}

export interface VariantScript {
  id: number;
  version: number;
  source: string;
  hook: string | null;
  voiceover_text: string | null;
  call_to_action: string | null;
  title: string | null;
  description: string | null;
  beats: ScriptBeat[];
}

export interface VariantConcept {
  video_format?: string;
  hook_type?: string;
  score?: number;
  components?: Record<string, number>;
  experiment?: boolean;
  reasons?: string[];
}

export interface VariantBrief {
  id: number;
  language: Language;
  label: string;
  status: VideoStatus;
  channel_id: number;
  error_message: string | null;
  video_format: string | null;
  hook_type: string | null;
  concept: VariantConcept;
  script: VariantScript | null;
  final_video: boolean;
  voice: {
    provider: string;
    voice_id: string | null;
    max_tempo: number;
    overflow: string[];
  } | null;
  subtitle_formats: string[];
  subtitle_issues: string[];
  quality: QualityResult | null;
}

/** One check of the quality control (Phase 10). */
export interface QualityCheckItem {
  name: string;
  passed: boolean;
  detail: string;
  blocking: boolean;
  penalty: number;
  values: Record<string, unknown>;
}

export interface QualityResult {
  passed: boolean;
  score: number | null;
  min_score: number | null;
  reasons: string[];
  checks: QualityCheckItem[];
  measured: { lufs?: number; true_peak?: number; black_s?: number; frozen_s?: number };
  checked_at: string;
}

export interface Clip {
  id: number;
  material_id: number;
  material_title: string | null;
  game: string | null;
  scene: Scene;
  start_s: number;
  end_s: number;
  rendered: boolean;
  width: number | null;
  height: number | null;
  fps: number | null;
  duration_s: number | null;
  size_bytes: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  layout: string | null;
  render_seconds: number | null;
  realtime_factor: number | null;
  rendered_at: string | null;
  variants: VariantBrief[];
}

export interface RenderCapacity {
  clips_rendered_7d: number;
  render_seconds_7d: number;
  clip_seconds_7d: number;
  realtime_factor: number | null;
  clips_per_hour_per_slot: number | null;
  parallel_slots: number;
  clips_per_hour: number | null;
  waiting_for_render: number;
}

/** Publishing strategy of a channel (Phase 11). */
export interface StrategyVersion {
  version: number;
  created_at: string;
  planned_for: string;
  posts_per_day: number;
  reasons: string[];
  inputs: {
    assessment?: {
      judged: number;
      waiting: number;
      recent: number[];
      recent_median: number | null;
      above_share: number | null;
    };
    supply?: { ready: number; approved_per_day: number; quality_recent: number | null };
    days_since_change?: number | null;
    rolled_back_from?: number;
  };
  params: { preferred_hours?: number[] | null; window?: number[]; interval_minutes?: number };
  created_by: string;
  rolled_back_to: number | null;
}

export type PublishingJobStatus =
  | "pending"
  | "scheduled"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "blocked";

export interface PlannedJob {
  id: number;
  variant_id: number;
  label: string;
  language: Language;
  title: string | null;
  status: PublishingJobStatus;
  mode: "mock" | "live";
  scheduled_for: string | null;
  note: string | null;
  external_id: string | null;
  url: string | null;
}

export interface ChannelPlan {
  channel_id: number;
  name: string;
  platform: string;
  language: Language;
  is_paused: boolean;
  auth_status: string;
  min_posts_per_day: number;
  max_posts_per_day: number;
  min_interval_minutes: number;
  timezone: string;
  window: number[];
  ready: number;
  current: StrategyVersion | null;
  history: StrategyVersion[];
  jobs: PlannedJob[];
}

// --- Analytics, Learning, Kosten (Phase 14) ---

export interface PerfSummary {
  posts: number;
  measured: number;
  views: number;
  median_views: number | null;
  engagement_rate: number | null;
  retention_pct: number | null;
  avg_view_duration_s: number | null;
  followers_gained: number;
}

export interface PerfGroup extends PerfSummary {
  key: string;
}

export interface PerfVideo {
  post_id: number;
  title: string | null;
  url: string | null;
  channel: string;
  game: string | null;
  format: string | null;
  views: number;
  window: string | null;
  is_mock: boolean;
}

export interface AnalyticsOverview {
  days: number;
  test_data: boolean;
  totals: PerfSummary;
  timeline: (PerfSummary & { day: string })[];
  groups: Record<string, PerfGroup[]>;
  top: PerfVideo[];
  weak: PerfVideo[];
  options: Record<string, string[]>;
}

export interface AnalyticsFilters {
  days: number;
  platform?: string;
  language?: string;
  game?: string;
  format?: string;
  hook?: string;
  hour?: string;
}

export interface LearningVersionOut {
  version: number;
  status: "trial" | "active" | "rolled_back" | "superseded";
  created_at: string;
  weights: Record<string, Record<string, number>>;
  reasons: string[];
  trial_until: string | null;
  evaluation: Record<string, unknown>;
  created_by: string;
  rolled_back_to: number | null;
  baseline: number | null;
}

export interface CostSummary {
  month: string;
  budget: {
    budget_eur: number;
    spent_eur: number;
    used_pct: number;
    level: string;
    thresholds: Record<string, number>;
  };
  costs: Record<
    "server" | "other_fixed" | "storage" | "ai" | "tts" | "api" | "other" | "total",
    number
  >;
  storage: { bytes: number; price_per_gb: number };
  videos: {
    produced: number;
    published: number;
    published_test: number;
    views: number;
    views_test: number;
  };
  unit_costs: {
    per_produced: number | null;
    per_published: number | null;
    per_1000_views: number | null;
  };
  api_usage_today: Record<string, number>;
  prices_configured: boolean;
}

// --- Phase 15: system status ---------------------------------------------------

export type CheckStatus = "ok" | "warn" | "critical" | "unknown";

export interface SystemCheck {
  key: string;
  label: string;
  status: CheckStatus;
  detail: string;
  value: number | null;
}

export interface ScalingAdvice {
  key: string;
  text: string;
  evidence: string;
}

export interface BackupInfo {
  file: string;
  created_at: string;
  size_bytes: number;
  rows: number;
}

export interface RestoreCheckInfo {
  file: string;
  checked_at: string;
  ok: boolean;
  duration_s: number;
  tables: number;
  rows: number;
  problems: string[];
}

export interface MonitorSample {
  ts: string;
  backlog: number;
  wait_s: number;
  load: number | null;
  mem_free_pct: number | null;
  disk_pct: number;
}

export interface SystemStatus {
  checked_at: string;
  status: CheckStatus;
  checks: SystemCheck[];
  scaling: ScalingAdvice[];
  samples: MonitorSample[];
  backup: {
    configured: boolean;
    count: number;
    total_bytes: number;
    age_hours: number | null;
    latest: BackupInfo | null;
    restore_check: RestoreCheckInfo | null;
    backups: BackupInfo[];
  };
}

// --- content projects (topic areas) ---------------------------------------------------

export type ContentProjectStatus = "active" | "paused" | "archived";

export interface ContentProject {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  languages: Language[];
  audience: string | null;
  tone: string | null;
  subtopics: string[];
  priority: number;
  status: ContentProjectStatus;
  is_default: boolean;
  channels: number;
  materials: number;
  videos: number;
  published: number;
  created_at: string;
}

export interface ContentProjectInput {
  name: string;
  description?: string | null;
  languages?: Language[];
  audience?: string | null;
  tone?: string | null;
  subtopics?: string[];
  priority?: number;
}

export interface ContentProjectPatch extends Partial<ContentProjectInput> {
  status?: ContentProjectStatus;
}

export interface ChannelInput {
  platform: PlatformCode;
  language: Language;
  name: string;
  content_project_id: number;
}

// --- AI layer (extension E3) -------------------------------------------------

export type AICallStatus = "reserved" | "succeeded" | "refused" | "failed" | "blocked";

export interface AIStatus {
  provider: string;
  live: boolean;
  reason: string | null;
  key_configured: boolean;
  paid_calls_enabled: boolean;
  cap_usd: string;
  cap_max_usd: string;
  spent_usd: string;
  reserved_usd: string;
  remaining_usd: string;
  used_pct: number;
  model_text: string;
  model_reasoning: string;
  prices: Record<string, { input: string; output: string }>;
  calls_this_month: number;
  blocked_this_month: number;
}

export interface AIUsageGroup {
  key: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
}

export interface AICall {
  id: number;
  created_at: string;
  purpose: string;
  tier: "text" | "reasoning";
  provider: string;
  model: string;
  status: AICallStatus;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  estimated_usd: string;
  duration_ms: number | null;
  error: string | null;
  content_project: string | null;
}

export interface AIUsage {
  by_purpose: AIUsageGroup[];
  by_model: AIUsageGroup[];
  recent: AICall[];
}

export interface AITestResult {
  text: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: string;
  call_id: number;
}

// --- chat assistant and editorial plan (E4) ---

export type ChatActionStatus = "done" | "undone" | "failed";

export interface ChatAction {
  id: number;
  created_at: string;
  tool: string;
  args: Record<string, unknown>;
  summary: string;
  status: ChatActionStatus;
  undoable: boolean;
  error: string | null;
  undone_at: string | null;
}

export interface ChatMessage {
  id: number;
  created_at: string;
  role: "user" | "assistant";
  text: string;
  provider: string | null;
  actions: ChatAction[];
}

export interface ChatExchange {
  question: ChatMessage;
  answer: ChatMessage;
}

export interface PlanProject {
  id: number;
  name: string;
  note: string | null;
}

export interface PlanDay {
  day: string;
  weekday: string;
  is_today: boolean;
  projects: PlanProject[];
}

export interface PlanFocus {
  id: number;
  project_id: number;
  project: string;
  topic: string;
  starts_on: string;
  ends_on: string;
}

export interface WeekPlan {
  start: string;
  end: string;
  today: string;
  days: PlanDay[];
  focus: PlanFocus[];
}
