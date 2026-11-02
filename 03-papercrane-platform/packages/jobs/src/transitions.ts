/**
 * JobStatus transition table + runtime guard.
 *
 * Models the state machine diagram in `docs/plans/01-core-platform.md` §5.
 *
 *   queued    → preparing, cancelled
 *   preparing → running, failed, cancelling
 *   running   → partial, succeeded, failed, cancelling
 *   partial   → succeeded, failed, cancelling    (continue path: partial→succeeded)
 *   cancelling→ cancelled
 *   succeeded → purged                            (retention cron)
 *   failed    → queued, purged                    (queued = retry)
 *   cancelled → —
 *   purged    → —
 */

import type { JobStatus } from './status';

export const TRANSITIONS: Record<JobStatus, readonly JobStatus[]> = {
  queued: ['preparing', 'cancelled'],
  preparing: ['running', 'failed', 'cancelling'],
  running: ['partial', 'succeeded', 'failed', 'cancelling'],
  partial: ['succeeded', 'failed', 'cancelling'],
  cancelling: ['cancelled'],
  succeeded: ['purged'],
  failed: ['queued', 'purged'],
  cancelled: [],
  purged: [],
};

/** Thrown by `transition()` when `from → next` is not permitted. */
export class IllegalTransitionError extends Error {
  readonly from: JobStatus;
  readonly next: JobStatus;

  constructor(from: JobStatus, next: JobStatus) {
    super(
      `Illegal job transition: ${from} → ${next}. ` +
        `Allowed from '${from}': [${TRANSITIONS[from].join(', ') || '(terminal)'}]`,
    );
    this.name = 'IllegalTransitionError';
    this.from = from;
    this.next = next;
  }
}

/**
 * Guarded transition: returns `next` if the transition is legal,
 * otherwise throws `IllegalTransitionError`.
 *
 * Use this in the worker/orchestrator whenever a status write is
 * about to happen — it's the single runtime enforcement point.
 */
export function transition(current: JobStatus, next: JobStatus): JobStatus {
  if (!TRANSITIONS[current].includes(next)) {
    throw new IllegalTransitionError(current, next);
  }
  return next;
}
