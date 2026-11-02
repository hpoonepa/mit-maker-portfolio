/**
 * Event publisher — writes per-job events to Redis pubsub (`job:${jobId}`)
 * so the API's SSE handler can fan them out to connected clients.
 *
 * Each event is validated + serialized via `@papercrane/jobs` before hitting
 * the wire. That's the single source of truth for the schema; if the
 * publisher skips validation clients will eventually get garbage.
 */

import type Redis from 'ioredis';
import type { JobEvent } from '@papercrane/jobs';
import { serializeEvent } from '@papercrane/jobs';
import type { Logger } from '@papercrane/observability';

export interface EventPublisher {
  publish(jobId: string, event: JobEvent): Promise<void>;
}

export function jobChannel(jobId: string): string {
  return `job:${jobId}`;
}

export class RedisEventPublisher implements EventPublisher {
  constructor(
    private readonly redis: Redis,
    private readonly logger: Logger,
  ) {}

  async publish(jobId: string, event: JobEvent): Promise<void> {
    const wire = serializeEvent(event);
    try {
      await this.redis.publish(jobChannel(jobId), wire);
    } catch (err) {
      // Publish failures must not kill the job. Log and continue — the DB
      // row is the canonical state; SSE is best-effort cache.
      this.logger.error({ jobId, err }, 'failed to publish job event');
    }
  }
}
