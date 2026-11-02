/**
 * Retry scheduler — requeues infra-failed jobs with exponential backoff.
 *
 * BullMQ has native retry via `attempts` + `backoff`, but we can't use that
 * directly: our retry policy depends on the *error code* (infra vs user),
 * which BullMQ has no concept of. So we catch the failure in the worker,
 * compute backoff via `@papercrane/jobs`, and schedule a new job with the
 * attempt counter bumped.
 */

import type { Queue } from 'bullmq';
import { backoffSeconds, shouldRetry, type JobError, jobQueueName, type Tier } from '@papercrane/jobs';
import type { Logger } from '@papercrane/observability';

export interface RequeueInput {
  jobId: string;
  tier: Tier;
  attempt: number;
  error: JobError;
}

/**
 * Returns true iff the job was requeued. Caller should transition the DB
 * row back to `queued` on true.
 */
export async function maybeRequeue(
  queues: Record<Tier, Queue>,
  input: RequeueInput,
  opts: { logger: Logger },
): Promise<boolean> {
  const { jobId, tier, attempt, error } = input;

  if (!shouldRetry(error, attempt)) {
    opts.logger.info({ jobId, attempt, code: error.code }, 'retry: not retryable, giving up');
    return false;
  }

  const delay = backoffSeconds(attempt) * 1000;
  const queue = queues[tier];
  const qname = jobQueueName(tier);

  await queue.add(
    'run-job',
    { jobId, attempt: attempt + 1 },
    {
      delay,
      jobId: `${jobId}:${attempt + 1}`, // BullMQ dedup
      removeOnComplete: false,
      removeOnFail: false,
    },
  );

  opts.logger.info(
    { jobId, attempt, nextAttempt: attempt + 1, delayMs: delay, queue: qname },
    'retry: requeued',
  );
  return true;
}
