import { useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../../lib/api";
import { keys, queryClient } from "../../lib/queryClient";
import { PrCard } from "./PrCard";
import { PendingRow, LaterRow, DismissedRow } from "./SimpleRows";
import { btnSm } from "./buttons";

function SectionLabel({ text }: { text: string }) {
  return (
    <div
      style={{
        fontSize: "0.72em",
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.07em",
        color: "var(--color-muted)",
        padding: "0.35rem 0",
        borderBottom: "1px solid var(--color-border-muted)",
      }}
    >
      {text}
    </div>
  );
}

export default function Prs() {
  const [params, setParams] = useSearchParams();
  const repoFilter = params.get("repo") ?? "";
  const authorFilter = params.get("author") ?? "";

  const { data, isLoading } = useQuery({
    queryKey: [...keys.prs, { repo: repoFilter, author: authorFilter }],
    queryFn: () =>
      api.prs({
        repo: repoFilter || undefined,
        author: authorFilter || undefined,
      }),
  });

  const discover = useMutation({
    mutationFn: api.prDiscover,
    onSuccess: (res) => {
      toast.success(`${res.discovered} PR${res.discovered !== 1 ? "s" : ""} synced`);
      queryClient.invalidateQueries({ queryKey: keys.prs });
      queryClient.invalidateQueries({ queryKey: keys.pendingCount });
    },
    onError: () => toast.error("Discover failed"),
  });
  const refreshAll = useMutation({
    mutationFn: api.prRefreshAll,
    onSuccess: (res) => {
      toast.success(`${res.updated} PR${res.updated !== 1 ? "s" : ""} refreshed`);
      queryClient.invalidateQueries({ queryKey: keys.prs });
    },
    onError: () => toast.error("Refresh failed"),
  });

  const setFilter = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p);
  };

  const watching = useMemo(() => {
    const list = data?.watching ?? [];
    return [...list].sort((a, b) => b.priority - a.priority);
  }, [data]);

  if (isLoading || !data) return <p>Loading…</p>;

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "0.5rem",
          marginBottom: "1rem",
        }}
      >
        <h2 style={{ margin: 0 }}>PRs</h2>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
          <span style={{ fontSize: "0.8em", color: "var(--color-muted)" }}>
            Last checked: {data.last_checked ?? "Never"}
          </span>
          <button
            style={btnSm}
            disabled={discover.isPending}
            onClick={() => discover.mutate()}
          >
            {discover.isPending ? "Searching…" : "↻ Discover PRs"}
          </button>
          <button
            style={btnSm}
            disabled={refreshAll.isPending}
            onClick={() => refreshAll.mutate()}
          >
            {refreshAll.isPending ? "Refreshing…" : "↻ Refresh all"}
          </button>
        </div>
      </div>

      {data.pending.length > 0 && (
        <details open style={{ marginBottom: "0.75rem" }}>
          <summary style={{ cursor: "pointer", listStyle: "none", padding: "0.35rem 0" }}>
            <SectionLabel text={`Pending — ${data.pending.length} new`} />
          </summary>
          <div style={{ border: "1px solid var(--color-border)", borderRadius: 6, padding: "0.5rem 1rem", marginTop: "0.4rem" }}>
            {data.pending.map((pr) => (
              <PendingRow key={`${pr.repo}#${pr.pr_number}`} pr={pr} />
            ))}
          </div>
        </details>
      )}

      <details open>
        <summary style={{ cursor: "pointer", listStyle: "none", padding: "0.35rem 0" }}>
          <SectionLabel text={`Watching${watching.length ? ` — ${watching.length}` : ""}`} />
        </summary>

        {(watching.length > 0 || repoFilter || authorFilter) && (
          <form
            onSubmit={(e) => e.preventDefault()}
            style={{
              display: "flex",
              gap: "0.75rem",
              flexWrap: "wrap",
              alignItems: "end",
              marginBottom: "0.75rem",
              marginTop: "0.5rem",
            }}
          >
            <div>
              <label style={{ fontSize: "0.75em", display: "block", marginBottom: "0.2rem", color: "var(--color-muted)" }}>
                Repo
              </label>
              <select value={repoFilter} onChange={(e) => setFilter("repo", e.target.value)}>
                <option value="">All repos</option>
                {data.all_repos.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: "0.75em", display: "block", marginBottom: "0.2rem", color: "var(--color-muted)" }}>
                Author
              </label>
              <select value={authorFilter} onChange={(e) => setFilter("author", e.target.value)}>
                <option value="">All authors</option>
                {data.all_authors.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            {(repoFilter || authorFilter) && (
              <button
                type="button"
                onClick={() => setParams({})}
                style={{ ...btnSm, fontSize: "0.78rem" }}
              >
                ✕ Clear
              </button>
            )}
          </form>
        )}

        {watching.length === 0 ? (
          <p style={{ color: "var(--color-muted)", fontSize: "0.88em" }}>
            No watched PRs{repoFilter || authorFilter ? " matching filters" : ""}.{" "}
            {data.pending.length === 0 && "Discover PRs to get started."}
          </p>
        ) : (
          watching.map((pr) => (
            <PrCard
              key={`${pr.repo}#${pr.pr_number}`}
              pr={pr}
              reviewModel={data.review_model}
              availableModels={data.available_models}
            />
          ))
        )}
      </details>

      {data.later.length > 0 && (
        <details style={{ marginTop: "0.75rem", border: "1px solid var(--color-border)", borderRadius: 6, padding: "0.6rem 1rem" }}>
          <summary style={{ cursor: "pointer", fontSize: "0.85em", color: "var(--color-muted)" }}>
            Later ({data.later.length})
          </summary>
          <div style={{ marginTop: "0.6rem" }}>
            {data.later.map((pr) => (
              <LaterRow key={`${pr.repo}#${pr.pr_number}`} pr={pr} />
            ))}
          </div>
        </details>
      )}

      {data.dismissed.length > 0 && (
        <details style={{ marginTop: "1.25rem", border: "1px solid var(--color-border)", borderRadius: 6, padding: "0.6rem 1rem" }}>
          <summary style={{ cursor: "pointer", fontSize: "0.85em", color: "var(--color-muted)" }}>
            Dismissed ({data.dismissed.length})
          </summary>
          <div style={{ marginTop: "0.6rem" }}>
            {data.dismissed.map((pr) => (
              <DismissedRow key={`${pr.repo}#${pr.pr_number}`} pr={pr} />
            ))}
          </div>
        </details>
      )}
    </>
  );
}
