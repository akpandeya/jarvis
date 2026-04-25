import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Central registry of query keys. Mutations invalidate against these.
export const keys = {
  sessions: ["sessions"] as const,
  timeline: (days: number, source?: string | null, project?: string | null, page = 1) =>
    ["timeline", { days, source: source ?? null, project: project ?? null, page }] as const,
  search: (q: string) => ["search", q] as const,
  insights: (days: number) => ["insights", days] as const,
  upcoming: ["upcoming"] as const,
  prs: ["prs"] as const,
  prDetail: (repo: string, n: number) => ["prs", "detail", repo, n] as const,
  suggestions: ["suggestions"] as const,
  pendingCount: ["prs", "pending-count"] as const,
  settingsRepoPaths: ["settings", "repo-paths"] as const,
  settingsBrowserProfiles: ["settings", "browser-profiles"] as const,
  settingsGcalProfiles: ["settings", "gcal-profiles"] as const,
  settingsJiraProfiles: ["settings", "jira-profiles"] as const,
  chatSession: (id: string) => ["chat", "session", id] as const,
};
