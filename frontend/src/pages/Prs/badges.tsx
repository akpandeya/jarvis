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
