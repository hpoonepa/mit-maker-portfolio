/**
 * Retry policy for failed jobs.
 *
 * From plan 01 §5: "only on infrastructure errors (GPU preemption, network),
 * not user errors. Max 3 retries, exponential backoff."
 */

export const INFRA_ERROR_CODES = [
  'GPU_PREEMPT',
  'NETWORK_TIMEOUT',
  'CONTAINER_OOM',
  'PROVIDER_UNAVAILABLE',
  // Canonical codes emitted by the Python Modal apps.
  'OOM',
  'TIMEOUT',
  'INFRA_ERROR',
  'WORKER_STALLED',
] as const;

export const USER_ERROR_CODES = [
  'INVALID_INPUT',
  'BAD_PDB',
  'QUOTA_EXCEEDED',
  'RUNTIME_ERROR',
] as const;

export type InfraErrorCode = (typeof INFRA_ERROR_CODES)[number];
export type UserErrorCode = (typeof USER_ERROR_CODES)[number];
export type JobErrorCode = InfraErrorCode | UserErrorCode;

export interface JobError {
  code: JobErrorCode;
  message: string;
  /** Optional structured context from worker/orchestrator. */
  cause?: unknown;
}

export const MAX_RETRIES = 3;

const INFRA_SET: ReadonlySet<string> = new Set(INFRA_ERROR_CODES);

/**
 * Returns true iff this error is infra-retryable and we have not yet
 * exceeded `MAX_RETRIES`. `attempt` is 1-indexed and represents the
 * attempt number that *just failed*.
 */
export function shouldRetry(error: JobError, attempt: number): boolean {
  if (!Number.isFinite(attempt) || attempt < 1) return false;
  if (attempt > MAX_RETRIES) return false;
  return INFRA_SET.has(error.code);
}

/**
 * Exponential backoff in seconds, capped at 600s (10 minutes).
 *
 *   attempt 1 → 60s
 *   attempt 2 → 120s
 *   attempt 3 → 240s
 *   attempt 4+ → min(600, 60 * 2^(attempt-1))
 *
 * Formula: `min(600, 60 * 2 ** (attempt - 1))`.
 */
export function backoffSeconds(attempt: number): number {
  if (!Number.isFinite(attempt) || attempt < 1) return 0;
  return Math.min(600, 60 * Math.pow(2, attempt - 1));
}
