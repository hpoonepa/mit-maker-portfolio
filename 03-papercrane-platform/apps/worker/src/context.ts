/**
 * WorkerContext — the injected singleton passed into every per-job handler.
 *
 * Keeping it explicit (rather than importing prisma/redis directly inside
 * handlers) makes the processor trivially mockable in tests and gives us
 * one place to swap implementations (e.g. a NullEventPublisher in a local
 * dry-run harness).
 */

import type Redis from 'ioredis';
import type { PrismaClient } from '@papercrane/db';
import type { Logger } from '@papercrane/observability';
import type { EventPublisher } from './events';
import type { ProviderRegistry } from './providers/types';
import type { CancellationManager } from './cancellation';
import type { TransitionFn } from './transitions';
import type { R2Handle } from '@papercrane/storage';

export interface WorkerContext {
  prisma: PrismaClient;
  redis: Redis;
  logger: Logger;
  eventPublisher: EventPublisher;
  providers: ProviderRegistry;
  cancellation: CancellationManager;
  transitionJob: TransitionFn;
  /** Optional in dev; production Modal jobs fail closed when it is absent. */
  storage?: R2Handle;
}
