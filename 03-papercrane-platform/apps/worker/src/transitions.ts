/**
 * DB-aware wrapper around `transition()` from @papercrane/jobs.
 *
 * The pure state-machine guard lives in the jobs package; this module adds:
 *   1. Reads current status from `jobs` table.
 *   2. Validates `current → next` via `transition()` (throws IllegalTransitionError).
 *   3. Writes `jobs.status = next` + a `job_audits` row inside a single tx.
 *   4. Idempotent: if already at `next`, no-ops (no audit entry).
 *
 * The Prisma `JobAudit` model (packages/db/prisma/schema.prisma §480) was
 * added in the Wave-4 schema migration. Field names on the model are
 * `fromStatus` / `toStatus` / `actor` — the column map handles the
 * snake_case DB names.
 */

import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';
import { transition, type JobStatus } from '@papercrane/jobs';

export type TransitionFn = (
  jobId: string,
  next: JobStatus,
  opts?: {
    actor?: string;
    reason?: string;
    error?: {
      code: string;
      message: string;
      retryable?: boolean;
      attempt?: number;
      completedSeeds?: number;
    };
  },
) => Promise<void>;

export function makeTransitioner(prisma: PrismaClient, logger: Logger): TransitionFn {
  return async function transitionJob(jobId, next, opts) {
    const row = await prisma.job.findUnique({ where: { id: jobId } });
    if (!row) {
      throw new Error(`transitionJob: job not found: ${jobId}`);
    }

    const current = row.status as JobStatus;
    if (current === next) {
      // Idempotent — nothing to do, don't pollute the audit log.
      return;
    }

    // Throws IllegalTransitionError on invalid transitions. Bubble up.
    transition(current, next);

    await prisma.$transaction(async (tx) => {
      const data: Record<string, unknown> = { status: next };
      if (next === 'preparing' || next === 'running') {
        data.heartbeatAt = new Date();
      }
      if (next === 'running') {
        data.startedAt = row.startedAt ?? new Date();
      }
      if (next === 'succeeded' || next === 'failed' || next === 'cancelled') {
        data.completedAt = new Date();
      }
      if (next === 'failed' && opts?.error) {
        data.error = opts.error;
      }
      if (next === 'queued') {
        // A retry is a fresh attempt; stale terminal metadata must not leak
        // into the job summary while it waits for the next worker claim.
        data.completedAt = null;
        data.error = null;
      }

      // A cancellation or another worker may win after the initial read.
      // Never overwrite that state with an older transition.
      await tx.job.update({ where: { id: jobId, status: current }, data });
      await tx.jobAudit.create({
        data: {
          jobId,
          fromStatus: current,
          toStatus: next,
          actor: opts?.actor ?? 'system',
          reason: opts?.reason ?? null,
        },
      });
    });

    logger.info({ jobId, from: current, to: next }, 'job transitioned');
  };
}
