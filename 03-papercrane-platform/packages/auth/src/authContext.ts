import type { ApiKeyScope, OrgTier } from '@papercrane/types';
import { ForbiddenError } from './errors.js';
import { hasScope } from './apiKey.js';

/**
 * The resolved identity for a request. One of two principals:
 *
 *   - `apiKey` — server-to-server or CLI call authenticated by API key.
 *   - `user`   — browser/SPA session authenticated by Supabase JWT.
 *
 * Route handlers read this off the request (Fastify plugins / tRPC context
 * populate it). This module is HTTP-framework-agnostic — we only build the
 * context object and enforce scope checks.
 */

export interface ApiKeyPrincipal {
  kind: 'apiKey';
  apiKeyId: string;
  orgId: string;
  tier: OrgTier;
  scopes: ApiKeyScope[];
  /** Last 8 chars of the key prefix, for audit logging. */
  prefix?: string;
}

export interface UserPrincipal {
  kind: 'user';
  userId: string;
  email?: string;
  role: string;
  /** Present once we've joined the JWT to the user's org membership. */
  orgId?: string;
  tier?: OrgTier;
}

export type AuthContext = ApiKeyPrincipal | UserPrincipal;

export interface BuildApiKeyContextInput {
  apiKeyId: string;
  orgId: string;
  tier: OrgTier;
  scopes: ApiKeyScope[];
  prefix?: string;
}

export function buildApiKeyContext(input: BuildApiKeyContextInput): ApiKeyPrincipal {
  return {
    kind: 'apiKey',
    apiKeyId: input.apiKeyId,
    orgId: input.orgId,
    tier: input.tier,
    scopes: input.scopes,
    prefix: input.prefix,
  };
}

export interface BuildUserContextInput {
  userId: string;
  email?: string;
  role: string;
  orgId?: string;
  tier?: OrgTier;
}

export function buildUserContext(input: BuildUserContextInput): UserPrincipal {
  return {
    kind: 'user',
    userId: input.userId,
    email: input.email,
    role: input.role,
    orgId: input.orgId,
    tier: input.tier,
  };
}

/**
 * Enforce that the principal has a required scope. User principals (Supabase
 * session) bypass scope checks — scoping is an API-key concept. If you want
 * to gate user routes, do it at the RBAC/role layer, not here.
 *
 * Throws {@link ForbiddenError} on denial.
 */
export function requireScope(ctx: AuthContext, required: ApiKeyScope): void {
  if (ctx.kind === 'user') return;
  if (!hasScope(ctx.scopes, required)) {
    throw new ForbiddenError(`missing scope: ${required}`, 'scope_denied');
  }
}

/**
 * Narrow a context to an API-key principal, throwing if it's a user session.
 * Useful for routes that are strictly server-to-server.
 */
export function requireApiKey(ctx: AuthContext): ApiKeyPrincipal {
  if (ctx.kind !== 'apiKey') {
    throw new ForbiddenError('endpoint requires API key auth', 'api_key_required');
  }
  return ctx;
}

/**
 * Narrow a context to a user principal, throwing if it's an API-key call.
 * Useful for browser-only endpoints (e.g. billing portal).
 */
export function requireUser(ctx: AuthContext): UserPrincipal {
  if (ctx.kind !== 'user') {
    throw new ForbiddenError('endpoint requires user session', 'user_required');
  }
  return ctx;
}
