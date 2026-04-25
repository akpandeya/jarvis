import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../../lib/api";
import type { ActiveSprint, JiraTicket } from "../../lib/types";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

function TicketButton({ t, host }: { t: JiraTicket; host: string }) {
  const open = useMutation({
    mutationFn: () => api.openUrl(t.url, { jira_host: host }),
    onError: () => toast.error(`Failed to open ${t.key}`),
  });
  const statusColour =
    t.status.toLowerCase().includes("progress") || t.status.toLowerCase().includes("review")
      ? "var(--color-primary)"
      : "var(--color-muted)";
  return (
    <button
      onClick={() => open.mutate()}
      title={t.summary || t.key}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "0.4rem",
        fontSize: "0.78em",
        padding: "0.2rem 0.55rem",
        marginRight: "0.35rem",
        marginBottom: "0.35rem",
        background: "none",
        border: "1px solid var(--color-border)",
        borderRadius: 4,
        color: "var(--color-text)",
        cursor: "pointer",
        maxWidth: "100%",
      }}
    >
      <span
        style={{
          fontWeight: 600,
          color: "var(--color-primary)",
          whiteSpace: "nowrap",
        }}
      >
        ↗ {t.key}
      </span>
      <span
        style={{
          fontSize: "0.88em",
          color: statusColour,
          whiteSpace: "nowrap",
        }}
      >
        {t.status}
      </span>
      <span
        style={{
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          maxWidth: "24rem",
          color: "var(--color-muted)",
        }}
      >
        {t.summary}
      </span>
    </button>
  );
}

function Bucket({
  label,
  tickets,
  host,
  initialLimit,
  muted,
}: {
  label: string;
  tickets: JiraTicket[];
  host: string; // "" means derive per-ticket from t.url
  initialLimit: number;
  muted?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  if (tickets.length === 0) return null;
  const shown = expanded ? tickets : tickets.slice(0, initialLimit);
  const hidden = tickets.length - shown.length;

  return (
    <div style={{ marginTop: "0.75rem" }}>
      <div
        style={{
          fontSize: "0.72em",
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: muted ? "var(--color-muted)" : "var(--color-text)",
          marginBottom: "0.4rem",
        }}
      >
        {label} ({tickets.length})
      </div>
      <div style={{ display: "flex", flexWrap: "wrap" }}>
        {shown.map((t) => (
          <TicketButton key={t.key} t={t} host={host || hostOf(t.url)} />
        ))}
        {hidden > 0 && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            style={{
              fontSize: "0.75em",
              padding: "0.2rem 0.55rem",
              marginBottom: "0.35rem",
              background: "none",
              border: "1px dashed var(--color-border)",
              borderRadius: 4,
              color: "var(--color-muted)",
              cursor: "pointer",
            }}
          >
            + {hidden} more
          </button>
        )}
      </div>
    </div>
  );
}

export function ActiveSprintSection({
  sprints,
  recent,
}: {
  sprints: ActiveSprint[];
  recent: JiraTicket[];
}) {
  const hasSprints = sprints && sprints.length > 0;
  const hasRecent = recent && recent.length > 0;
  if (!hasSprints && !hasRecent) return null;

  return (
    <section style={{ marginTop: "2rem", marginBottom: "1.5rem" }}>
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
        Jira
      </div>

      {sprints.map((s) => (
        <div
          key={s.board_id}
          style={{
            marginBottom: "1.25rem",
            padding: "0.85rem 1rem",
            border: "1px solid var(--color-border)",
            borderRadius: 6,
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: "0.75rem",
              flexWrap: "wrap",
            }}
          >
            <div style={{ fontWeight: 600 }}>
              {s.nickname}
              {s.sprint_name ? (
                <span style={{ color: "var(--color-muted)", fontWeight: 400 }}>
                  {" — "}
                  {s.sprint_name}
                </span>
              ) : null}
            </div>
            <div
              style={{
                fontSize: "0.78em",
                color: "var(--color-muted)",
              }}
            >
              {s.host}
            </div>
          </div>
          <Bucket
            label="Mine"
            tickets={s.mine}
            host={s.host}
            initialLimit={s.mine.length}
          />
          <Bucket
            label="Unassigned"
            tickets={s.unassigned}
            host={s.host}
            initialLimit={5}
            muted
          />
          <Bucket
            label="Others"
            tickets={s.others}
            host={s.host}
            initialLimit={3}
            muted
          />
        </div>
      ))}

      {hasRecent && (
        <div
          style={{
            marginBottom: "1.25rem",
            padding: "0.85rem 1rem",
            border: "1px solid var(--color-border)",
            borderRadius: 6,
          }}
        >
          <div style={{ fontWeight: 600 }}>
            Recent tickets{" "}
            <span style={{ color: "var(--color-muted)", fontWeight: 400 }}>
              — touched lately, not on a watched sprint
            </span>
          </div>
          <Bucket label="Recent" tickets={recent} host="" initialLimit={8} />
        </div>
      )}
    </section>
  );
}
