export {
  generateApiKey,
  hashApiKey,
  verifyApiKey,
  hasScope,
  API_KEY_PREFIX_LENGTH,
  ARGON2_OPTS,
  type ApiKeyEnv,
  type GeneratedApiKey,
} from './apiKey.js';

export {
  verifySupabaseJwt,
  __resetJwksCache,
  type VerifySupabaseJwtOptions,
  type SupabaseJwtPayload,
} from './supabaseJwt.js';

export {
  buildApiKeyContext,
  buildUserContext,
  requireScope,
  requireApiKey,
  requireUser,
  type AuthContext,
  type ApiKeyPrincipal,
  type UserPrincipal,
  type BuildApiKeyContextInput,
  type BuildUserContextInput,
} from './authContext.js';

export { AuthError, ForbiddenError } from './errors.js';

// Re-export common auth types from @papercrane/types so consumers can
// pull both runtime helpers and types from a single import surface.
// NOTE: limited to names guaranteed by both the real package AND the
// in-package types shim (`packages/auth/src/types-shim.d.ts`).
export type { ApiKeyScope, OrgTier } from '@papercrane/types';
