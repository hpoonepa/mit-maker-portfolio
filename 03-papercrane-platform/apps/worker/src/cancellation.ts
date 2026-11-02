/**
 * Cooperative cancellation manager.
 *
 * The orchestrator publishes `pc:cancel:<jobId>` to Redis when a user hits
 * `POST /v1/jobs/:id/cancel`. A single subscriber in this worker process
 * flips an in-memory flag via `cancel(jobId)`. The job processor calls
 * `isCancelled(jobId)` between seeds — if true it flushes completed work
 * and transitions to `cancelled`.
 *
 * Plan 01 §5: "Cancellation is cooperative: sets status='cancelling',
 * worker checks flag every seed, flushes completed designs, transitions
 * to cancelled."
 */

import type Redis from 'ioredis';

export const CANCEL_CHANNEL_PATTERN = 'pc:cancel:*';

export function cancelChannel(jobId: string): string {
  return `pc:cancel:${jobId}`;
}

export class CancellationManager {
  private readonly cancelled = new Set<string>();

  cancel(jobId: string): void {
    this.cancelled.add(jobId);
  }

  isCancelled(jobId: string): boolean {
    return this.cancelled.has(jobId);
  }

  clear(jobId: string): void {
    this.cancelled.delete(jobId);
  }

  size(): number {
    return this.cancelled.size;
  }
}

/**
 * Subscribe to `pc:cancel:*` on a dedicated Redis connection. Returns a
 * `dispose` that unsubscribes and resolves when the subscriber is quiet.
 *
 * IMPORTANT: the Redis instance used for pSubscribe *must not* be reused
 * for normal commands — ioredis enters subscriber mode and blocks other
 * commands. Pass in a cloned connection (`redis.duplicate()`).
 */
export async function attachCancellationListener(
  subscriber: Redis,
  manager: CancellationManager,
  onMessage?: (jobId: string) => void,
): Promise<() => Promise<void>> {
  await subscriber.psubscribe(CANCEL_CHANNEL_PATTERN);
  const handler = (_pattern: string, channel: string, _message: string): void => {
    const jobId = channel.slice('pc:cancel:'.length);
    if (!jobId) return;
    manager.cancel(jobId);
    onMessage?.(jobId);
  };
  subscriber.on('pmessage', handler);

  return async () => {
    subscriber.off('pmessage', handler);
    try {
      await subscriber.punsubscribe(CANCEL_CHANNEL_PATTERN);
    } catch {
      // subscriber may already be closed on shutdown
    }
  };
}
