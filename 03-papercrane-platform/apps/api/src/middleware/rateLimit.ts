import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import type Redis from "ioredis";

/**
 * Token-bucket rate limiter backed by Redis.
 *
 * Keying: `(principal_id, endpoint_class)`. principal_id is the api_key_id for
 * API-key requests and user_id for session requests. endpoint_class lets us
 * bucket heavy routes (job submission) separately from light ones (list
 * endpoints) — for now everything buckets to `default`.
 *
 * Implementation: a single INCR-with-expiry per window. Not a true token
 * bucket with smooth refill — it's a fixed-window counter, which is fine for
 * our 60/600-per-minute thresholds. If we need smoother shaping later we can
 * swap in a Lua script for the GCRA algorithm without changing callers.
 *
 * Tiers:
 *   free:     60 req/min
 *   pro:      600 req/min
 *   frontier: unlimited (bypass entirely)
 *
 * Anonymous (pre-auth) requests are limited by IP at a flat 30 req/min.
 */

export interface RateLimitConfig {
  windowSec: number;
  /** requests per window, per principal. */
  limits: {
    free: number;
    pro: number;
    frontier: number;
    /** Fallback when principal tier is unknown. */
    anonymous: number;
  };
  /**
   * Per-endpoint-class overrides, keyed by `endpointClass`. When the route's
   * `rateLimit.endpointClass` matches a key here, its tier-limits replace the
   * defaults AND the bucket is keyed by `(org_id, endpointClass)` so high-
   * volume routes (worker-driven `seeds-consume`) don't drain the same
   * bucket as light read endpoints.
   *
   * Plan 05 §3 wires `seeds-consume` to: free=5/min, pro=200/min,
   * frontier=unthrottled.
   */
  classes?: Record<string, RateLimitConfig["limits"]>;
}

export const DEFAULT_RATE_LIMIT: RateLimitConfig = {
  windowSec: 60,
  limits: {
    free: 60,
    pro: 600,
    frontier: Number.POSITIVE_INFINITY,
    anonymous: 30,
  },
  classes: {
    // POST /v1/seeds/consume — see plan 05 §3.
    "seeds-consume": {
      free: 5,
      pro: 200,
      frontier: Number.POSITIVE_INFINITY,
      anonymous: 5,
    },
    // Auth-adjacent / unauthenticated POSTs (Stripe webhook impostor attempts,
    // password-reset triggers, etc). 5/min/IP is enough headroom for legit
    // retries but throttles credential-stuffing. Wave 15.
    "auth": {
      free: 30,
      pro: 60,
      frontier: Number.POSITIVE_INFINITY,
      anonymous: 5,
    },
  },
};

export interface RateLimitDeps {
  redis: Redis;
  config?: RateLimitConfig;
}

interface Decision {
  allowed: boolean;
  remaining: number;
  resetSec: number;
}

function resolvePrincipalKey(
  req: FastifyRequest,
  perOrg: boolean,
): {
  key: string;
  tier: keyof RateLimitConfig["limits"];
} {
  const auth = req.auth;
  if (auth?.kind === "apiKey") {
    // For per-org-bucketed routes (e.g. seeds-consume), all keys belonging to
    // the same org share a single bucket — otherwise an org could fan out by
    // rotating API keys and bypass the org-level limit.
    const key = perOrg ? `org:${auth.orgId}` : `ak:${auth.apiKeyId}`;
    return { key, tier: auth.tier };
  }
  if (auth?.kind === "user") {
    const key =
      perOrg && auth.orgId ? `org:${auth.orgId}` : `u:${auth.userId}`;
    return { key, tier: auth.tier ?? "free" };
  }
  const ip = (req.ip ?? "unknown").replace(/[^a-zA-Z0-9.:]/g, "_");
  return { key: `ip:${ip}`, tier: "anonymous" };
}

/**
 * Check and consume one token for the current request. Returns the decision
 * instead of modifying the reply — callers decide how to respond.
 */
export async function consumeToken(
  req: FastifyRequest,
  endpointClass: string,
  deps: RateLimitDeps,
): Promise<Decision> {
  const cfg = deps.config ?? DEFAULT_RATE_LIMIT;
  const classOverride = cfg.classes?.[endpointClass];
  const limitsForClass = classOverride ?? cfg.limits;
  // Class overrides bucket per-org (one bucket shared across all keys in the
  // org); the default class falls back to per-principal keying.
  const { key, tier } = resolvePrincipalKey(req, classOverride !== undefined);
  const limit = limitsForClass[tier];

  // Frontier + any Infinity tier bypass entirely.
  if (!Number.isFinite(limit)) {
    return { allowed: true, remaining: Number.POSITIVE_INFINITY, resetSec: 0 };
  }

  const redisKey = `ratelimit:${endpointClass}:${key}`;
  const window = cfg.windowSec;

  // Fixed-window INCR. First hit sets TTL; subsequent hits inherit it.
  const pipeline = deps.redis.multi();
  pipeline.incr(redisKey);
  pipeline.ttl(redisKey);
  const results = await pipeline.exec();

  // exec returns [[err, val], ...] or null on failure. Treat failure as
  // open-fail (allow the request) rather than breaking prod on a Redis blip —
  // the alternative is cascading outages when Redis hiccups.
  if (!results) {
    return { allowed: true, remaining: limit, resetSec: window };
  }

  const count = Number(results[0]?.[1] ?? 0);
  let ttl = Number(results[1]?.[1] ?? -1);
  if (ttl < 0) {
    await deps.redis.expire(redisKey, window);
    ttl = window;
  }

  const remaining = Math.max(0, (limit as number) - count);
  return {
    allowed: count <= (limit as number),
    remaining,
    resetSec: ttl,
  };
}

export interface RateLimitOptions {
  endpointClass?: string;
}

export function buildRateLimitPreHandler(
  deps: RateLimitDeps,
  opts: RateLimitOptions = {},
) {
  return async function rateLimitPreHandler(
    req: FastifyRequest,
    reply: FastifyReply,
  ): Promise<void> {
    const routeConfig = req.routeOptions?.config as
      | { public?: boolean; rateLimit?: false | { endpointClass?: string } }
      | undefined;
    if (routeConfig?.rateLimit === false) return;
    const endpointClass =
      routeConfig?.rateLimit?.endpointClass ??
      opts.endpointClass ??
      "default";

    const decision = await consumeToken(req, endpointClass, deps);
    void reply.header("x-ratelimit-remaining", String(decision.remaining));
    void reply.header("x-ratelimit-reset", String(decision.resetSec));

    if (!decision.allowed) {
      // RFC 7231 §7.1.3 — `Retry-After` carries the wait in seconds.
      void reply.header("retry-after", String(decision.resetSec));
      void reply.code(429).send({
        error: "rate_limited",
        message: "rate limit exceeded",
        retryAfterSec: decision.resetSec,
      });
    }
  };
}

export function registerRateLimit(
  app: FastifyInstance,
  deps: RateLimitDeps,
  opts: RateLimitOptions = {},
): void {
  app.addHook("preHandler", buildRateLimitPreHandler(deps, opts));
}
