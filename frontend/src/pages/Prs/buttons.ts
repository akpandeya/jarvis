import type { CSSProperties } from "react";

export const btnSm: CSSProperties = {
  fontSize: "0.73rem",
  padding: "0.2rem 0.55rem",
  borderRadius: 4,
  whiteSpace: "nowrap",
  background: "none",
  border: "1px solid var(--color-border)",
  color: "var(--color-muted)",
  cursor: "pointer",
};

export const btnSmPrimary: CSSProperties = {
  ...btnSm,
  borderColor: "var(--color-primary)",
  color: "var(--color-primary)",
};

export const btnSmDanger: CSSProperties = {
  ...btnSm,
  borderColor: "var(--color-danger)",
  color: "var(--color-danger)",
};
