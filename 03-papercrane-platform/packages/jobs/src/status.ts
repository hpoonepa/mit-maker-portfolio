/**
 * Canonical JobStatus enum + terminal-state helpers.
 *
 * Source of truth for the Paper Crane jobs state machine. Mirrors the
 * diagram in `docs/plans/01-core-platform.md` §5.
 *
 * NOTE: once `@papercrane/types` is populated, the `JobStatus` literal union
 * should be re-exported from there and imported here. For now it lives
 * locally because the types package is still a stub.
 */

import { TRANSITIONS } from './transitions';

export const JOB_STATUSES = [
  'queued',
  'preparing',
  'running',
  'partial',
  'succeeded',
  'failed',
  'cancelling',
  'cancelled',
  'purged',
] as const;

export type JobStatus = (typeof JOB_STATUSES)[number];

/** Terminal states: nothing leaves them (cancelled, purged) or only retention/retry (succeeded, failed). */
export const TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set<JobStatus>([
  'succeeded',
  'failed',
  'cancelled',
  'purged',
]);

/** Returns true if the status has no outbound worker transitions. */
export function isTerminal(status: JobStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

/** Pure predicate — does the state machine permit `from → to`? */
export function canTransition(from: JobStatus, to: JobStatus): boolean {
  return TRANSITIONS[from].includes(to);
}
