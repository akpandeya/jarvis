import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../lib/api";
import { keys, queryClient } from "../lib/queryClient";
import { AccountBadge } from "../components/AccountBadge";
import { CiBadge, ReviewBadge } from "./Prs/badges";
import type { Meeting, PrSubscription } from "../lib/types";

function useNow(intervalMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function MeetingRow({ m }: { m: Meeting }) {
  const now = useNow();
  const past = m.happened_at_epoch > 0 && m.happened_at_epoch < now;
  const open = useMutation({
    mutationFn: (args: { url: string; gh?: string }) => api.openUrl(args.url, args.gh),
    onError: () => toast.error("Failed to open URL"),
  });
  return (
    <div
      style={{
        display: "flex",
        gap: "0.75rem",
        alignItems: "flex-start",
        padding: "0.65rem 0",
        borderBottom: "1px solid var(--color-border-muted)",
        opacity: past ? 0.32 : 1,
        transition: "opacity .4s",
      }}
    >
      <div
        style={{
          fontSize: "0.8em",
          color: "var(--color-muted)",
          minWidth: "3.8rem",
          paddingTop: "0.1rem",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {m.time_local}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: "0.92em",
            fontWeight: 600,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            textDecoration: past ? "line-through" : "none",
          }}
          title={m.title}
        >
          {m.title}
        </div>
        <div
          style={{
            fontSize: "0.78em",
            color: "var(--color-muted)",
            marginTop: "0.2rem",
            display: "flex",
            gap: "0.5rem",
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          {m.account && <AccountBadge account={m.account} />}
          {m.attendee_count != null && m.attendee_count > 1 && (
            <span>{m.attendee_count} attendees</span>
          )}
          {m.meet_link && (
            <button
              disabled={past}
              className="join-btn"
              onClick={() => open.mutate({ url: m.meet_link!, gh: m.account ?? undefined })}
              style={{
                fontSize: "0.72rem",
                padding: "0.15rem 0.5rem",
                background: "none",
                border: "1px solid var(--color-primary)",
                color: "var(--color-primary)",
                borderRadius: 4,
              }}
            >
              ▶ Join
            </button>
          )}
          {m.url && (
            <button
              className="join-btn"
              onClick={() => open.mutate({ url: m.url!, gh: m.account ?? undefined })}
              style={{
                fontSize: "0.72rem",
                padding: "0.15rem 0.5rem",
                background: "none",
                border: "1px solid var(--color-muted)",
                color: "var(--color-muted)",
                borderRadius: 4,
              }}
            >
              calendar ↗
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function TopPrCard({
  pr,
  reviewModel,
  availableModels,
}: {
  pr: PrSubscription;
  reviewModel: string;
  availableModels: { id: string; label: string }[];
}) {
  const [model, setModel] = useState("");
  const navigate = useNavigate();

  const open = useMutation({
    mutationFn: () => api.openUrl(pr.pr_url ?? "", pr.gh_account),
    onError: () => toast.error("Failed to open"),
  });
  const review = useMutation({
    mutationFn: () => api.prReview(pr.repo, pr.pr_number, model),
    onSuccess: (res) => navigate(res.redirect),
    onError: () => toast.error("Failed to start review"),
  });
  const rereview = useMutation({
    mutationFn: () => api.prRereview(pr.repo, pr.pr_number, model),
    onSuccess: (res) => navigate(res.redirect),
    onError: () => toast.error("Failed to re-review"),
  });

  const btnStyle = {
    fontSize: "0.72rem",
    padding: "0.15rem 0.5rem",
    background: "none",
    border: "1px solid var(--color-primary)",
    color: "var(--color-primary)",
    borderRadius: 4,
    cursor: "pointer",
  };

  return (
    <div style={{ padding: "0.55rem 0", borderBottom: "1px solid var(--color-border-muted)" }}>
      <div
        style={{
          fontSize: "0.88em",
          fontWeight: 600,
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        <button
          onClick={() => open.mutate()}
          style={{
            ...btnStyle,
            borderColor: "var(--color-muted)",
            color: "var(--color-muted)",
          }}
        >
          ↗ GitHub
        </button>
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          #{pr.pr_number} {pr.title ?? "(unknown)"}
        </span>
      </div>
      <div
        style={{
          fontSize: "0.78em",
          color: "var(--color-muted)",
          marginTop: "0.35rem",
          display: "flex",
          gap: "0.5rem",
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <span>{pr.repo}</span>
        <CiBadge status={pr.ci_status} />
        <ReviewBadge decision={pr.review_decision} />
        {pr.priority > 0 && (
          <span style={{ fontSize: "0.75em", color: "var(--color-primary)", fontWeight: 600 }}>
            p{pr.priority}
          </span>
        )}
        {pr.chat_session_id ? (
          <>
            <Link
              to={`/chat?session=${pr.chat_session_id}`}
              style={{ ...btnStyle, textDecoration: "none" }}
            >
              ↩ Continue
            </Link>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{ fontSize: "0.68rem", padding: "0.1rem 0.3rem" }}
            >
              <option value="">{reviewModel}</option>
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
            <button
              onClick={() => rereview.mutate()}
              disabled={rereview.isPending}
              style={btnStyle}
            >
              ↻ Re-review
            </button>
          </>
        ) : (
          <>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{ fontSize: "0.68rem", padding: "0.1rem 0.3rem" }}
            >
              <option value="">{reviewModel}</option>
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
            <button onClick={() => review.mutate()} disabled={review.isPending} style={btnStyle}>
              Ask Claude
            </button>
          </>
        )}
      </div>
    </div>
  );
}

export default function Upcoming() {
  const { data, isLoading } = useQuery({
    queryKey: keys.upcoming,
    queryFn: api.upcoming,
  });

  // Touch the query client so a future invalidation in another tab works.
  void queryClient;

  if (isLoading || !data) return <p>Loading…</p>;

  return (
    <>
      <div style={{ display: "flex", alignItems: "baseline", gap: "0.75rem", marginBottom: "1rem" }}>
        <h2 style={{ margin: 0 }}>Focus</h2>
        <span style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>{data.today_label}</span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 380px",
          gap: "1.5rem",
          alignItems: "start",
        }}
      >
        <section>
          <div
            style={{
              fontSize: "0.75em",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.07em",
              color: "var(--color-muted)",
              marginBottom: "0.75rem",
              paddingBottom: "0.4rem",
              borderBottom: "1px solid var(--color-border-muted)",
            }}
          >
            Today's Meetings
          </div>
          {data.meetings.length > 0 ? (
            data.meetings.map((m) => <MeetingRow key={`${m.happened_at}-${m.title}`} m={m} />)
          ) : (
            <div style={{ color: "var(--color-muted)", fontSize: "0.88em", padding: "1rem 0", textAlign: "center" }}>
              No meetings today
            </div>
          )}
        </section>

        <aside>
          <div
            style={{
              fontSize: "0.75em",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.07em",
              color: "var(--color-muted)",
              marginBottom: "0.75rem",
              paddingBottom: "0.4rem",
              borderBottom: "1px solid var(--color-border-muted)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span>Top PRs</span>
            <Link to="/prs" style={{ fontSize: "0.78em", fontWeight: 400, textTransform: "none", letterSpacing: 0, color: "var(--color-muted)" }}>
              all PRs ↗
            </Link>
          </div>
          {data.top_prs.length > 0 ? (
            data.top_prs.map((pr) => (
              <TopPrCard
                key={`${pr.repo}#${pr.pr_number}`}
                pr={pr}
                reviewModel={data.review_model}
                availableModels={data.available_models}
              />
            ))
          ) : (
            <div style={{ color: "var(--color-muted)", fontSize: "0.88em", padding: "1rem 0", textAlign: "center" }}>
              No watched PRs
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
