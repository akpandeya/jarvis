import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys } from "../lib/queryClient";

export function PendingBadge() {
  const { data } = useQuery({
    queryKey: keys.pendingCount,
    queryFn: () => api.prPendingCount(),
    refetchInterval: 120_000,
  });
  const count = data?.count ?? 0;
  if (!count) return null;
  return (
    <span
      style={{
        display: "inline-block",
        background: "var(--color-danger)",
        color: "#fff",
        borderRadius: 10,
        fontSize: "0.65em",
        fontWeight: 700,
        padding: "0.05rem 0.4rem",
        marginLeft: "0.25rem",
        lineHeight: 1.4,
        verticalAlign: "middle",
      }}
    >
      {count}
    </span>
  );
}
