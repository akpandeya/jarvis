// CI/review status chips — rendered from cached subscription fields.

export function CiBadge({ status }: { status: string | null | undefined }) {
  if (status === "passed") return <span style={{ color: "var(--color-success)" }}>✓ CI Passed</span>;
  if (status === "failed") return <span style={{ color: "var(--color-danger)" }}>✗ CI Failed</span>;
  if (status === "running") return <span style={{ color: "var(--color-muted)" }}>⏳ Running</span>;
  return <span style={{ color: "var(--color-muted)" }}>–</span>;
}

export function ReviewBadge({ decision }: { decision: string | null | undefined }) {
  if (decision === "APPROVED") return <span style={{ color: "var(--color-success)" }}>✓ Approved</span>;
  if (decision === "CHANGES_REQUESTED")
    return <span style={{ color: "var(--color-danger)" }}>↩ Changes requested</span>;
  if (decision && decision !== "REVIEW_REQUIRED")
    return <span style={{ color: "var(--color-muted)" }}>{decision}</span>;
  return <span style={{ color: "var(--color-muted)" }}>Review pending</span>;
}

export function ClaudeVerdictBadge({
  verdict,
  mustFix,
  nits,
}: {
  verdict: string | null | undefined;
  mustFix: number | null | undefined;
  nits: number | null | undefined;
}) {
  if (!verdict) return null;
  const m = mustFix ?? 0;
  const n = nits ?? 0;
  let color = "var(--color-muted)";
  let icon = "🤖";
  let label = verdict;
  if (verdict === "lgtm") {
    color = "var(--color-success)";
    icon = "🟢";
    label = "LGTM";
  } else if (verdict === "lgtm-with-nits") {
    color = "var(--color-success)";
    icon = "🟡";
    label = `LGTM · ${n} nit${n === 1 ? "" : "s"}`;
  } else if (verdict === "appreciate-changes") {
    color = "var(--color-warning, #d4a017)";
    icon = "🟡";
    label = `${m} must-fix${n ? ` · ${n} nit${n === 1 ? "" : "s"}` : ""}`;
  } else if (verdict === "changes-requested") {
    color = "var(--color-danger)";
    icon = "🔴";
    label = `${m} must-fix`;
  }
  return (
    <span style={{ color }} title={`Claude verdict: ${verdict}`}>
      {icon} {label}
    </span>
  );
}
