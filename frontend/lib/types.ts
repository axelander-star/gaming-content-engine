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
  /** Last transfer of the prepared profile to YouTube (description, keywords, banner). */
  profile_sync: ProfileSync | null;
}

export interface ProfileSync {
  ok: boolean;
  /** What YouTube accepted, e.g. "Banner", "Beschreibung", "Stichwörter". */
  applied: string[];
  /** What the platform has no interface for and the operator does by hand. */
  manual: string[];
  error: string | null;
  at: string;
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
  | "other_licensed"
  | "campaign";
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

/** Ausbau A7: hook A/B tests and winner recycling. */
export interface HookTestEntry {
  variant_id: number;
  post_id: number;
  label: string;
  hook_type: string | null;
  score: number;
  title: string | null;
}

export interface HookTest {
  channel_id: number;
  channel: string;
  clip_id: number;
  entries: HookTestEntry[];
  winner_variant_id: number | null;
  winner_hook: string | null;
}

export interface HookBalance {
  hook_type: string;
  label: string;
  tests: number;
  wins: number;
  losses: number;
  draws: number;
  median_score: number | null;
}

export interface WinnerPost {
  post_id: number;
  variant_id: number;
  title: string | null;
  channel: string;
  score: number;
  hook_type: string | null;
  published_at: string;
  recycled_variant_id: number | null;
  new_hook: string | null;
}

export interface HookReport {
  tests: HookTest[];
  balance: HookBalance[];
  winners: WinnerPost[];
  winner_score: number;
  recycle_after_days: number;
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

export type FixedCostCategory = "server" | "domain" | "subscription" | "storage" | "backup" | "other";

export interface FixedCostInput {
  name: string;
  provider: string | null;
  category: FixedCostCategory;
  amount: string;
  currency: "EUR" | "USD";
  interval: "month" | "year";
  in_budget: boolean;
  is_active: boolean;
  note: string | null;
}

export interface FixedCost extends Omit<FixedCostInput, "amount"> {
  id: number;
  amount: number;
  monthly_eur: number;
  missing_price: boolean;
  updated_at: string | null;
}

export interface AIUsageWindow {
  calls: number;
  live_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_tokens: number;
  cost_usd: number;
  last_call_at: string | null;
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
  as_of: string;
  costs: Record<
    | "fixed"
    | "fixed_in_budget"
    | "storage"
    | "ai"
    | "tts"
    | "api"
    | "other"
    | "total"
    | "accrued"
    | "today",
    number
  >;
  fixed: { items: FixedCost[]; from_env: boolean };
  ai: { today: AIUsageWindow; month: AIUsageWindow; eur_per_usd: number };
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

export interface TopicSuggestion {
  name: string;
  description: string;
  subtopics: string[];
  audience: string;
  tone: string;
  /** Why now, in plain words. */
  reason: string;
  /** The numbers behind it (YouTube charts, Wikipedia). */
  facts: string[];
  examples: string[];
  score: number;
}

export interface TopicSuggestions {
  live: boolean;
  /** Invented example numbers (development without live data). */
  sample: boolean;
  suggestions: TopicSuggestion[];
  sources: string[];
  /** What is missing for real data, e.g. the YouTube key. */
  hint: string | null;
  errors: string[];
  generated_at: string;
  provider: string;
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

export interface ChatAttachment {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  pages: number | null;
  width: number | null;
  height: number | null;
  has_text: boolean;
}

export interface ChatMessage {
  id: number;
  created_at: string;
  role: "user" | "assistant";
  text: string;
  provider: string | null;
  actions: ChatAction[];
  attachments: ChatAttachment[];
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

// --- research and idea lab (E5) ---

export type IdeaStatus = "new" | "accepted" | "rejected";

export interface ResearchSource {
  id: number;
  content_project_id: number;
  project: string;
  name: string;
  url: string;
  enabled: boolean;
  last_fetched_at: string | null;
  last_status: string | null;
  last_error: string | null;
  last_item_count: number;
  items: number;
}

export interface ResearchSources {
  mode: "mock" | "live";
  sources: ResearchSource[];
}

export type ResearchStepState = "queued" | "running" | "done" | "failed" | "skipped";

export interface ResearchRunStatus {
  state: "idle" | "running" | "done" | "stuck";
  started_at: string | null;
  finished_at: string | null;
  project_id: number | null;
  steps: { agent: string; state: ResearchStepState; detail: string | null }[];
  new_items: number;
  new_ideas: number;
}

export interface ResearchItem {
  id: number;
  content_project_id: number;
  source: string | null;
  title: string;
  url: string | null;
  summary: string | null;
  published_at: string | null;
  fetched_at: string;
  is_mock: boolean;
  used: boolean;
}

export type IdeaSort = "score" | "trend" | "fit" | "title" | "newest" | "oldest";

export interface IdeaPage {
  total: number;
  offset: number;
  limit: number;
  sort: IdeaSort;
  items: Idea[];
}

export interface Idea {
  id: number;
  created_at: string;
  content_project_id: number;
  project: string;
  title: string;
  pitch: string;
  format: string;
  sources: { item_id: number | null; title: string; url: string | null }[];
  trend_score: number;
  fit_score: number;
  effort_score: number;
  rights_risk: number;
  score: number;
  reasoning: string;
  status: IdeaStatus;
  provider: string;
  planned_for: string | null;
  decided_at: string | null;
}

// --- editorial calendar (E6) ---

export interface CalendarEntry {
  id: number;
  project_id: number;
  project: string;
  note: string | null;
  from_rule: boolean;
}

export interface Occasion {
  day: string;
  name: string;
  kind: "holiday" | "occasion" | "own";
  languages: string[];
  lead_days: number;
  id: number | null;
  project_id: number | null;
  note: string | null;
  ends_on: string | null;
}

export interface PlanRule {
  id: number;
  project_id: number;
  project: string;
  weekday: number;
  every_weeks: number;
  label: string;
  starts_on: string;
  note: string | null;
  skipped: number;
}

export interface CalendarVideo {
  job_id: number;
  variant_id: number;
  title: string;
  channel: string;
  project_id: number;
  at: string;
  status: "scheduled" | "running" | "succeeded" | "failed" | "cancelled";
  is_mock: boolean;
}

export interface CalendarDay {
  day: string;
  weekday: string;
  is_today: boolean;
  entries: CalendarEntry[];
  videos: CalendarVideo[];
  events: Occasion[];
}

export interface CalendarFocus {
  id: number;
  project_id: number;
  project: string;
  topic: string;
  starts_on: string;
  ends_on: string;
  note: string | null;
}

export interface Calendar {
  start: string;
  end: string;
  today: string;
  days: CalendarDay[];
  focus: CalendarFocus[];
}

// --- Media library and own production (extension E7) --------------------------------

export type LibraryKind = "video" | "image" | "audio";
export type LibraryOrigin = "upload" | "generated";
export type LibraryStatus = "processing" | "ready" | "failed";

export interface LibraryItem {
  id: number;
  project_id: number;
  project: string;
  kind: LibraryKind;
  origin: LibraryOrigin;
  status: LibraryStatus;
  title: string;
  filename: string | null;
  content_type: string;
  size_bytes: number;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
  orientation: "portrait" | "landscape" | "square" | null;
  has_rendition: boolean;
  has_thumb: boolean;
  rendition: Record<string, unknown>;
  render_seconds: number | null;
  rights: Record<string, unknown>;
  tags: string[];
  note: string | null;
  error_message: string | null;
  archived: boolean;
  /** false once the original was removed after the retention period */
  has_original: boolean;
  original_deleted_at: string | null;
  created_at: string;
  /** A6: the long video this short was cut from */
  parent_item_id: number | null;
  /** A6: splitting into shorts: queued | running | done | failed */
  split_state: string | null;
  split_info: {
    count?: number;
    length_s?: number;
    made?: { item_id: number }[];
    error?: string | null;
  };
  /** why it cannot be split; null = can be split */
  split_problem: string | null;
  split_suggestion: { count: number; length_s: number } | null;
}

export interface LibraryInfo {
  rights_statement: string;
  allowed_types: Record<string, string>;
  max_rendition_s: number;
  /** originals of uploaded videos are deleted after this many days (0 = never) */
  original_retention_days: number;
}

export type ProductionStatus = "draft" | "queued" | "rendering" | "done" | "failed";

export interface ProductionSegment {
  headline: string;
  text: string;
  image_item_id: number | null;
}

export interface Production {
  id: number;
  project_id: number;
  project: string;
  idea_id: number | null;
  title: string;
  language: Language;
  status: ProductionStatus;
  segments: ProductionSegment[];
  script_source: string;
  voice_provider: string | null;
  duration_s: number | null;
  render_seconds: number | null;
  result: {
    cues?: number;
    subtitle_issues?: string[];
    realtime_factor?: number;
    ffmpeg_seconds?: number;
    size_bytes?: number;
    voice?: { provider: string; voice_id: string; spoken_s: number };
    timeline?: { start_s: number; voice_end_s: number; end_s: number }[];
  };
  output_item_id: number | null;
  error_message: string | null;
  created_at: string;
  rendered_at: string | null;
  series_id?: number | null;
  series_part?: number | null;
}

/** One post of a series part on a channel. */
export interface SeriesPartPost {
  channel_id: number;
  channel: string;
  variant_id: number;
  status: VideoStatus;
}

export interface SeriesPart {
  part: number;
  production: Production;
  posts: SeriesPartPost[];
}

/** A big topic split into many short parts, produced up front and released over days. */
export interface Series {
  id: number;
  project_id: number;
  project: string;
  idea_id: number | null;
  title: string;
  topic: string;
  pitch: string | null;
  language: Language;
  part_seconds: number;
  outline: { title: string; summary: string }[];
  script_source: string;
  paused: boolean;
  created_at: string;
  counts: {
    parts: number;
    scripted: number;
    rendering: number;
    done: number;
    failed: number;
    prepared: number;
    approved: number;
    scheduled: number;
    published: number;
  };
  parts: SeriesPart[];
}

export interface SeriesInput {
  project_id: number;
  topic?: string | null;
  pitch?: string | null;
  idea_id?: number | null;
  language: Language;
  parts?: number | null;
  total_minutes?: number | null;
  part_seconds: number;
}

export interface SeriesSuggestion {
  title: string;
  pitch: string;
  parts: number;
  reason: string;
  source: string | null;
  idea_id: number | null;
}

export interface SeriesPlanDay {
  day: string;
  parts: number[];
  reasons: string[];
  fixed: boolean;
}

export interface SeriesChannelPlan {
  channel_id: number;
  channel: string;
  platform: string;
  days: SeriesPlanDay[];
}

export interface ProductionInput {
  project_id: number;
  title?: string | null;
  topic?: string | null;
  idea_id?: number | null;
  language?: Language;
  segments?: ProductionSegment[] | null;
}

// --- approval center (extension E8) ---

export interface ApprovalPlatform {
  code: PlatformCode;
  title_max: number;
  caption_max: number;
  hashtags_max: number;
  max_duration_s: number;
  vertical: boolean;
  defaults: Record<string, unknown>;
}

export interface ApprovalInfo {
  publishing_mode: "mock" | "live";
  platforms: ApprovalPlatform[];
  youtube_privacy: string[];
  youtube_formats: string[];
  tiktok_modes: string[];
  twitch_note: string;
}

export interface ApprovalCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ApprovalPost {
  id: number;
  status: VideoStatus;
  project_id: number;
  project: string;
  item_id: number;
  item_title: string;
  channel_id: number;
  channel: string;
  platform: PlatformCode;
  language: Language;
  title: string;
  description: string;
  hashtags: string[];
  options: Record<string, unknown>;
  caption: string;
  quality_score: number | null;
  checks: ApprovalCheck[];
  problems: string[];
  scheduled_for: string | null;
  published_url: string | null;
  published_mock: boolean | null;
  updated_at: string | null;
}

export interface PostTexts {
  title: string;
  description: string;
  hashtags: string[];
}

export interface PostTextsInput extends PostTexts {
  options?: Record<string, unknown>;
}

export interface PostChanges {
  title?: string;
  description?: string;
  hashtags?: string[];
  options?: Record<string, unknown>;
}

// --- Clipping campaigns (Content Rewards) -------------------------------------

export type CampaignStatus = "active" | "paused" | "ended";

export interface CampaignFields {
  name?: string;
  url?: string;
  game_id?: number | null;
  cpm_usd?: number | null;
  budget_usd?: number | null;
  min_views?: number | null;
  max_payout_per_clip_usd?: number | null;
  platforms?: PlatformCode[];
  languages?: Language[];
  channel_ids?: number[];
  required_hashtags?: string[];
  disclosure?: string | null;
  required_text?: string | null;
  min_duration_s?: number | null;
  max_duration_s?: number | null;
  submission_window_min?: number;
  ends_on?: string | null;
  brief?: string | null;
  material_links?: string[];
}

export interface CampaignInput extends CampaignFields {
  content_project_id: number;
  name: string;
  url: string;
  platforms: PlatformCode[];
  languages: Language[];
  channel_ids: number[];
  /** The brief allows edited, monetized short clips of the material (with its music). */
  rights_confirmed: boolean;
}

export interface Campaign {
  id: number;
  content_project_id: number;
  project: string;
  source_id: number;
  license_id: number;
  game_id: number | null;
  provider: string;
  name: string;
  url: string;
  status: CampaignStatus;
  cpm_usd: number | null;
  budget_usd: number | null;
  min_views: number | null;
  max_payout_per_clip_usd: number | null;
  platforms: PlatformCode[];
  languages: Language[];
  channel_ids: number[];
  channels: string[];
  required_hashtags: string[];
  disclosure: string | null;
  required_text: string | null;
  min_duration_s: number | null;
  max_duration_s: number | null;
  submission_window_min: number;
  ends_on: string | null;
  brief: string | null;
  material_links: string[];
  materials: number;
  clips_waiting: number;
  submissions_open: number;
  submissions_done: number;
  next_step: string;
  proposals: CampaignProposal[];
  proposals_at: string | null;
  proposals_source: string | null;
  created_at: string;
}

export interface CampaignProposal {
  title: string;
  hook: string;
  scenes: string[];
  on_screen_text: string[];
  caption: string;
  length_s: number;
  why: string;
  facts: string[];
}

/** Form fields read from a pasted campaign page (nothing is saved). */
export interface CampaignParseFields {
  name: string | null;
  url: string | null;
  cpm_usd: number | null;
  budget_usd: number | null;
  max_payout_per_clip_usd: number | null;
  min_views: number | null;
  platforms: string[];
  languages: string[];
  required_hashtags: string[];
  disclosure: string | null;
  required_text: string | null;
  min_duration_s: number | null;
  max_duration_s: number | null;
  ends_on: string | null;
  material_links: string[];
  game_id: number | null;
  brief: string | null;
}

export interface CampaignParseResult {
  fields: CampaignParseFields;
  found: string[];
  missing: string[];
  source: string;
  game: string | null;
}

export interface CampaignClip {
  id: number;
  campaign_id: number;
  campaign: string;
  status: VideoStatus;
  channel_id: number;
  channel: string;
  platform: PlatformCode;
  language: Language;
  title: string;
  description: string;
  hashtags: string[];
  caption: string;
  duration_s: number | null;
  quality_score: number | null;
  checks: { name: string; passed: boolean; detail: string }[];
  problems: string[];
  scheduled_for: string | null;
}

export type SubmissionState = "open" | "overdue" | "needs_link" | "submitted" | "skipped";

export interface CampaignSubmission {
  id: number;
  campaign_id: number;
  campaign: string;
  campaign_url: string;
  channel_id: number;
  channel: string;
  platform: PlatformCode;
  title: string;
  post_url: string | null;
  is_mock: boolean;
  posted_at: string | null;
  deadline_at: string | null;
  state: SubmissionState;
  seconds_left: number | null;
  late: boolean;
  submitted_at: string | null;
  note: string | null;
}

// --- channel assistant ---------------------------------------------------------------

export type SlotState = "connected" | "added" | "placeholder" | "prepared" | "missing";
export type ChannelSetupStatus = "open" | "done" | "dismissed";
export type MailAliasStatus = "not_needed" | "mock" | "created" | "failed";

export interface CoverageSlot {
  platform: PlatformCode;
  language: Language;
  state: SlotState;
  channel_id: number | null;
  channel_name: string | null;
  task_id: number | null;
}

export interface ProjectCoverage {
  project_id: number;
  project: string;
  project_status: "active" | "paused" | "archived";
  slots: CoverageSlot[];
  missing: number;
}

export interface ChannelSetupTask {
  id: number;
  content_project_id: number;
  content_project: string;
  platform: PlatformCode;
  platform_label: string;
  language: Language;
  status: ChannelSetupStatus;
  display_name: string;
  handle: string;
  alt_handles: string[];
  handle_check: Record<string, "free" | "taken" | "unknown">;
  bio: string;
  bio_max: number;
  email: string | null;
  email_status: MailAliasStatus;
  email_error: string | null;
  has_avatar: boolean;
  has_banner: boolean;
  signup_url: string;
  steps: string[];
  text_source: string;
  name_options: { name: string; reason: string }[];
  research_facts: string[];
  research_live: boolean;
  researched_at: string | null;
  channel_id: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface MailRoutingStatus {
  mode: "mock" | "live";
  domain: string;
  forward_to_set: boolean;
  problem: string | null;
}

export interface MailRoutingCheck {
  ok: boolean;
  mode: "mock" | "live";
  enabled: boolean | null;
  status: string | null;
  rules_used: number | null;
  rule_limit: number;
  findings: string[];
}

export interface AliasTestMail {
  status: "sent" | "mock" | "failed";
  to: string;
  message: string;
}

export interface ChannelSetupPatch {
  display_name?: string;
  handle?: string;
  bio?: string;
}

// --- account overview (A2) -------------------------------------------------------------

export type AccountStatus =
  | "setup"
  | "paused"
  | "new"
  | "growing"
  | "stable"
  | "declining"
  | "idle"
  | "pause_suggested";
export type RevenueSource = "youtube" | "content_rewards" | "affiliate" | "sponsor" | "other";

export interface AccountRow {
  channel_id: number;
  name: string;
  platform: PlatformCode;
  language: Language;
  project_id: number;
  project: string;
  auth_status: ChannelAuthStatus;
  is_paused: boolean;
  handle: string | null;
  first_post_at: string | null;
  last_post_at: string | null;
  total_posts: number;
  posts_30d: number;
  views_30d: number;
  views_prev_30d: number;
  followers_30d: number;
  engagement_30d: number | null;
  trend_30d: number | null;
  views_per_post: number | null;
  revenue_30d: string;
  revenue_review: string;
  revenue_by_source: Partial<Record<RevenueSource, string>>;
  estimate_30d: string;
  status: AccountStatus;
  status_label: string;
  reasons: string[];
}

export interface AccountSummary {
  channels: number;
  connected: number;
  views_30d: number;
  views_prev_30d: number;
  followers_30d: number;
  revenue_30d: string;
  estimate_30d: string;
  by_status: Partial<Record<AccountStatus, number>>;
  projects: {
    project_id: number;
    project: string;
    channels: number;
    views_30d: number;
    revenue_30d: string;
    estimate_30d: string;
  }[];
  top_revenue: number[];
  review_days: number;
}

export interface AccountsOverview {
  summary: AccountSummary;
  accounts: AccountRow[];
}

export interface RevenueEntry {
  id: number;
  channel_id: number;
  source: RevenueSource;
  amount_eur: string;
  period_start: string;
  period_end: string;
  note: string | null;
  created_at: string;
}

export interface RevenueInput {
  channel_id: number;
  source: RevenueSource;
  amount_eur: string;
  period_start: string;
  period_end: string;
  note?: string;
}

// --- comments (A3) ---------------------------------------------------------------------

export type CommentStatus = "new" | "review" | "ready" | "sent" | "ignored" | "failed";
export type CommentKind = "question" | "praise" | "criticism" | "sensitive" | "spam" | "other";

export interface ViewerComment {
  id: number;
  channel_id: number;
  channel: string;
  platform: PlatformCode;
  post_title: string | null;
  post_url: string | null;
  author: string | null;
  text: string;
  like_count: number | null;
  written_at: string | null;
  kind: CommentKind;
  status: CommentStatus;
  review_reason: string | null;
  reply_text: string | null;
  reply_source: string | null;
  reply_is_mock: boolean;
  replied_at: string | null;
  error: string | null;
  is_test: boolean;
  can_send: boolean;
}

export interface CommentStats {
  by_status: Partial<Record<CommentStatus, number>>;
  auto_reply: boolean;
  live: boolean;
}

// --- notifications and push (A4) ---

export type NotificationLevel = "info" | "warning" | "error" | "critical";

export interface AppNotification {
  id: number;
  created_at: string;
  level: NotificationLevel;
  kind: string | null;
  title: string;
  body: string | null;
  link: string | null;
  read: boolean;
  push_state: string | null;
}

export interface NotificationList {
  unread: number;
  items: AppNotification[];
}

export interface PushSettings {
  mode: "mock" | "live";
  configured: boolean;
  min_level: NotificationLevel;
  quiet_start: number;
  quiet_end: number;
  timezone: string;
}

// --- competitor radar (A5) ---

export interface CompetitorChannel {
  id: number;
  project_id: number;
  project: string;
  handle: string;
  name: string | null;
  url: string;
  last_checked_at: string | null;
  last_error: string | null;
  videos: number;
  standouts: number;
}

export interface CompetitorVideo {
  id: number;
  competitor_id: number;
  channel: string;
  project_id: number;
  title: string;
  url: string | null;
  published_at: string | null;
  views: number;
  likes: number | null;
  comments: number | null;
  outlier: number | null;
  is_mock: boolean;
  in_idea_lab: boolean;
}

export interface CompetitorRadar {
  live: boolean;
  competitors: CompetitorChannel[];
  standouts: CompetitorVideo[];
}

// --- Ausbau A8: bio-link pages, affiliate links, newsletter, campaign fit ---

export interface BioLinkItem {
  title: string;
  url: string;
}

export interface BioPage {
  id: number;
  channel_id: number;
  channel: string;
  platform: string;
  language: string;
  project_id: number;
  project: string;
  slug: string;
  enabled: boolean;
  headline: string;
  intro: string | null;
  links: BioLinkItem[];
  show_videos: boolean;
  newsletter_enabled: boolean;
  views: number;
  public_url: string | null;
  preview_path: string;
  subscribers: number;
}

export type BioPagePatch = Partial<
  Pick<BioPage, "slug" | "enabled" | "headline" | "intro" | "links" | "show_videos" | "newsletter_enabled">
>;

export interface AffiliateLink {
  id: number;
  project_id: number;
  project: string;
  title: string;
  url: string;
  program: string | null;
  language: string | null;
  keywords: string[];
  in_posts: boolean;
  active: boolean;
  clicks: number;
  note: string | null;
}

export interface AffiliateInput {
  project_id: number;
  title: string;
  url: string;
  program?: string | null;
  language?: string | null;
  keywords?: string[];
  in_posts?: boolean;
  active?: boolean;
  note?: string | null;
}

export interface NewsletterSubscriber {
  id: number;
  project_id: number;
  channel_id: number | null;
  email: string;
  language: string;
  status: "pending" | "confirmed" | "unsubscribed";
  created_at: string;
  confirmed_at: string | null;
}

export interface NewsletterOverview {
  confirmed: number;
  pending: number;
  unsubscribed: number;
  subscribers: NewsletterSubscriber[];
}

export interface OutgoingMail {
  id: number;
  to_address: string;
  subject: string;
  body_text: string;
  kind: string;
  status: "mock" | "sent" | "failed";
  error: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface Outbox {
  mode: "mock" | "smtp";
  problem: string | null;
  mails: OutgoingMail[];
}

export interface CampaignMatchInput {
  name: string;
  brief?: string | null;
  game?: string | null;
  platforms: string[];
  languages: string[];
  cpm_usd?: number | null;
  min_views?: number | null;
  max_payout_per_clip_usd?: number | null;
}

export interface CampaignFit {
  project_id: number;
  project: string;
  score: number;
  reasons: string[];
  channels: { id: number; name: string; platform: string; language: string }[];
  median_views: number | null;
  usd_per_clip: number | null;
}

// --- Ausbau A9: sponsor inbox ---

export type SponsorStatus = "new" | "replied" | "won" | "declined" | "archived";

export interface SponsorInquiry {
  id: number;
  project_id: number | null;
  project: string | null;
  brand: string;
  contact_email: string | null;
  subject: string | null;
  body: string;
  received_at: string;
  language: string;
  category: "sponsoring" | "product_test" | "affiliate" | "other" | "spam";
  category_label: string;
  status: SponsorStatus;
  flags: string[];
  fit_score: number;
  price_eur: number | null;
  price_basis: {
    median_views?: number | null;
    low?: number;
    high?: number;
    bundle?: number;
    bundle_posts?: number;
    note?: string;
  };
  draft: string;
  draft_source: string;
  note: string | null;
}

export interface SponsorInbox {
  counts: Record<SponsorStatus, number>;
  inquiries: SponsorInquiry[];
}

export interface SponsorInput {
  sender: string;
  subject?: string | null;
  body: string;
  project_id?: number | null;
}

export type SponsorPatch = Partial<{
  status: SponsorStatus;
  project_id: number | null;
  draft: string;
  price_eur: number | null;
  note: string | null;
}>;

// --- Ausbau A10: weekly report ---

export interface WeeklyReport {
  subject: string;
  text: string;
  recipient: string | null;
  mode: "mock" | "smtp";
  problem: string | null;
  schedule: string;
  last_sent_at: string | null;
}

// --- Trend alarm (Ausbau A11) ---

export type TrendAlarmStatus =
  | "drafting"
  | "ready"
  | "approved"
  | "dismissed"
  | "expired"
  | "failed";

export interface TrendAlarmChannel {
  id: number;
  name: string;
  platform: string;
  language: string;
  project: string;
  is_paused: boolean;
  trend_autopilot: boolean;
}

export interface TrendAlarmInfo {
  mode: "mock" | "live";
  threshold: number;
  max_per_day: number;
  drafts: number;
  min_views: number;
  regions: string[];
  autopilot_enabled: boolean;
  autopilot_min_score: number;
  publishing_mode: string;
  push_mode: string;
  channels: TrendAlarmChannel[];
}

export interface TrendAlarmPost {
  variant_id: number;
  channel: string;
  platform: string;
  status: string;
}

export interface TrendAlarmDraft {
  angle: string | null;
  production_id: number;
  title: string | null;
  status: string | null;
  item_id: number | null;
  duration_s: number | null;
  error: string | null;
  posts: TrendAlarmPost[];
}

export interface TrendAlarm {
  id: number;
  created_at: string;
  content_project_id: number;
  project: string;
  source: string;
  title: string;
  url: string | null;
  creator: string | null;
  published_at: string | null;
  metrics: Record<string, unknown>;
  score: number;
  facts: string[];
  status: TrendAlarmStatus;
  autopilot: boolean;
  approved_production_id: number | null;
  decided_at: string | null;
  error: string | null;
  is_mock: boolean;
  drafts: TrendAlarmDraft[];
}
