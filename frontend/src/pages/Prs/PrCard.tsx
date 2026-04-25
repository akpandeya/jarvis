import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../../lib/api";
import { queryClient, keys } from "../../lib/queryClient";
import { CiBadge, ReviewBadge } from "./badges";
import { btnSm, btnSmPrimary } from "./buttons";
import type { ClaudeModel, PrSubscription } from "../../lib/types";

function invalidate() {
  queryClient.invalidateQueries({ queryKey: keys.prs });
  queryClient.invalidateQueries({ queryKey: keys.pendingCount });
  queryClient.invalidateQueries({ queryKey: keys.upcoming });
}

export function PrCard({
  pr,
  reviewModel,
  availableModels,
}: {
  pr: PrSubscription;
  reviewModel: string;
  availableModels: ClaudeModel[];
}) {
  const [model, setModel] = useState("");
  const [priority, setPriority] = useState(pr.priority);
  const navigate = useNavigate();

  const open = useMutation({
    mutationFn: () => api.openUrl(pr.pr_url ?? "", pr.gh_account),
    onError: () => toast.error("Failed to open"),
  });
  const later = useMutation({
    mutationFn: () => api.prLater(pr.repo, pr.pr_number),
    onSuccess: () => {
      toast.success("Moved to Later");
      invalidate();
    },
    onError: () => toast.error("Failed"),
  });
  const dismiss = useMutation({
    mutationFn: () => api.prDismiss(pr.repo, pr.pr_number),
    onSuccess: () => {
      toast.success("Dismissed");
      invalidate();
    },
    onError: () => toast.error("Failed"),
  });
  const refresh = useMutation({
    mutationFn: () => api.prRefresh(pr.repo, pr.pr_number),
    onSuccess: () => invalidate(),
    onError: () => toast.error("Refresh failed"),
  });
  const setPri = useMutation({
    mutationFn: (p: number) => api.prPriority(pr.repo, pr.pr_number, p),
    onSuccess: () => invalidate(),
    onError: () => toast.error("Priority update failed"),
  });
  const review = useMutation({
    mutationFn: () => api.prReview(pr.repo, pr.pr_number, model),
    onSuccess: (res) => navigate(res.redirect),
    onError: () => toast.error("Review failed"),
  });
  const rereview = useMutation({
    mutationFn: () => api.prRereview(pr.repo, pr.pr_number, model),
    onSuccess: (res) => navigate(res.redirect),
    onError: () => toast.error("Re-review failed"),
  });

  return (
    <article
      style={{
        marginBottom: "0.6rem",
        padding: "0.7rem 1rem",
        border: "1px solid var(--color-border)",
        borderRadius: 6,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: "0.92em" }}>
            <a
              href={pr.pr_url ?? "#"}
              onClick={(e) => {
                e.preventDefault();
                open.mutate();
              }}
            >
              #{pr.pr_number} {pr.title ?? "(unknown)"}
            </a>
          </div>
          <div style={{ fontSize: "0.78em", color: "var(--color-muted)", marginTop: "0.2rem" }}>
            {pr.repo}
            {pr.author && <> · {pr.author}</>}
            {pr.branch && (
              <>
                {" · "}
                <code>{pr.branch}</code>
              </>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", fontSize: "0.85em" }}>
          <span>
            <CiBadge status={pr.ci_status} /> &nbsp; <ReviewBadge decision={pr.review_decision} />
          </span>
          <button
            title="Refresh"
            style={btnSm}
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? "…" : "↻"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginTop: "0.5rem", alignItems: "center" }}>
        <button style={btnSm} onClick={() => open.mutate()}>
          ↗ GitHub
        </button>

        {pr.authoring_session_ids && pr.authoring_session_ids.length > 0 && (
          <Link
            to={`/chat?session=${pr.authoring_session_ids[0]}`}
            style={{ ...btnSm, textDecoration: "none" }}
            title={
              pr.authoring_session_ids.length > 1
                ? `Open the most recent of ${pr.authoring_session_ids.length} authoring conversations`
                : "Open the conversation that created this PR"
            }
          >
            💬 Conversation
            {pr.authoring_session_ids.length > 1
              ? ` (${pr.authoring_session_ids.length})`
              : ""}
          </Link>
        )}

        {pr.chat_session_id ? (
          <>
            <Link
              to={`/chat?session=${pr.chat_session_id}`}
              style={{ ...btnSmPrimary, textDecoration: "none" }}
              title="Open the existing review conversation"
            >
              ↩ Open review
            </Link>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{ fontSize: "0.72rem", padding: "0.15rem 0.35rem", margin: 0 }}
            >
              <option value="">default ({reviewModel})</option>
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
            <button style={btnSmPrimary} onClick={() => rereview.mutate()} disabled={rereview.isPending}>
              ↻ Re-review
            </button>
          </>
        ) : (
          <>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{ fontSize: "0.72rem", padding: "0.15rem 0.35rem", margin: 0 }}
            >
              <option value="">default ({reviewModel})</option>
              {availableModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
            <button style={btnSmPrimary} onClick={() => review.mutate()} disabled={review.isPending}>
              Review
            </button>
          </>
        )}

        <button style={btnSm} onClick={() => later.mutate()} disabled={later.isPending}>
          Later
        </button>
        <button style={btnSm} onClick={() => dismiss.mutate()} disabled={dismiss.isPending}>
          – Dismiss
        </button>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.35rem",
            marginLeft: "auto",
            fontSize: "0.75em",
            color: "var(--color-muted)",
          }}
        >
          <span>Priority</span>
          <input
            type="range"
            min={0}
            max={10}
            value={priority}
            onChange={(e) => setPriority(+e.target.value)}
            onMouseUp={() => setPri.mutate(priority)}
            onKeyUp={() => setPri.mutate(priority)}
            onTouchEnd={() => setPri.mutate(priority)}
            style={{ width: 72, margin: 0, cursor: "pointer" }}
          />
          <span style={{ minWidth: "1.1em", textAlign: "right" }}>{priority}</span>
        </div>
      </div>
    </article>
  );
}
