import { NavLink } from "react-router-dom";
import { PendingBadge } from "./PendingBadge";

const items: { to: string; label: string; badge?: "pending-count" }[] = [
  { to: "/upcoming", label: "Focus" },
  { to: "/timeline", label: "Timeline" },
  { to: "/search", label: "Search" },
  { to: "/summary", label: "Summary" },
  { to: "/sessions", label: "Sessions" },
  { to: "/prs", label: "PRs", badge: "pending-count" },
  { to: "/chat", label: "Chat" },
  { to: "/insights", label: "Insights" },
  { to: "/settings", label: "Settings" },
];

export function Nav() {
  return (
    <nav
      style={{
        borderBottom: "1px solid var(--color-border)",
        padding: "0.75rem 1rem",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        background: "var(--color-bg-elev)",
      }}
    >
      <strong style={{ color: "var(--color-text)" }}>Jarvis</strong>
      <ul
        style={{
          display: "flex",
          gap: "1.25rem",
          listStyle: "none",
          margin: 0,
          padding: 0,
          fontSize: "0.92em",
        }}
      >
        {items.map((it) => (
          <li key={it.to}>
            <NavLink
              to={it.to}
              style={({ isActive }) => ({
                color: "var(--color-primary)",
                textDecoration: isActive ? "underline" : "none",
                fontWeight: isActive ? 700 : 400,
              })}
            >
              {it.label}
              {it.badge === "pending-count" && <PendingBadge />}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
