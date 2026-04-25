// Types mirror the Pydantic / dict shapes returned by jarvis/web/app.py.
// These are contracts with the backend — add matching server-side models if a
// field changes.

export interface Session {
  id: string;
  project: string | null;
  started_at: string;
  ended_at: string | null;
  context: string;
}

export interface ClaudeSession {
  title: string | null;
  happened_at: string | null;
  session_id: string | null;
  branch: string | null;
  cwd: string | null;
  turns: number | null;
}

export interface SessionsResponse {
  sessions: Session[];
  claude_sessions: ClaudeSession[];
}

export interface Event {
  id: string;
  source: string;
  kind: string;
  title: string;
  body: string | null;
  url: string | null;
  project: string | null;
  happened_at: string;
  metadata: Record<string, unknown> | null;
}

export interface TimelineResponse {
  events: Event[];
  total: number;
  sources: string[];
  projects: string[];
  has_more: boolean;
  page: number;
  days: number;
  source: string | null;
  project: string | null;
}

export interface SearchResponse {
  events: Event[];
  query: string;
}

export interface InsightsResponse {
  days: number;
  time_of_day: Record<string, number>;
  day_of_week: Record<string, number>;
  sources: Record<string, number>;
  projects: Record<string, number>;
  collaborators: { name: string; events: number }[];
  context_switches: {
    avg_per_day: number;
    daily: Record<string, number>;
  } | null;
}

export interface Meeting {
  title: string;
  happened_at: string;
  url: string | null;
  body: string | null;
  location: string | null;
  meet_link: string | null;
  attendee_count: number | null;
  account: string | null;
  status: string | null;
  time_local: string;
  happened_at_epoch: number;
}

export interface PrSubscription {
  id: string;
  repo: string;
  pr_number: number;
  title: string | null;
  author: string | null;
  branch: string | null;
  pr_url: string | null;
  state: string;
  subscribed_at: string;
  last_fetched_at: string | null;
  dismissed: number;
  ci_status: string | null;
  review_decision: string | null;
  watch_state: string;
  chat_session_id: string | null;
  priority: number;
  gh_account?: string;
}

export interface ClaudeModel {
  label: string;
  id: string;
}

export interface JiraTicket {
  key: string;
  status: string;
  summary: string;
  assignee: string;
  issue_type: string;
  priority: string;
  url: string;
}

export interface ActiveSprint {
  board_id: number;
  host: string;
  project_key: string;
  nickname: string;
  sprint_name: string;
  mine: JiraTicket[];
  unassigned: JiraTicket[];
  others: JiraTicket[];
}

export interface UpcomingResponse {
  today: string; // ISO date (YYYY-MM-DD)
  today_label: string; // pretty e.g. "Friday, April 24"
  meetings: Meeting[];
  top_prs: PrSubscription[];
  active_sprints: ActiveSprint[];
  review_model: string;
  available_models: ClaudeModel[];
}

export interface PrsResponse {
  pending: PrSubscription[];
  watching: PrSubscription[];
  later: PrSubscription[];
  dismissed: PrSubscription[];
  all_repos: string[];
  all_authors: string[];
  last_checked: string | null;
  review_model: string;
  available_models: ClaudeModel[];
  filter_repo: string;
  filter_author: string;
}

export interface Suggestion {
  rule_id: string;
  message: string;
  action: string;
  priority: number;
}

export interface ChatHistoryTurn {
  role: "user" | "assistant";
  text: string;
}

export interface ChatSessionMeta {
  session_id: string;
  history_preview: string;
  history: ChatHistoryTurn[];
  autostart_prompt: string;
  autostart_model: string;
}

export interface SummaryResponse {
  html: string;
}

export interface OkResponse {
  ok: boolean;
}

export interface SubscriptionUpdateResponse extends OkResponse {
  subscription: PrSubscription;
}

export interface DiscoverResponse {
  discovered: number;
  total: number;
}

export interface RefreshAllResponse {
  updated: number;
}

export interface RefreshRunningResponse {
  ok: boolean;
  refreshed: number;
  still_running: number;
}

export interface PendingCountResponse {
  count: number;
}

export interface ReviewStartResponse {
  session_id: string;
  redirect: string;
}

export interface IngestResponse {
  ok: boolean;
  log: string;
}
