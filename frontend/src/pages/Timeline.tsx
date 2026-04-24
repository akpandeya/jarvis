import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { keys, queryClient } from "../lib/queryClient";
import { SourceBadge } from "../components/SourceBadge";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import type { Event } from "../lib/types";

export function EventList({ events }: { events: Event[] }) {
  return (
    <>
      {events.map((e) => (
        <div
          key={e.id}
          style={{
            borderBottom: "1px solid var(--color-border-muted)",
            padding: "0.5rem 0",
          }}
        >
          <div>
            <SourceBadge source={e.source} />
            <strong style={{ marginLeft: "0.5rem" }}>{e.title?.slice(0, 100)}</strong>
          </div>
          <div style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
            {new Date(e.happened_at).toLocaleString()} · {e.kind}
            {e.project && <> · {e.project}</>}
            {e.url && (
              <>
                {" · "}
                <a href={e.url} target="_blank" rel="noreferrer">
                  link
                </a>
              </>
            )}
            {e.source === "claude_sessions" &&
              e.metadata &&
              typeof (e.metadata as { session_id?: string }).session_id === "string" && (
                <>
                  {" · "}
                  <a
                    href={`/chat?session=${(e.metadata as { session_id: string }).session_id}`}
                    style={{ fontSize: "0.8em" }}
                  >
                    ▶ Resume
                  </a>
                </>
              )}
          </div>
        </div>
      ))}
    </>
  );
}

export default function Timeline() {
  const [params, setParams] = useSearchParams();
  const source = params.get("source") ?? "";
  const project = params.get("project") ?? "";
  const days = +(params.get("days") ?? 14);
  const page = +(params.get("page") ?? 1);

  const { data, isLoading } = useQuery({
    queryKey: keys.timeline(days, source || null, project || null, page),
    queryFn: () => api.timeline({ days, source: source || null, project: project || null, page }),
  });

  const ingest = useMutation({
    mutationFn: api.ingest,
    onSuccess: (res) => {
      toast.success("Ingest completed");
      if (res.log) console.log(res.log);
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
    },
    onError: () => toast.error("Ingest failed"),
  });

  const setParam = (k: string, v: string) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    p.delete("page");
    setParams(p);
  };

  return (
    <>
      <h2 style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        Timeline
        {data && (
          <small style={{ fontWeight: 400, color: "var(--color-muted)" }}>
            ({data.total} events)
          </small>
        )}
        <button
          onClick={() => ingest.mutate()}
          disabled={ingest.isPending}
          style={{
            fontSize: "0.75rem",
            padding: "0.25rem 0.75rem",
            border: "1px solid var(--color-border)",
            borderRadius: 4,
            background: "none",
            color: "var(--color-muted)",
          }}
        >
          {ingest.isPending ? "⏳ Ingesting…" : "↻ Run Ingest"}
        </button>
      </h2>

      <form
        onSubmit={(e) => e.preventDefault()}
        style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "end" }}
      >
        <select
          value={source}
          onChange={(e) => setParam("source", e.target.value)}
        >
          <option value="">All sources</option>
          {(data?.sources ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          list="project-list"
          placeholder="All projects"
          value={project}
          onChange={(e) => setParam("project", e.target.value)}
          style={{ width: 220 }}
        />
        <datalist id="project-list">
          {(data?.projects ?? []).map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>
        <select
          value={days}
          onChange={(e) => setParam("days", e.target.value)}
        >
          {[1, 3, 7, 14, 30, 90].map((d) => (
            <option key={d} value={d}>
              Last {d} days
            </option>
          ))}
        </select>
      </form>

      <div style={{ marginTop: "1rem" }}>
        {isLoading && <p>Loading…</p>}
        {data && <EventList events={data.events} />}
        {data?.has_more && (
          <button
            onClick={() => setParam("page", String(page + 1))}
            style={{
              marginTop: "1rem",
              padding: "0.3rem 0.75rem",
              border: "1px solid var(--color-border)",
              borderRadius: 4,
              background: "none",
              color: "var(--color-muted)",
            }}
          >
            Load more
          </button>
        )}
      </div>
    </>
  );
}
