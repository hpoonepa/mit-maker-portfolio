import type { FastifyInstance, FastifyRequest } from "fastify";
import type { PrismaClient } from "@papercrane/db";
import type Stripe from "stripe";
import type Redis from "ioredis";
import {
  AuthError,
  ForbiddenError,
  requireScope,
  type ApiKeyScope,
} from "@papercrane/auth";
import { resolveOrgId } from "../../context.js";
import { runWithTenant } from "../../middleware/tenantRLS.js";
import {
  buildTenantTxRunner,
  consumeSeed,
  type OverageRecorder,
} from "../../services/seedMeter.js";

/**
 * Seed-metering HTTP surface.
 *
 *   POST /v1/seeds/consume   — worker-facing, idempotent, per-seed debit.
 *
 * All HTTP concerns (header parsing, status mapping, scope checks) live here.
 * The actual business logic lives in `services/seedMeter.ts`.
 *
 * Plan 05 §3 pins this route as the write-path for the seed counter; the
 * read-path is `/v1/usage/current` in `routes/rest/usage.ts`.
 */

export interface SeedRoutesDeps {
  prisma: PrismaClient;
  /** Optional — when omitted, overage billing is logged but not pushed to Stripe. */
  stripe?: Stripe;
  /** Optional — used for the SETNX guard that dedups overage records per minute. */
  redis?: Redis;
}

/**
 * Build the optional overage recorder. Returns undefined when stripe/redis
 * aren't wired (dev/test bootstrap). When wired, the recorder calls Stripe's
 * metered usage API with an Idempotency-Key derived from the worker's
 * Idempotency-Key, plus a Redis SETNX guard to prevent same-minute replays.
 */
function buildOverageRecorder(
  stripe: Stripe | undefined,
  redis: Redis | undefined,
): OverageRecorder | undefined {
  if (!stripe || !redis) return undefined;
  return {
    acquireOnce: async (key, ttlSec) => {
      const result = await redis.set(key, "1", "EX", ttlSec, "NX");
      return result === "OK";
    },
    recordUsage: async ({ subscriptionItemId, quantity, timestamp, idempotencyKey }) => {
      const record = await stripe.subscriptionItems.createUsageRecord(
        subscriptionItemId,
        { quantity, timestamp, action: "increment" },
        { idempotencyKey },
      );
      return { id: record.id };
    },
  };
}

// `usage:write` is the scope required by the worker to debit a seed. It's now
// part of `ApiKeyScopeSchema` (@papercrane/types/auth) so we use it directly.
const USAGE_WRITE_SCOPE: ApiKeyScope = "usage:write";

/**
 * Thrown when the Idempotency-Key header is absent. Mapped to 422 below.
 * We use a plain subclass of Error rather than AuthError so the generic
 * errorHandler passes through our custom status code + `error` field.
 */
class IdempotencyKeyMissingError extends Error {
  public readonly statusCode = 422;
  public readonly code = "idempotency_key_required";
  constructor() {
    super("Idempotency-Key header is required for POST /v1/seeds/consume");
  }
}

function extractIdempotencyKey(req: FastifyRequest): string {
  const raw = req.headers["idempotency-key"];
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new IdempotencyKeyMissingError();
  }
  return value.trim();
}

export async function registerSeedRoutes(
  app: FastifyInstance,
  deps: SeedRoutesDeps,
): Promise<void> {
  app.post(
    "/v1/seeds/consume",
    {
      config: {
        // Worker-driven endpoint — bucketed per-org (not per-key) at the
        // class limits defined in DEFAULT_RATE_LIMIT.classes['seeds-consume']
        // (plan 05 §3: free 5/min, pro 200/min, frontier unthrottled).
        rateLimit: { endpointClass: "seeds-consume" },
      },
    },
    async (req, reply) => {
      // Auth + scope. Worker calls come in with an API key that has
      // `usage:write`; user-session calls bypass scope checks by design
      // (`requireScope` short-circuits for `kind === 'user'`).
      if (!req.auth) throw new AuthError("auth required", "auth_required");
      requireScope(req.auth, USAGE_WRITE_SCOPE);

      const orgId = resolveOrgId(req.auth);
      if (!orgId) throw new AuthError("org required", "org_required");

      // Idempotency header MUST be present — this is how the worker makes
      // retries safe. Missing header is a 422 (unprocessable entity) rather
      // than 400; the payload itself may still be valid.
      const idempotencyKey = extractIdempotencyKey(req);

      // Cross-check the body.orgId against the authenticated principal's
      // orgId. A key scoped to org A should not be able to debit org B even
      // if the caller types org B's uuid into the body.
      const body = req.body as { orgId?: string } | undefined;
      if (body && typeof body.orgId === "string" && body.orgId !== orgId) {
        throw new ForbiddenError(
          "body.orgId does not match authenticated org",
          "org_mismatch",
        );
      }

      // Tenant-scoped transaction runner. `runWithTenant` already opens an
      // interactive Prisma transaction with RLS bound to the request's uid,
      // so the service layer runs its debit + counter + idempotency writes
      // atomically against a single connection.
      const runInTenantTx = buildTenantTxRunner({
        prisma: deps.prisma,
        runWithTenant: (fn) => runWithTenant(req, deps.prisma, fn),
      });

      const result = await consumeSeed({
        input: req.body,
        idempotencyKey,
        runInTenantTx,
        logger: req.log,
        overage: buildOverageRecorder(deps.stripe, deps.redis),
      });

      if ("quotaExceeded" in result && result.quotaExceeded) {
        void reply.code(402);
        return { error: "QUOTA_EXCEEDED", remaining: 0 };
      }

      return {
        seedId: result.seedId,
        counted: result.counted,
        remainingInPeriod: result.remainingInPeriod,
        periodResetsAt: result.periodResetsAt,
      };
    },
  );
}
