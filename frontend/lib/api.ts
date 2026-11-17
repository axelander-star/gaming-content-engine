// Thin, typed client for the backend API.
// Sessions live in an HttpOnly cookie; state-changing requests send the
// CSRF token from the readable `gce_csrf` cookie as `X-CSRF-Token` header.

import type {
  Agent,
  CommentStats,
  CommentStatus,
  ViewerComment,
  AccountsOverview,
  RevenueEntry,
  RevenueInput,
  ChannelSetupPatch,
  ChannelSetupStatus,
  ChannelSetupTask,
  MailRoutingStatus,
  ProjectCoverage,
  ApprovalInfo,
  ApprovalPost,
  PostChanges,
  PostTexts,
  PostTextsInput,
  VideoStatus,
  AgentDecision,
  AgentRun,
  Budget,
  Campaign,
  CampaignClip,
  CampaignFields,
  CampaignInput,
  CampaignStatus,
  CampaignSubmission,
  Channel,
  ChannelInput,
  ContentProject,
  ContentProjectInput,
  ContentProjectPatch,
  AnalyticsFilters,
  AnalyticsOverview,
  ChannelPlan,
  CostSummary,
  HookReport,
  LearningVersionOut,
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
  Dashboard,
  AIStatus,
  AIUsage,
  AITestResult,
  Calendar,
  CalendarEntry,
  CalendarFocus,
  ChatAction,
  ChatAttachment,
  CompetitorChannel,
  SponsorInbox,
  SponsorInput,
  SponsorInquiry,
  SponsorPatch,
  SponsorStatus,
  AffiliateInput,
  AffiliateLink,
  BioPage,
  BioPagePatch,
  CampaignFit,
  CampaignMatchInput,
  NewsletterOverview,
  Outbox,
  CompetitorRadar,
  Idea,
  IdeaStatus,
  LibraryInfo,
  LibraryItem,
  LibraryKind,
  LibraryOrigin,
  LibraryStatus,
  NotificationList,
  Occasion,
  PlanRule,
  Production,
  PushSettings,
  ProductionInput,
  ProductionSegment,
  ResearchItem,
  ResearchSource,
  ResearchSources,
  ChatExchange,
  ChatMessage,
  WeekPlan,
  PolicyStatus,
  PublisherPolicy,
  Readiness,
  RenderCapacity,
  Scene,
  SettingsResponse,
  Source,
  SourceType,
  StrategyVersion,
  SystemStatus,
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
  dashboard: () => request<Dashboard>("/overview/dashboard"),

  aiStatus: () => request<AIStatus>("/ai/status"),
  aiUsage: (limit = 20) => request<AIUsage>(`/ai/usage?limit=${limit}`),
  aiTest: (prompt: string, tier: "text" | "reasoning") =>
    request<AITestResult>("/ai/test", { method: "POST", body: json({ prompt, tier }) }),

  chatMessages: (limit = 50) => request<ChatMessage[]>(`/assistant/messages?limit=${limit}`),
  sendChat: (text: string) =>
    request<ChatExchange>("/assistant/messages", { method: "POST", body: json({ text }) }),
  sendChatWithFiles: (text: string, attachmentIds: number[]) =>
    request<ChatExchange>("/assistant/messages", {
      method: "POST",
      body: json({ text, attachment_ids: attachmentIds }),
    }),
  uploadChatFile: (file: File) => upload<ChatAttachment>("/assistant/attachments", file),
  chatFileUrl: (id: number) => `/api/assistant/attachments/${id}/file`,
  /** Spoken answer: a Blob from the server voice, or null = let the browser speak. */
  chatSpeech: async (messageId: number): Promise<Blob | null> => {
    const res = await fetch(`/api/assistant/messages/${messageId}/speech`, {
      credentials: "same-origin",
    });
    if (res.status === 204) return null;
    if (!res.ok) {
      const body: unknown = await res.json().catch(() => null);
      throw new ApiError(res.status, errorMessage(body, res.status));
    }
    return res.blob();
  },
  notifications: (limit = 30) => request<NotificationList>(`/notifications?limit=${limit}`),
  markNotificationsRead: (ids?: number[]) =>
    request<{ marked: number; unread: number }>("/notifications/read", {
      method: "POST",
      body: json({ ids: ids ?? null }),
    }),
  pushSettings: () => request<PushSettings>("/notifications/push"),
  testPush: () => request<{ result: string }>("/notifications/push/test", { method: "POST" }),
  undoChatAction: (id: number) =>
    request<ChatAction>(`/assistant/actions/${id}/undo`, { method: "POST" }),
  weekPlan: (start?: string) =>
    request<WeekPlan>(`/planning/week${start ? `?start=${encodeURIComponent(start)}` : ""}`),

  researchSources: () => request<ResearchSources>("/research/sources"),
  createResearchSource: (body: { content_project_id: number; name: string; url: string }) =>
    request<ResearchSource>("/research/sources", { method: "POST", body: json(body) }),
  updateResearchSource: (id: number, changes: { name?: string; enabled?: boolean }) =>
    request<ResearchSource>(`/research/sources/${id}`, { method: "PATCH", body: json(changes) }),
  deleteResearchSource: (id: number) =>
    request<void>(`/research/sources/${id}`, { method: "DELETE" }),
  researchItems: (projectId?: number, limit = 30) =>
    request<ResearchItem[]>(
      `/research/items?limit=${limit}${projectId ? `&project_id=${projectId}` : ""}`,
    ),
  runResearch: (projectId?: number) =>
    request<{ jobs: Record<string, string> }>("/research/run", {
      method: "POST",
      body: json({ project_id: projectId ?? null, ideas: true }),
    }),
  ideas: (filters: { projectId?: number; status?: IdeaStatus } = {}) => {
    const q = new URLSearchParams({ limit: "100" });
    if (filters.projectId) q.set("project_id", String(filters.projectId));
    if (filters.status) q.set("status", filters.status);
    return request<Idea[]>(`/ideas?${q.toString()}`);
  },
  acceptIdea: (id: number, day: string | null) =>
    request<Idea>(`/ideas/${id}/accept`, { method: "POST", body: json({ day }) }),
  rejectIdea: (id: number) => request<Idea>(`/ideas/${id}/reject`, { method: "POST" }),
  reopenIdea: (id: number) => request<Idea>(`/ideas/${id}/reopen`, { method: "POST" }),

  calendar: (start: string, end: string, projectId?: number) =>
    request<Calendar>(
      `/planning/calendar?start=${start}&end=${end}${projectId ? `&project_id=${projectId}` : ""}`,
    ),
  addPlanDay: (body: { day: string; project_id: number; note?: string | null }) =>
    request<CalendarEntry>("/planning/days", { method: "POST", body: json(body) }),
  updatePlanDay: (id: number, changes: { day?: string; note?: string | null }) =>
    request<CalendarEntry>(`/planning/days/${id}`, { method: "PATCH", body: json(changes) }),
  deletePlanDay: (id: number) => request<void>(`/planning/days/${id}`, { method: "DELETE" }),
  addFocus: (body: {
    project_id: number;
    topic: string;
    starts_on: string;
    ends_on: string;
    note?: string | null;
  }) => request<CalendarFocus>("/planning/focus", { method: "POST", body: json(body) }),
  deleteFocus: (id: number) => request<void>(`/planning/focus/${id}`, { method: "DELETE" }),
  planRules: () => request<PlanRule[]>("/planning/rules"),
  addPlanRule: (body: { project_id: number; weekday: number; every_weeks?: number }) =>
    request<PlanRule>("/planning/rules", { method: "POST", body: json(body) }),
  deletePlanRule: (id: number) => request<void>(`/planning/rules/${id}`, { method: "DELETE" }),
  occasions: (start: string, end: string) =>
    request<Occasion[]>(`/planning/events?start=${start}&end=${end}`),
  addOccasion: (body: {
    name: string;
    day: string;
    languages: string[];
    project_id?: number | null;
  }) => request<Occasion>("/planning/events", { method: "POST", body: json(body) }),
  deleteOccasion: (id: number) => request<void>(`/planning/events/${id}`, { method: "DELETE" }),
  competitorRadar: (projectId?: number) =>
    request<CompetitorRadar>(`/competitors${projectId ? `?project_id=${projectId}` : ""}`),
  addCompetitor: (projectId: number, handle: string) =>
    request<CompetitorChannel>("/competitors", {
      method: "POST",
      body: json({ project_id: projectId, handle }),
    }),
  removeCompetitor: (id: number) => request<void>(`/competitors/${id}`, { method: "DELETE" }),
  runCompetitorRadar: () =>
    request<{ job_id: string | null }>("/competitors/run", { method: "POST" }),

  libraryInfo: () => request<LibraryInfo>("/library/info"),
  library: (
    filters: {
      projectId?: number;
      kind?: LibraryKind;
      origin?: LibraryOrigin;
      status?: LibraryStatus;
      archived?: boolean;
    } = {},
  ) => {
    const q = new URLSearchParams();
    if (filters.projectId) q.set("project_id", String(filters.projectId));
    if (filters.kind) q.set("kind", filters.kind);
    if (filters.origin) q.set("origin", filters.origin);
    if (filters.status) q.set("status", filters.status);
    if (filters.archived) q.set("archived", "true");
    return request<LibraryItem[]>(`/library?${q.toString()}`);
  },
  libraryItem: (id: number) => request<LibraryItem>(`/library/${id}`),
  updateLibraryItem: (id: number, changes: { title?: string; note?: string | null; tags?: string[] }) =>
    request<LibraryItem>(`/library/${id}`, { method: "PATCH", body: json(changes) }),
  archiveLibraryItem: (id: number) =>
    request<LibraryItem>(`/library/${id}/archive`, { method: "POST" }),
  restoreLibraryItem: (id: number) =>
    request<LibraryItem>(`/library/${id}/restore`, { method: "POST" }),
  splitLibraryItem: (id: number, count: number, lengthS: number) =>
    request<LibraryItem>(`/library/${id}/split`, {
      method: "POST",
      body: json({ count, length_s: lengthS }),
    }),
  reprocessLibraryItem: (id: number) =>
    request<LibraryItem>(`/library/${id}/reprocess`, { method: "POST" }),
  libraryFileUrl: (id: number, which: "original" | "rendition" | "thumb" = "rendition") =>
    `/api/library/${id}/file?which=${which}`,

  productions: (projectId?: number) =>
    request<Production[]>(`/productions${projectId ? `?project_id=${projectId}` : ""}`),
  production: (id: number) => request<Production>(`/productions/${id}`),
  createProduction: (body: ProductionInput) =>
    request<Production>("/productions", { method: "POST", body: json(body) }),
  updateProduction: (
    id: number,
    changes: { title?: string; language?: Language; segments?: ProductionSegment[] },
  ) => request<Production>(`/productions/${id}`, { method: "PATCH", body: json(changes) }),
  translateProduction: (id: number, language: Language) =>
    request<Production>(`/productions/${id}/translate`, {
      method: "POST",
      body: json({ language }),
    }),
  renderProduction: (id: number) =>
    request<Production>(`/productions/${id}/render`, { method: "POST" }),
  deleteProduction: (id: number) =>
    request<void>(`/productions/${id}`, { method: "DELETE" }),
  productionSubtitlesUrl: (id: number, format: "srt" | "vtt") =>
    `/api/productions/${id}/subtitles?fmt=${format}`,

  // approval center (extension E8)
  approvalInfo: () => request<ApprovalInfo>("/approval/info"),
  approvalPosts: (filter: { projectId?: number; itemId?: number; status?: VideoStatus } = {}) => {
    const q = new URLSearchParams();
    if (filter.projectId) q.set("project_id", String(filter.projectId));
    if (filter.itemId) q.set("item_id", String(filter.itemId));
    if (filter.status) q.set("status", filter.status);
    const qs = q.toString();
    return request<ApprovalPost[]>(`/approval${qs ? `?${qs}` : ""}`);
  },
  suggestPostTexts: (itemId: number, channelId: number) =>
    request<PostTexts>("/approval/suggest", {
      method: "POST",
      body: json({ item_id: itemId, channel_id: channelId }),
    }),
  preparePosts: (itemId: number, channelIds: number[], texts: Record<number, PostTextsInput> = {}) =>
    request<ApprovalPost[]>("/approval/prepare", {
      method: "POST",
      body: json({ item_id: itemId, channel_ids: channelIds, texts }),
    }),
  preparePostsEverywhere: (itemId: number) =>
    request<ApprovalPost[]>("/approval/prepare", {
      method: "POST",
      body: json({ item_id: itemId, everywhere: true }),
    }),
  updatePost: (id: number, changes: PostChanges) =>
    request<ApprovalPost>(`/approval/${id}`, { method: "PATCH", body: json(changes) }),
  approvePost: (id: number) => request<ApprovalPost>(`/approval/${id}/approve`, { method: "POST" }),
  withdrawPost: (id: number) =>
    request<ApprovalPost>(`/approval/${id}/withdraw`, { method: "POST" }),
  discardPost: (id: number) => request<ApprovalPost>(`/approval/${id}/discard`, { method: "POST" }),

  settings: () => request<SettingsResponse>("/settings"),
  updateControls: (
    changes: Partial<Pick<EffectiveControls, "emergency_stop" | "auto_publish_enabled">>,
  ) => request<EffectiveControls>("/settings/controls", { method: "PATCH", body: json(changes) }),
  updateOperations: (changes: Partial<OperationsSettings>) =>
    request<OperationsSettings>("/settings/operations", { method: "PATCH", body: json(changes) }),

  channels: () => request<Channel[]>("/channels"),
  createChannel: (body: ChannelInput) =>
    request<Channel>("/channels", { method: "POST", body: json(body) }),
  moveChannel: (id: number, contentProjectId: number) =>
    request<Channel>(`/channels/${id}/project`, {
      method: "PUT",
      body: json({ content_project_id: contentProjectId }),
    }),

  projects: () => request<ContentProject[]>("/projects"),
  createProject: (body: ContentProjectInput) =>
    request<ContentProject>("/projects", { method: "POST", body: json(body) }),
  updateProject: (id: number, changes: ContentProjectPatch) =>
    request<ContentProject>(`/projects/${id}`, { method: "PATCH", body: json(changes) }),
  pauseChannel: (id: number) => request<Channel>(`/channels/${id}/pause`, { method: "POST" }),
  resumeChannel: (id: number) => request<Channel>(`/channels/${id}/resume`, { method: "POST" }),
  connectChannel: (id: number) =>
    request<{ url: string }>(`/channels/${id}/connect`, { method: "POST" }),
  disconnectChannel: (id: number) =>
    request<Channel>(`/channels/${id}/disconnect`, { method: "POST" }),
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
  variantFileUrl: (id: number) => `/api/variants/${id}/file`,
  variantSubtitlesUrl: (id: number, format: "srt" | "vtt") =>
    `/api/variants/${id}/subtitles.${format}`,
  renderCapacity: () => request<RenderCapacity>("/production/capacity"),

  // publishing strategy (Phase 11)
  publishingPlan: () => request<ChannelPlan[]>("/publishing/plan"),
  rollbackStrategy: (channelId: number, version: number) =>
    request<StrategyVersion>(`/publishing/channels/${channelId}/rollback`, {
      method: "POST",
      body: json({ version }),
    }),

  // analytics, learning and costs (Phase 14)
  analytics: (filters: AnalyticsFilters) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== "") params.set(key, String(value));
    }
    return request<AnalyticsOverview>(`/analytics/overview?${params.toString()}`);
  },
  learningVersions: () => request<LearningVersionOut[]>("/analytics/learning"),
  hookReport: () => request<HookReport>("/analytics/hooks"),

  // Ausbau A8: bio-link pages, affiliate links, newsletter, campaign fit
  bioPages: (projectId?: number) =>
    request<BioPage[]>(`/bio-pages${projectId ? `?project_id=${projectId}` : ""}`),
  updateBioPage: (id: number, data: BioPagePatch) =>
    request<BioPage>(`/bio-pages/${id}`, { method: "PATCH", body: json(data) }),
  affiliateLinks: (projectId?: number) =>
    request<AffiliateLink[]>(`/affiliate-links${projectId ? `?project_id=${projectId}` : ""}`),
  createAffiliateLink: (data: AffiliateInput) =>
    request<AffiliateLink>("/affiliate-links", { method: "POST", body: json(data) }),
  updateAffiliateLink: (id: number, data: Partial<Omit<AffiliateInput, "project_id">>) =>
    request<AffiliateLink>(`/affiliate-links/${id}`, { method: "PATCH", body: json(data) }),
  deleteAffiliateLink: (id: number) =>
    request<void>(`/affiliate-links/${id}`, { method: "DELETE" }),
  newsletter: (projectId?: number) =>
    request<NewsletterOverview>(`/newsletter${projectId ? `?project_id=${projectId}` : ""}`),
  deleteSubscriber: (id: number) => request<void>(`/newsletter/${id}`, { method: "DELETE" }),
  outbox: () => request<Outbox>("/mail/outbox"),
  // Ausbau A9: sponsor inbox (drafts only, nothing is sent)
  sponsorInbox: (state?: SponsorStatus) =>
    request<SponsorInbox>(`/sponsors${state ? `?state=${state}` : ""}`),
  addSponsorInquiry: (data: SponsorInput) =>
    request<SponsorInquiry>("/sponsors", { method: "POST", body: json(data) }),
  updateSponsorInquiry: (id: number, data: SponsorPatch) =>
    request<SponsorInquiry>(`/sponsors/${id}`, { method: "PATCH", body: json(data) }),
  redraftSponsorInquiry: (id: number) =>
    request<SponsorInquiry>(`/sponsors/${id}/redraft`, { method: "POST" }),
  deleteSponsorInquiry: (id: number) => request<void>(`/sponsors/${id}`, { method: "DELETE" }),
  matchCampaign: (data: CampaignMatchInput) =>
    request<CampaignFit[]>("/campaigns/match", { method: "POST", body: json(data) }),
  rollbackLearning: (version: number) =>
    request<LearningVersionOut>(`/analytics/learning/${version}/rollback`, { method: "POST" }),
  costSummary: () => request<CostSummary>("/costs/summary"),
  systemStatus: () => request<SystemStatus>("/system/status"),

  // comments: drafts, replies, review
  comments: (state?: CommentStatus) =>
    request<ViewerComment[]>(`/comments${state ? `?state=${state}` : ""}`),
  commentStats: () => request<CommentStats>("/comments/stats"),
  editCommentReply: (id: number, reply_text: string) =>
    request<ViewerComment>(`/comments/${id}/reply`, { method: "PUT", body: json({ reply_text }) }),
  sendComment: (id: number, reply_text?: string) =>
    request<ViewerComment>(`/comments/${id}/send`, {
      method: "POST",
      body: json(reply_text === undefined ? {} : { reply_text }),
    }),
  commentDone: (id: number) => request<ViewerComment>(`/comments/${id}/done`, { method: "POST" }),
  ignoreComment: (id: number) =>
    request<ViewerComment>(`/comments/${id}/ignore`, { method: "POST" }),
  redraftComment: (id: number) =>
    request<ViewerComment>(`/comments/${id}/redraft`, { method: "POST" }),
  addManualComment: (channel_id: number, text: string, author?: string) =>
    request<ViewerComment>("/comments/manual", {
      method: "POST",
      body: json({ channel_id, text, author: author || undefined }),
    }),
  runComments: () => request<{ job_id: string | null }>("/comments/run", { method: "POST" }),
  // account overview: every channel with reach, revenue and recommendation
  accounts: () => request<AccountsOverview>("/accounts"),
  revenue: (channelId?: number) =>
    request<RevenueEntry[]>(`/accounts/revenue${channelId ? `?channel_id=${channelId}` : ""}`),
  addRevenue: (data: RevenueInput) =>
    request<RevenueEntry>("/accounts/revenue", { method: "POST", body: json(data) }),
  deleteRevenue: (id: number) =>
    request<void>(`/accounts/revenue/${id}`, { method: "DELETE" }),
  // channel assistant: coverage per topic area and "create channel" tasks
  channelCoverage: () => request<ProjectCoverage[]>("/channel-setup/coverage"),
  channelSetupTasks: (state: ChannelSetupStatus = "open") =>
    request<ChannelSetupTask[]>(`/channel-setup/tasks?state=${state}`),
  mailRoutingStatus: () => request<MailRoutingStatus>("/channel-setup/mail"),
  prepareChannels: (projectId: number) =>
    request<ChannelSetupTask[]>("/channel-setup/prepare", {
      method: "POST",
      body: json({ project_id: projectId }),
    }),
  updateChannelSetup: (id: number, changes: ChannelSetupPatch) =>
    request<ChannelSetupTask>(`/channel-setup/tasks/${id}`, { method: "PATCH", body: json(changes) }),
  retryChannelSetupEmail: (id: number) =>
    request<ChannelSetupTask>(`/channel-setup/tasks/${id}/email`, { method: "POST" }),
  completeChannelSetup: (id: number, handle?: string) =>
    request<{ task: ChannelSetupTask; channel_id: number }>(`/channel-setup/tasks/${id}/complete`, {
      method: "POST",
      body: json(handle ? { handle } : {}),
    }),
  dismissChannelSetup: (id: number) =>
    request<ChannelSetupTask>(`/channel-setup/tasks/${id}/dismiss`, { method: "POST" }),
  channelSetupImage: (id: number, kind: "avatar" | "banner") =>
    `/api/channel-setup/tasks/${id}/${kind}.png`,
  // clipping campaigns (Content Rewards)
  campaigns: () => request<Campaign[]>("/campaigns"),
  createCampaign: (data: CampaignInput) =>
    request<Campaign>("/campaigns", { method: "POST", body: json(data) }),
  updateCampaign: (id: number, changes: CampaignFields) =>
    request<Campaign>(`/campaigns/${id}`, { method: "PATCH", body: json(changes) }),
  setCampaignStatus: (id: number, status: CampaignStatus) =>
    request<Campaign>(`/campaigns/${id}/status`, { method: "POST", body: json({ status }) }),
  campaignClips: () => request<CampaignClip[]>("/campaigns/clips/list"),
  updateCampaignClip: (
    id: number,
    changes: { title?: string; description?: string; hashtags?: string[] },
  ) => request<CampaignClip>(`/campaigns/clips/${id}`, { method: "PATCH", body: json(changes) }),
  approveCampaignClip: (id: number) =>
    request<CampaignClip>(`/campaigns/clips/${id}/approve`, { method: "POST" }),
  withdrawCampaignClip: (id: number) =>
    request<CampaignClip>(`/campaigns/clips/${id}/withdraw`, { method: "POST" }),
  discardCampaignClip: (id: number) =>
    request<CampaignClip>(`/campaigns/clips/${id}/discard`, { method: "POST" }),
  submissions: (done = false) =>
    request<CampaignSubmission[]>(
      `/campaigns/submissions/list${done ? "?done=true&limit=30" : ""}`,
    ),
  setSubmissionLink: (id: number, url: string) =>
    request<CampaignSubmission>(`/campaigns/submissions/${id}/link`, {
      method: "POST",
      body: json({ url }),
    }),
  markSubmitted: (id: number) =>
    request<CampaignSubmission>(`/campaigns/submissions/${id}/submitted`, { method: "POST" }),
  skipSubmission: (id: number, note?: string) =>
    request<CampaignSubmission>(`/campaigns/submissions/${id}/skip`, {
      method: "POST",
      body: json({ note: note ?? null }),
    }),
  reopenSubmission: (id: number) =>
    request<CampaignSubmission>(`/campaigns/submissions/${id}/reopen`, { method: "POST" }),

  users: () => request<User[]>("/users"),
  createUser: (data: { email: string; password: string; role: UserRole; display_name?: string }) =>
    request<User>("/users", { method: "POST", body: json(data) }),
  updateUser: (
    id: number,
    data: Partial<{ role: UserRole; is_active: boolean; display_name: string; password: string }>,
  ) => request<User>(`/users/${id}`, { method: "PATCH", body: json(data) }),
};
