/**
 * Per-procedure rate limit wrapper.
 *
 * The limiter is deliberately backend-agnostic: a tiny interface is all we
 * need, and the API app injects a Redis-backed implementation. In tests or
 * local dev, callers can pass an in-memory stub or skip the wrapper
 * entirely.
 *
 * Keying strategy: `${procedure}:${subjectId}` where subjectId is the
 * authenticated principal's key id or user id, falling back to the request
 * IP from context.req. This keeps limits per-user rather than per-org so
 * one noisy user can't starve others on the same plan.
 */
import { TRPCError } from '@trpc/server';
import { middleware } from '../trpc.js';

export interface RateLimiter {
  /** Returns true iff the call is within budget; false means deny. */
  consume(key: string, limit: number, windowSec: number): Promise<boolean>;
}

export interface RateLimitOptions {
  /** Procedure name used in the key. Pick one unique per procedure. */
  procedure: string;
  /** Max calls allowed in `windowSec`. */
  limit: number;
  /** Window length in seconds. */
  windowSec: number;
  /** The limiter implementation. If omitted, the middleware is a noop. */
  limiter?: RateLimiter;
}

function subjectId(ctx: {
  auth: { kind: 'user'; userId: string } | { kind: 'apiKey'; apiKeyId: string } | null;
  req?: { headers: Record<string, string | string[] | undefined> };
}): string {
  if (ctx.auth?.kind === 'user') return `u:${ctx.auth.userId}`;
  if (ctx.auth?.kind === 'apiKey') return `k:${ctx.auth.apiKeyId}`;
  const ipHeader = ctx.req?.headers?.['x-forwarded-for'];
  const ip = Array.isArray(ipHeader) ? ipHeader[0] : ipHeader;
  return `ip:${ip ?? 'unknown'}`;
}

export function rateLimit(opts: RateLimitOptions) {
  return middleware(async ({ ctx, next }) => {
    if (!opts.limiter) return next();
    const key = `${opts.procedure}:${subjectId(ctx)}`;
    const ok = await opts.limiter.consume(key, opts.limit, opts.windowSec);
    if (!ok) {
      throw new TRPCError({
        code: 'TOO_MANY_REQUESTS',
        message: `rate limit exceeded for ${opts.procedure}`,
      });
    }
    return next();
  });
}
