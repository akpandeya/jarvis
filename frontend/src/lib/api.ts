// Typed fetch wrappers. One function per endpoint.
// All HTTP error responses throw — callers surface them via TanStack Query.

import type {
  ChatSessionMeta,
  DiscoverResponse,
  InsightsResponse,
  OkResponse,
  PendingCountResponse,
  PrsResponse,
  RefreshAllResponse,
  RefreshRunningResponse,
  ReviewStartResponse,
  SearchResponse,
  SessionsResponse,
  SubscriptionUpdateResponse,
  Suggestion,
  SummaryResponse,
  TimelineResponse,
  UpcomingResponse,
  IngestResponse,
} from "./types";

class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`API ${status}: ${body.slice(0, 120)}`);
    this.status = status;
    this.body = body;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    credentials: "same-origin",
    ...init,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new ApiError(resp.status, text);
  }
  const ct = resp.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) return (await resp.json()) as T;
  // Some endpoints return empty body on success.
  return {} as T;
}

function form(values: Record<string, string | number | null | undefined>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === undefined) continue;
    fd.append(k, String(v));
  }
  return fd;
}

// Encode owner/repo as owner--repo for path params (same as the backend expects).
export function encodeRepo(repo: string): string {
  return repo.replace(/\//g, "--");
}

export const api = {
  // Sessions / Focus
  sessions: () => req<SessionsResponse>("/api/sessions"),
  upcoming: () => req<UpcomingResponse>("/api/upcoming"),

  // Timeline / search / insights
  timeline: (params: {
    days?: number;
    source?: string | null;
    project?: string | null;
    page?: number;
  }) => {
    const q = new URLSearchParams();
    if (params.days) q.set("days", String(params.days));
    if (params.source) q.set("source", params.source);
    if (params.project) q.set("project", params.project);
    if (params.page) q.set("page", String(params.page));
    return req<TimelineResponse>(`/api/timeline?${q}`);
  },
  search: (q: string) =>
    req<SearchResponse>(`/api/search?q=${encodeURIComponent(q)}`),
  insights: (days: number) => req<InsightsResponse>(`/api/insights?days=${days}`),
  suggestions: () => req<Suggestion[]>("/api/suggestions"),
  summary: (kind: string, days: number, project?: string | null) => {
    const q = new URLSearchParams({ kind, days: String(days) });
    if (project) q.set("project", project);
    return req<SummaryResponse>(`/api/summary?${q}`);
  },
  ingest: () =>
    req<IngestResponse>("/api/ingest", { method: "POST" }),

  // Chat
  chatSession: (id: string) => req<ChatSessionMeta>(`/api/chat/session/${encodeURIComponent(id)}`),

  // PRs
  prs: (params?: { repo?: string; author?: string }) => {
    const q = new URLSearchParams();
    if (params?.repo) q.set("repo", params.repo);
    if (params?.author) q.set("author", params.author);
    return req<PrsResponse>(`/api/prs${q.toString() ? `?${q}` : ""}`);
  },
  prDetail: (repo: string, n: number) =>
    req<Record<string, unknown>>(
      `/api/prs/${encodeRepo(repo)}/${n}/detail`,
    ),
  prWatch: (repo: string, n: number) =>
    req<SubscriptionUpdateResponse>(
      `/api/prs/${encodeRepo(repo)}/${n}/watch`,
      { method: "POST" },
    ),
  prDismiss: (repo: string, n: number) =>
    req<SubscriptionUpdateResponse>(
      `/api/prs/${encodeRepo(repo)}/${n}/dismiss`,
      { method: "POST" },
    ),
  prLater: (repo: string, n: number) =>
    req<SubscriptionUpdateResponse>(
      `/api/prs/${encodeRepo(repo)}/${n}/later`,
      { method: "POST" },
    ),
  prRestore: (repo: string, n: number) =>
    req<SubscriptionUpdateResponse>(
      `/api/prs/${encodeRepo(repo)}/${n}/restore`,
      { method: "POST" },
    ),
  prPriority: (repo: string, n: number, priority: number) =>
    req<SubscriptionUpdateResponse>(
      `/api/prs/${encodeRepo(repo)}/${n}/priority`,
      { method: "POST", body: form({ priority }) },
    ),
  prRefresh: (repo: string, n: number) =>
    req<SubscriptionUpdateResponse>(
      `/api/prs/${encodeRepo(repo)}/${n}/refresh`,
    ),
  prUnsubscribe: (repo: string, n: number) =>
    req<OkResponse>(`/api/prs/${encodeRepo(repo)}/${n}`, { method: "DELETE" }),
  prReview: (repo: string, n: number, model: string) =>
    req<ReviewStartResponse>(
      `/api/prs/${encodeRepo(repo)}/${n}/review`,
      { method: "POST", body: form({ model }) },
    ),
  prRereview: (repo: string, n: number, model: string) =>
    req<ReviewStartResponse>(
      `/api/prs/${encodeRepo(repo)}/${n}/rereview`,
      { method: "POST", body: form({ model }) },
    ),
  prDiscover: () =>
    req<DiscoverResponse>("/api/prs/discover", { method: "POST" }),
  prRefreshAll: () =>
    req<RefreshAllResponse>("/api/prs/refresh-all", { method: "POST" }),
  prRefreshRunning: () =>
    req<RefreshRunningResponse>("/api/prs/refresh-running", { method: "POST" }),
  prPendingCount: () =>
    req<PendingCountResponse>("/api/prs/pending-count"),

  // Side-effect endpoints
  openUrl: (url: string, gh_account?: string) =>
    req<OkResponse>("/api/open-url", {
      method: "POST",
      body: form({ url, gh_account }),
    }),
};

export { ApiError };
