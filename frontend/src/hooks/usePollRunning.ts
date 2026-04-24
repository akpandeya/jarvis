// Auto-refresh running CI every 5 minutes as long as at least one PR in the
// given list has ci_status === "running". Silent on error — the user still has
// the manual refresh button.

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys } from "../lib/queryClient";
import type { PrSubscription } from "../lib/types";

const FIVE_MINUTES = 5 * 60 * 1000;

export function usePollRunning(prs: PrSubscription[]) {
  const qc = useQueryClient();
  const hasRunning = prs.some((p) => p.ci_status === "running");

  useEffect(() => {
    if (!hasRunning) return;
    const id = window.setInterval(async () => {
      try {
        await api.prRefreshRunning();
      } catch {
        return;
      }
      qc.invalidateQueries({ queryKey: keys.prs });
      qc.invalidateQueries({ queryKey: keys.upcoming });
      qc.invalidateQueries({ queryKey: keys.pendingCount });
    }, FIVE_MINUTES);
    return () => window.clearInterval(id);
  }, [hasRunning, qc]);
}
