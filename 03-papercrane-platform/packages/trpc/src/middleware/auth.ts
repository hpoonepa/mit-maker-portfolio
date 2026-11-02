/**
 * Auth middleware for tRPC procedures.
 *
 *   - `requireAuth`      — any authenticated principal (user or API key)
 *   - `requireScope(s)`  — auth + explicit scope (API-key concept; users bypass)
 *   - `requireTier(min)` — auth + tier >= min (free < pro < frontier)
 *
 * These return chained middleware factories. Build the final procedure by
 * `publicProcedure.use(requireAuth).use(requireTier('pro'))`.
 */
import { TRPCError } from '@trpc/server';
import type { ApiKeyScope } from '@papercrane/types';
import { betaGateEnabled } from '@papercrane/types';
import type { Tier } from '@papercrane/jobs';
import { middleware } from '../trpc.js';
import type { AuthContext } from '../context.js';

const TIER_RANK: Record<Tier, number> = { free: 0, pro: 1, frontier: 2 };

/**
 * Reject the call if there is no resolved auth principal on the context.
 * Downstream middleware and procedures can assume `ctx.auth` is non-null.
 */
export const requireAuth = middleware(async ({ ctx, next, path }) => {
  if (!ctx.auth) {
    throw new TRPCError({ code: 'UNAUTHORIZED', message: 'unauthorized' });
  }
  // Admission must protect direct API calls as well as dashboard navigation.
  // The authenticated admission endpoints remain reachable to claim an invite.
  if (betaGateEnabled(process.env.NEXT_PUBLIC_BETA_GATE) &&
      path !== 'beta.claimInvite' && path !== 'beta.accessStatus') {
    const user = await ctx.withRlsUser(ctx.prisma, ctx.auth.userId, (tx) =>
      tx.user.findUnique({ where: { id: ctx.auth!.userId }, select: { betaAccessGrantedAt: true } }),
    );
    if (!user?.betaAccessGrantedAt) {
      throw new TRPCError({ code: 'FORBIDDEN', message: 'A valid beta invite is required to access the platform.' });
    }
  }
  return next({ ctx: { ...ctx, auth: ctx.auth as AuthContext } });
});

/**
 * Enforce a specific API-key scope. User sessions (Supabase) bypass scope
 * checks — use RBAC at the application layer for user-facing gating.
 */
export function requireScope(required: ApiKeyScope) {
  return middleware(async ({ ctx, next }) => {
    if (!ctx.auth) {
      throw new TRPCError({ code: 'UNAUTHORIZED', message: 'unauthorized' });
    }
    if (ctx.auth.kind === 'user') {
      return next({ ctx: { ...ctx, auth: ctx.auth } });
    }
    const scopes = ctx.auth.scopes;
    if (!(scopes.includes('*') || scopes.includes(required))) {
      throw new TRPCError({
        code: 'FORBIDDEN',
        message: `missing scope: ${required}`,
      });
    }
    return next({ ctx: { ...ctx, auth: ctx.auth } });
  });
}

/**
 * Enforce a minimum plan tier. Example: `requireTier('pro')` allows pro and
 * frontier, rejects free.
 */
export function requireTier(min: Tier) {
  return middleware(async ({ ctx, next }) => {
    if (!ctx.auth) {
      throw new TRPCError({ code: 'UNAUTHORIZED', message: 'unauthorized' });
    }
    if (TIER_RANK[ctx.auth.tier] < TIER_RANK[min]) {
      throw new TRPCError({
        code: 'FORBIDDEN',
        message: `endpoint requires tier >= ${min}`,
      });
    }
    return next({ ctx: { ...ctx, auth: ctx.auth } });
  });
}
