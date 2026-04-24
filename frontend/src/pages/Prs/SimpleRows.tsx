import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../../lib/api";
import { queryClient, keys } from "../../lib/queryClient";
import { btnSm, btnSmPrimary } from "./buttons";
import type { PrSubscription } from "../../lib/types";

function invalidate() {
  queryClient.invalidateQueries({ queryKey: keys.prs });
  queryClient.invalidateQueries({ queryKey: keys.pendingCount });
  queryClient.invalidateQueries({ queryKey: keys.upcoming });
}

function openPr(pr: PrSubscription) {
  void api.openUrl(pr.pr_url ?? "", pr.gh_account);
}

export function PendingRow({ pr }: { pr: PrSubscription }) {
  const watch = useMutation({
    mutationFn: () => api.prWatch(pr.repo, pr.pr_number),
    onSuccess: () => {
      toast.success("Now watching");
      invalidate();
    },
  });
  const later = useMutation({
    mutationFn: () => api.prLater(pr.repo, pr.pr_number),
    onSuccess: () => {
      toast.success("Moved to Later");
      invalidate();
    },
  });
  const dismiss = useMutation({
    mutationFn: () => api.prDismiss(pr.repo, pr.pr_number),
    onSuccess: () => {
      toast.success("Dismissed");
      invalidate();
    },
  });
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexWrap: "wrap",
        gap: "0.5rem",
        padding: "0.5rem 0",
        borderBottom: "1px solid var(--color-border-muted)",
      }}
    >
      <div>
        <div style={{ fontWeight: 600, fontSize: "0.92em" }}>
          <a
            href={pr.pr_url ?? "#"}
            onClick={(e) => {
              e.preventDefault();
              openPr(pr);
            }}
          >
            {pr.repo}#{pr.pr_number} — {pr.title ?? "(unknown)"}
          </a>
        </div>
        <div style={{ fontSize: "0.78em", color: "var(--color-muted)", marginTop: "0.2rem" }}>
          {pr.author ?? ""}
          {pr.branch && (
            <>
              {" · "}
              <code>{pr.branch}</code>
            </>
          )}
        </div>
      </div>
      <div style={{ display: "flex", gap: "0.4rem" }}>
        <button style={btnSmPrimary} onClick={() => watch.mutate()} disabled={watch.isPending}>
          + Watch
        </button>
        <button style={btnSm} onClick={() => later.mutate()} disabled={later.isPending}>
          Later
        </button>
        <button style={btnSm} onClick={() => dismiss.mutate()} disabled={dismiss.isPending}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

export function LaterRow({ pr }: { pr: PrSubscription }) {
  const watch = useMutation({
    mutationFn: () => api.prWatch(pr.repo, pr.pr_number),
    onSuccess: () => invalidate(),
  });
  const restore = useMutation({
    mutationFn: () => api.prRestore(pr.repo, pr.pr_number),
    onSuccess: () => invalidate(),
  });
  const dismiss = useMutation({
    mutationFn: () => api.prDismiss(pr.repo, pr.pr_number),
    onSuccess: () => invalidate(),
  });
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "0.4rem 0",
        borderBottom: "1px solid var(--color-border-muted)",
        flexWrap: "wrap",
        gap: "0.5rem",
      }}
    >
      <div style={{ fontSize: "0.84em" }}>
        <a
          href={pr.pr_url ?? "#"}
          onClick={(e) => {
            e.preventDefault();
            openPr(pr);
          }}
        >
          #{pr.pr_number} {pr.title ?? "(unknown)"}
        </a>
        <span style={{ color: "var(--color-muted)", marginLeft: "0.4rem" }}>{pr.repo}</span>
        {pr.author && <span style={{ color: "var(--color-muted)" }}> · {pr.author}</span>}
      </div>
      <div style={{ display: "flex", gap: "0.4rem" }}>
        <button style={btnSmPrimary} onClick={() => watch.mutate()}>
          + Watch
        </button>
        <button style={btnSm} onClick={() => restore.mutate()}>
          ↩ Pending
        </button>
        <button style={btnSm} onClick={() => dismiss.mutate()}>
          Dismiss
        </button>
      </div>
    </div>
  );
}

export function DismissedRow({ pr }: { pr: PrSubscription }) {
  const watch = useMutation({
    mutationFn: () => api.prWatch(pr.repo, pr.pr_number),
    onSuccess: () => invalidate(),
  });
  const restore = useMutation({
    mutationFn: () => api.prRestore(pr.repo, pr.pr_number),
    onSuccess: () => invalidate(),
  });
  const remove = useMutation({
    mutationFn: () => api.prUnsubscribe(pr.repo, pr.pr_number),
    onSuccess: () => invalidate(),
  });
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "0.4rem 0",
        borderBottom: "1px solid var(--color-border-muted)",
        flexWrap: "wrap",
        gap: "0.5rem",
      }}
    >
      <div style={{ fontSize: "0.84em" }}>
        <a
          href={pr.pr_url ?? "#"}
          onClick={(e) => {
            e.preventDefault();
            openPr(pr);
          }}
        >
          #{pr.pr_number} {pr.title ?? "(unknown)"}
        </a>
        <span style={{ color: "var(--color-muted)", marginLeft: "0.4rem" }}>{pr.repo}</span>
      </div>
      <div style={{ display: "flex", gap: "0.4rem" }}>
        <button style={btnSm} onClick={() => restore.mutate()}>
          ↩ Restore
        </button>
        <button style={btnSmPrimary} onClick={() => watch.mutate()}>
          + Watch
        </button>
        <button
          style={btnSm}
          onClick={() => {
            if (confirm("Remove this PR entirely?")) remove.mutate();
          }}
        >
          ✕
        </button>
      </div>
    </div>
  );
}
