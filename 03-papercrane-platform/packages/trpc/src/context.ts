/**
 * tRPC context for Paper Crane.
 *
 * There are two flavours of context:
 *
 *   - "outer" context — built by the Fastify/Next adapter per HTTP request.
 *     Holds request/response refs and resolved auth, which the adapter
 *     determines from Authorization header or Supabase session cookie.
 *
 *   - "inner" context — what procedures actually consume. Exposes the
 *     dependencies needed to run business logic (prisma, withRlsUser,
 *     storage, queues). This separation lets tests build a lightweight
 *     inner context without touching HTTP.
 *
 * The inner factory also accepts overrides for every dependency so tests
 * can pass mocks. Production callers pass real implementations from
 * `@papercrane/db`, `@papercrane/jobs`, and `@papercrane/storage`.
 */
import type { PrismaClient, Prisma } from '@papercrane/db';
import { prisma as defaultPrisma, withRlsUser as defaultWithRlsUser } from '@papercrane/db';
import { JOB_QUEUE_NAMES, type JobQueueName, type Tier } from '@papercrane/jobs';
import type { ApiKeyScope } from '@papercrane/types';
import type { ToolCatalogEntry } from './routers/tools.js';

/**
 * Resolved auth principal. We reuse the shape from the tRPC layer rather
 * than `@papercrane/auth`'s principal types so the router stays decoupled
 * from the adapter's auth implementation.
 */
export interface UserAuth {
  kind: 'user';
  userId: string;
  orgId: string;
  orgSlug: string;
  tier: Tier;
  scopes: ApiKeyScope[];
}

export interface ApiKeyAuth {
  kind: 'apiKey';
  apiKeyId: string;
  orgId: string;
  orgSlug: string;
  tier: Tier;
  scopes: ApiKeyScope[];
  /** Synthetic user id used for RLS GUC (the key's owning user). */
  userId: string;
}

export type AuthContext = UserAuth | ApiKeyAuth;

/**
 * The `withRlsUser` signature, widened so tests can pass a bare mock.
 */
export type WithRlsUserFn = <T>(
  prisma: PrismaClient,
  userId: string,
  fn: (tx: Prisma.TransactionClient) => Promise<T>,
) => Promise<T>;

/** Enqueue a job onto a BullMQ tier queue. */
export type EnqueueJobFn = (
  queueName: JobQueueName,
  payload: { jobId: string; toolId: string; orgId: string },
) => Promise<void>;

/** Publish a cancellation signal on Redis pubsub — worker handles teardown. */
export type PublishCancelFn = (jobId: string) => Promise<void>;

/**
 * Presign a GET URL for a storage object. Defaults to a noop in tests.
 */
export type PresignGetFn = (key: string, ttlSec?: number) => Promise<string>;

/**
 * Presign a PUT URL for an upload. The content-type (and optionally length)
 * are bound into the signature server-side.
 */
export type PresignPutFn = (
  key: string,
  contentType: string,
  contentLength?: number,
  ttlSec?: number,
) => Promise<string>;

export interface InnerContext {
  auth: AuthContext | null;
  prisma: PrismaClient;
  withRlsUser: WithRlsUserFn;
  enqueueJob: EnqueueJobFn;
  publishCancel: PublishCancelFn;
  presignGet: PresignGetFn;
  presignPut: PresignPutFn;
  /** Public tool catalogue (injected so tests can control it). */
  tools: ToolCatalogEntry[];
  /** Clock, overridable in tests. */
  now: () => Date;
}

export interface CreateInnerContextOptions {
  auth?: AuthContext | null;
  prisma?: PrismaClient;
  withRlsUser?: WithRlsUserFn;
  enqueueJob?: EnqueueJobFn;
  publishCancel?: PublishCancelFn;
  presignGet?: PresignGetFn;
  presignPut?: PresignPutFn;
  tools?: ToolCatalogEntry[];
  now?: () => Date;
}

const defaultEnqueue: EnqueueJobFn = async () => {
  // In tests and contexts without a Redis connection this is a noop; the
  // real implementation lives in `apps/api` and wires BullMQ.
};

const defaultPublishCancel: PublishCancelFn = async () => {
  // Noop default — the API wires a real Redis pubsub publisher.
};

const defaultPresignGet: PresignGetFn = async (key) => `https://signed.example/${key}`;
const defaultPresignPut: PresignPutFn = async (key) => `https://signed.example/put/${key}`;

export function createInnerContext(opts: CreateInnerContextOptions = {}): InnerContext {
  return {
    auth: opts.auth ?? null,
    prisma: opts.prisma ?? defaultPrisma,
    withRlsUser: opts.withRlsUser ?? (defaultWithRlsUser as unknown as WithRlsUserFn),
    enqueueJob: opts.enqueueJob ?? defaultEnqueue,
    publishCancel: opts.publishCancel ?? defaultPublishCancel,
    presignGet: opts.presignGet ?? defaultPresignGet,
    presignPut: opts.presignPut ?? defaultPresignPut,
    tools: opts.tools ?? [],
    now: opts.now ?? (() => new Date()),
  };
}

/**
 * Factory invoked by the Fastify adapter. Keeps the HTTP shape deliberately
 * permissive (`unknown`) so the tRPC package does not depend on Fastify types.
 */
export interface CreateContextOptions {
  req: { headers: Record<string, string | string[] | undefined> };
  res: unknown;
  /** Already-resolved auth, if the adapter has run auth middleware. */
  auth?: AuthContext | null;
  /** Optional overrides forwarded to `createInnerContext`. */
  overrides?: Omit<CreateInnerContextOptions, 'auth'>;
}

export type Context = InnerContext & {
  /** The raw request, available if a procedure needs headers or IP. */
  req: CreateContextOptions['req'];
};

export function createContext(opts: CreateContextOptions): Context {
  const inner = createInnerContext({ ...(opts.overrides ?? {}), auth: opts.auth ?? null });
  return { ...inner, req: opts.req };
}

/** Re-exported for adapters that need to know queue-name constants. */
export { JOB_QUEUE_NAMES };
