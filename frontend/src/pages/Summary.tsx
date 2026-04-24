import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

type Kind = "standup" | "weekly" | "context";

export default function Summary() {
  const [kind, setKind] = useState<Kind>("standup");
  const [days, setDays] = useState(1);
  const [trigger, setTrigger] = useState(0);

  const { data, isFetching, error } = useQuery({
    queryKey: ["summary", kind, days, trigger],
    queryFn: () => api.summary(kind, days),
    enabled: trigger > 0,
    staleTime: Infinity,
  });

  return (
    <>
      <h2>Summary</h2>

      <form
        onSubmit={(e) => e.preventDefault()}
        style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "end" }}
      >
        <select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
          <option value="standup">Standup</option>
          <option value="weekly">Weekly</option>
          <option value="context">Context</option>
        </select>
        <select value={days} onChange={(e) => setDays(+e.target.value)}>
          {[1, 3, 7, 14, 30].map((d) => (
            <option key={d} value={d}>
              Last {d} days
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setTrigger((t) => t + 1)}
          disabled={isFetching}
          style={{
            padding: "0.4rem 1rem",
            background: "var(--color-primary)",
            color: "#000",
            border: 0,
            borderRadius: 4,
            fontWeight: 600,
          }}
        >
          {isFetching ? "Generating…" : "Generate"}
        </button>
      </form>

      <article
        style={{
          marginTop: "1.5rem",
          padding: "1rem 1.25rem",
          border: "1px solid var(--color-border)",
          borderRadius: 6,
          lineHeight: 1.7,
        }}
      >
        {!trigger && (
          <p style={{ fontSize: "0.85em", color: "var(--color-muted)" }}>
            Click "Generate" to create a summary using Claude.
          </p>
        )}
        {error && <p style={{ color: "var(--color-danger)" }}>Failed to generate summary.</p>}
        {data && <div dangerouslySetInnerHTML={{ __html: data.html }} />}
      </article>
    </>
  );
}
