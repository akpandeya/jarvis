import type { CSSProperties } from "react";

const sources: Record<string, [string, string]> = {
  git_local: ["var(--color-src-git_local)", "var(--color-src-git_local-fg)"],
  github: ["var(--color-src-github)", "var(--color-src-github-fg)"],
  jira: ["var(--color-src-jira)", "var(--color-src-jira-fg)"],
  gcal: ["var(--color-src-gcal)", "var(--color-src-gcal-fg)"],
  kafka: ["var(--color-src-kafka)", "var(--color-src-kafka-fg)"],
};

export function SourceBadge({ source }: { source: string }) {
  const [bg, fg] = sources[source] ?? ["#3d3d3d", "#d1d5db"];
  const style: CSSProperties = {
    display: "inline-block",
    padding: "0.1rem 0.4rem",
    borderRadius: 4,
    fontSize: "0.8em",
    fontWeight: 600,
    background: bg,
    color: fg,
  };
  return <span style={style}>{source}</span>;
}
