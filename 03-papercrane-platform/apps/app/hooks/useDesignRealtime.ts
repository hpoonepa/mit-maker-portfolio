"use client";

import { useEffect, useState } from "react";

import { subscribeToPgChanges } from "@/lib/realtime/supabase-rt";

export interface DesignRow {
  id: string;
  job_id: string;
  org_id: string;
  seed: number;
  rank: number | null;
  sequence: string | null;
  iptm: number | null;
  ipsae: number | null;
  created_at: string;
}

export interface UseDesignRealtimeResult {
  designs: DesignRow[];
  error: Error | null;
}

/**
 * Append-only stream of designs created for `jobId`. New rows arrive as the
 * worker writes them, so the job page can render a growing table without
 * polling. Existing designs (loaded by SSR/tRPC) should be passed via
 * `initialDesigns` to seed state.
 */
export function useDesignRealtime(
  jobId: string | null | undefined,
  initialDesigns: DesignRow[] = []
): UseDesignRealtimeResult {
  const [designs, setDesigns] = useState<DesignRow[]>(initialDesigns);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!jobId) return;

    const unsubscribe = subscribeToPgChanges<DesignRow>({
      channelName: `rt:designs:${jobId}`,
      table: "designs",
      event: "INSERT",
      filter: `job_id=eq.${jobId}`,
      onChange: (payload) => {
        const row = payload.new as Partial<DesignRow> | undefined;
        if (!row?.id) return;
        const full = row as DesignRow;
        setDesigns((prev) => {
          // Idempotent: ignore if we've already seen this id (e.g. SSR seed
          // happened to include the same row).
          if (prev.some((d) => d.id === full.id)) return prev;
          return [...prev, full];
        });
      },
      onError: (err) => setError(err),
    });

    return unsubscribe;
  }, [jobId]);

  return { designs, error };
}
