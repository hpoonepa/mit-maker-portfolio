import type { ToolManifest } from "@papercrane/types";

/**
 * Pragmatic ETA estimator for a pending job.
 *
 * Formula:
 *   etaSeconds = queueWaitSeconds
 *              + tool.compute.estimatedMinutes * 60 * ceil(totalDesigns / parallelism)
 *
 * `parallelism` defaults to the worker's bounded seed fan-out: two GPU runs or
 * four CPU runs, while respecting a larger explicit GPU count.
 */
export type EtaEstimateInput = {
  tool: Pick<ToolManifest, "compute">;
  totalDesigns: number;
  /** Jobs ahead in the tier's queue; defaults to 0. */
  queueDepth?: number;
  /** Average seconds per queued job; baseline 90s (tune later). */
  avgQueueJobSeconds?: number;
  /** Override parallelism; defaults to bounded worker seed fan-out. */
  parallelism?: number;
};

export type EtaEstimate = {
  etaSeconds: number;
  queueWaitSeconds: number;
  runSeconds: number;
  parallelism: number;
};

export function estimateEta(input: EtaEstimateInput): EtaEstimate {
  const designs = Math.max(0, Math.floor(input.totalDesigns));
  const defaultParallelism =
    input.tool.compute.gpuType.toUpperCase() === "CPU"
      ? 4
      : Math.max(2, input.tool.compute.gpuCount);
  const parallelism = Math.max(1, input.parallelism ?? defaultParallelism);
  const avgQueueSeconds = Math.max(0, input.avgQueueJobSeconds ?? 90);
  const queueDepth = Math.max(0, Math.floor(input.queueDepth ?? 0));

  const queueWaitSeconds = queueDepth * avgQueueSeconds;
  const perDesignSeconds = input.tool.compute.estimatedMinutes * 60;
  const runSeconds =
    designs > 0 ? Math.ceil(designs / parallelism) * perDesignSeconds : 0;

  return {
    etaSeconds: Math.round(queueWaitSeconds + runSeconds),
    queueWaitSeconds: Math.round(queueWaitSeconds),
    runSeconds: Math.round(runSeconds),
    parallelism,
  };
}

/**
 * Human-friendly duration: "2m 30s", "1h 12m", "< 1m".
 */
export function formatEta(seconds: number): string {
  if (seconds < 60) return "< 1m";
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins === 0 ? `${hours}h` : `${hours}h ${remMins}m`;
}
