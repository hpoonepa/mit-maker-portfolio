import type { FastifyBaseLogger, FastifyRequest } from "fastify";
import type { Prisma, PrismaClient } from "@papercrane/db";
import { withRlsUser } from "@papercrane/db";
import { createR2Client, presignGet as r2PresignGet, presignPut as r2PresignPut } from "@papercrane/storage";
import type { AuthContext } from "@papercrane/auth";
import { Queue } from "bullmq";
import type Redis from "ioredis";
import type {
  EnqueueJobFn,
  PresignGetFn,
  PresignPutFn,
  PublishCancelFn,
} from "@papercrane/trpc";

type WithRlsUserFn = <T>(
  prisma: PrismaClient,
  userId: string,
  fn: (tx: Prisma.TransactionClient) => Promise<T>,
) => Promise<T>;

// Dev-mode no-op defaults for the tRPC inner-context helpers. Production
// wires real implementations (BullMQ enqueue, Redis pubsub, R2 presign);
// in dev these stubs return fake-but-shaped values so routers don't crash.
const stubEnqueue: EnqueueJobFn = async () => {};
const stubPublishCancel: PublishCancelFn = async () => {};
const stubPresignGet: PresignGetFn = async (key) =>
  `http://localhost:3001/dev-stub/get/${encodeURIComponent(key)}`;
const stubPresignPut: PresignPutFn = async (key) =>
  `http://localhost:3001/dev-stub/put/${encodeURIComponent(key)}`;

/**
 * Per-request context. Built once at the start of request handling and passed
 * (directly or via `req.ctx`) down into route handlers and tRPC procedures.
 *
 * Shape mirrors what tRPC procedures expect so we can pass the same object to
 * both REST handlers and the tRPC plugin without wrapping.
 */
export interface RequestContext {
  logger: FastifyBaseLogger;
  prisma: PrismaClient;
  /** Resolved identity, or undefined for unauthenticated requests. */
  auth?: AuthContext;
  /** Convenience accessors lifted from `auth` for tRPC consumers. */
  orgId?: string;
  userId?: string;
  tier?: "free" | "pro" | "frontier";
  scopes: readonly string[];
  /** RLS-bound transaction helper used by tRPC routers. */
  withRlsUser: WithRlsUserFn;
  /** Storage + queue helpers required by tRPC inner context. Dev defaults
   *  ship no-op stubs; prod wires R2 + BullMQ + Redis pubsub. */
  enqueueJob: EnqueueJobFn;
  publishCancel: PublishCancelFn;
  presignGet: PresignGetFn;
  presignPut: PresignPutFn;
  /** Catalog + clock — required by tRPC procedures. */
  tools: never[];
  now: () => Date;
}

export interface BuildContextDeps {
  prisma: PrismaClient;
  redis?: Redis | null;
}

const queueCache = new Map<string, Queue>();

function queueFor(name: string, redis: Redis): Queue {
  const cached = queueCache.get(name);
  if (cached) return cached;
  const q = new Queue(name, { connection: redis });
  queueCache.set(name, q);
  return q;
}

/**
 * Build a {@link RequestContext} from a Fastify request. Called after auth
 * middleware has set `req.auth` (which may be undefined for public routes).
 */
export function buildRequestContext(
  req: FastifyRequest,
  deps: BuildContextDeps,
): RequestContext {
  const auth = req.auth;
  let r2: ReturnType<typeof createR2Client> | null = null;
  const getR2 = () => {
    if (r2) return r2;
    r2 = createR2Client();
    return r2;
  };
  const ctx: RequestContext = {
    logger: req.log,
    prisma: deps.prisma,
    auth,
    scopes: [],
    withRlsUser,
    enqueueJob: deps.redis
      ? async (queueName, payload) => {
          await queueFor(queueName, deps.redis!).add(payload.jobId, payload, {
            removeOnComplete: 1000,
            removeOnFail: 5000,
            attempts: 1,
          });
        }
      : stubEnqueue,
    publishCancel: deps.redis
      ? async (jobId) => {
          await deps.redis!.publish("jobs:cancel", jobId);
        }
      : stubPublishCancel,
    presignGet: async (key, ttlSec) => {
      try {
        return await r2PresignGet(getR2(), key, ttlSec);
      } catch {
        return stubPresignGet(key, ttlSec);
      }
    },
    presignPut: async (key, contentType, contentLength, ttlSec) => {
      try {
        return await r2PresignPut(getR2(), key, contentType, contentLength, ttlSec);
      } catch {
        return stubPresignPut(key, contentType, contentLength, ttlSec);
      }
    },
    tools: [],
    now: () => new Date(),
  };

  if (!auth) return ctx;

  if (auth.kind === "apiKey") {
    ctx.orgId = auth.orgId;
    ctx.tier = auth.tier;
    ctx.scopes = auth.scopes;
  } else {
    ctx.userId = auth.userId;
    ctx.orgId = auth.orgId;
    ctx.tier = auth.tier;
  }

  return ctx;
}

/**
 * Convenience: pull the effective orgId off an auth context, or undefined for
 * user sessions that haven't joined an org yet. Used by route handlers that
 * need the scoping key without caring which principal kind they have.
 */
export function resolveOrgId(auth: AuthContext | undefined): string | undefined {
  if (!auth) return undefined;
  return auth.kind === "apiKey" ? auth.orgId : auth.orgId;
}

// Fastify module augmentation — `req.auth` and `req.ctx` added by middleware.
declare module "fastify" {
  interface FastifyRequest {
    auth?: AuthContext;
    ctx?: RequestContext;
  }
}
