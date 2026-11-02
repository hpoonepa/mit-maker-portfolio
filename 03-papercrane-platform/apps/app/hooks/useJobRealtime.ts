"use client";

import { useEffect, useState } from "react";

import { subscribeToPgChanges } from "@/lib/realtime/supabase-rt";

export type JobStatus =
  | "PENDING"
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

interface JobRow {
  id: string;
  status: JobStatus;
  progress?: number | null;
  updated_at?: string;
  finished_at?: string | null;
}

export interface UseJobRealtimeResult {
  status: JobStatus | null;
  progress: number | null;
  lastUpdate: Date | null;
  error: Error | null;
}

/**
 * Subscribe to live status/progress updates for a single job.
 *
 * Pass `initialStatus` so the UI does not flash "unknown" before the first
 * realtime payload arrives. The hook only fires for the requested job id -
 * RLS additionally enforces that the row belongs to the user's org.
 */
export function useJobRealtime(
  jobId: string | null | undefined,
  initialStatus: JobStatus | null = null,
  initialProgress: number | null = null
): UseJobRealtimeResult {
  const [status, setStatus] = useState<JobStatus | null>(initialStatus);
  const [progress, setProgress] = useState<number | null>(initialProgress);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!jobId) return;

    // Reset to seeded values when jobId changes so the previous job's
    // status/progress doesn't leak into the new job until the first payload.
    setStatus(initialStatus);
    setProgress(initialProgress);
    setLastUpdate(null);
    setError(null);

    const unsubscribe = subscribeToPgChanges<JobRow>({
      channelName: `rt:jobs:${jobId}`,
      table: "jobs",
      event: "UPDATE",
      filter: `id=eq.${jobId}`,
      onChange: (payload) => {
        const row = payload.new as Partial<JobRow> | undefined;
        if (!row) return;
        if (row.status) setStatus(row.status);
        if (typeof row.progress === "number") setProgress(row.progress);
        setLastUpdate(new Date());
      },
      onError: (err) => setError(err),
    });

    return unsubscribe;
    // initialStatus/initialProgress intentionally excluded: they are seed
    // values, not reactive inputs. Including them would re-subscribe on
    // every parent re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return { status, progress, lastUpdate, error };
}
