import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys } from "../lib/queryClient";
import { SourceBadge } from "../components/SourceBadge";

export default function Sessions() {
  const { data, isLoading, error } = useQuery({
    queryKey: keys.sessions,
    queryFn: api.sessions,
  });

  if (isLoading) return <p>Loading…</p>;
  if (error) return <p style={{ color: "var(--color-danger)" }}>Failed to load sessions.</p>;

  const sessions = data?.sessions ?? [];
  const claude = (data?.claude_sessions ?? []).filter((s) => s.session_id);

  return (
    <>
      <h2>Sessions</h2>

      {sessions.length === 0 ? (
        <p>
          No sessions recorded yet. Run <code>jarvis session save</code> to
          capture one.
        </p>
      ) : (
        sessions.map((s) => (
          <article
            key={s.id}
            style={{
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              padding: "0.8rem 1rem",
              marginBottom: "0.75rem",
            }}
          >
            <header style={{ marginBottom: "0.4rem" }}>
              <strong>{s.started_at.slice(0, 16)}</strong>
              {s.project && (
                <span style={{ marginLeft: "0.5rem" }}>
                  <SourceBadge source="github" />
                  <span style={{ marginLeft: "0.3rem" }}>{s.project}</span>
                </span>
              )}
            </header>
            <p>{s.context}</p>
          </article>
        ))
      )}

      {claude.length > 0 && (
        <>
          <h3 style={{ marginTop: "2rem" }}>Claude Code Sessions</h3>
          <p style={{ fontSize: "0.85em", color: "var(--color-muted)", marginBottom: "1rem" }}>
            Recent Claude Code conversations ingested from <code>~/.claude/projects/</code>. Click ▶
            Resume to continue in the Chat panel.
          </p>
          {claude.map((s) => (
            <article
              key={s.session_id!}
              style={{
                marginBottom: "0.6rem",
                padding: "0.65rem 1rem",
                border: "1px solid var(--color-border)",
                borderRadius: 6,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "0.5rem",
                flexWrap: "wrap",
              }}
            >
              <div>
                <div style={{ fontSize: "0.9em" }}>
                  {(s.title || "(untitled)").slice(0, 120)}
                </div>
                <div
                  style={{
                    fontSize: "0.78em",
                    color: "var(--color-muted)",
                    marginTop: "0.2rem",
                  }}
                >
                  {s.happened_at?.slice(0, 16) ?? ""}
                  {s.branch && (
                    <>
                      {" · "}
                      <code>{s.branch}</code>
                    </>
                  )}
                  {s.turns != null && ` · ${s.turns} turns`}
                </div>
              </div>
              <a
                href={`/chat?session=${encodeURIComponent(s.session_id!)}`}
                role="button"
                style={{
                  fontSize: "0.75rem",
                  padding: "0.2rem 0.6rem",
                  whiteSpace: "nowrap",
                  border: "1px solid var(--color-primary)",
                  borderRadius: 4,
                }}
              >
                ▶ Resume
              </a>
            </article>
          ))}
        </>
      )}
    </>
  );
}
