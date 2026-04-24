import type { CSSProperties } from "react";

const accounts: Record<string, [string, string]> = {
  work: ["var(--color-acct-work)", "var(--color-acct-work-fg)"],
  personal: ["var(--color-acct-personal)", "var(--color-acct-personal-fg)"],
};

export function AccountBadge({ account }: { account: string }) {
  const [bg, fg] =
    accounts[account] ?? [
      "var(--color-acct-default)",
      "var(--color-acct-default-fg)",
    ];
  const style: CSSProperties = {
    display: "inline-block",
    padding: "0.1rem 0.45rem",
    borderRadius: 4,
    fontSize: "0.75em",
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    background: bg,
    color: fg,
  };
  return <span style={style}>{account}</span>;
}
