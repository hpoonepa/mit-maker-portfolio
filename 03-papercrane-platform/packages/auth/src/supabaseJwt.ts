import {
  createLocalJWKSet,
  createRemoteJWKSet,
  jwtVerify,
  type JSONWebKeySet,
  type JWTPayload,
  type JWTVerifyGetKey,
} from 'jose';
import { AuthError } from './errors.js';

/**
 * Verify a Supabase-issued JWT.
 *
 * Supabase signs user JWTs with RS256 (asymmetric) and publishes the public
 * keys at `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`. We pull
 * the JWKS with caching (`jose.createRemoteJWKSet` handles TTL + refresh on
 * unknown `kid`) and verify signature + standard claims.
 *
 * Validated claims:
 *   - signature    (RS256 against the JWKS)
 *   - `iss`        must equal `https://<projectRef>.supabase.co/auth/v1`
 *   - `aud`        must equal `opts.audience` (default: 'authenticated')
 *   - `exp`        must be in the future (jose enforces this)
 *
 * Throws `AuthError` on any failure so callers can translate uniformly.
 */

export interface VerifySupabaseJwtOptions {
  /** Supabase project ref, e.g. `abcd1234`. Used to build the issuer URL. */
  projectRef: string;
  /**
   * Override the JWKS URL. Defaults to
   * `https://<projectRef>.supabase.co/auth/v1/.well-known/jwks.json`.
   */
  jwksUri?: string;
  /** Preloaded keys for offline verification and deterministic tests. */
  jwks?: JSONWebKeySet;
  /** Required `aud` claim. Default `'authenticated'`. */
  audience?: string;
  /** Clock tolerance in seconds for `exp`/`nbf`. Default 5. */
  clockToleranceSec?: number;
}

export interface SupabaseJwtPayload {
  sub: string;
  email?: string;
  role: string;
  aud: string;
  exp: number;
}

/**
 * Module-level cache of JWKS fetchers, keyed by jwksUri. `createRemoteJWKSet`
 * returns a function that handles its own in-memory caching + cooldown, so we
 * just need to avoid building a new one per request.
 */
const jwksCache = new Map<string, JWTVerifyGetKey>();

function getJwks(jwksUri: string): JWTVerifyGetKey {
  let jwks = jwksCache.get(jwksUri);
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(jwksUri), {
      // Defaults are reasonable: 30s cooldown on unknown kid, 10min TTL.
      // Leaving explicit so future tuning is obvious.
      cooldownDuration: 30_000,
      cacheMaxAge: 10 * 60_000,
    });
    jwksCache.set(jwksUri, jwks);
  }
  return jwks;
}

/** FOR TESTS: clear the JWKS fetcher cache. */
export function __resetJwksCache(): void {
  jwksCache.clear();
}

export async function verifySupabaseJwt(
  token: string,
  opts: VerifySupabaseJwtOptions,
): Promise<SupabaseJwtPayload> {
  if (!token || typeof token !== 'string') {
    throw new AuthError('missing JWT', 'jwt_missing');
  }

  const issuer = `https://${opts.projectRef}.supabase.co/auth/v1`;
  const jwksUri = opts.jwksUri ?? `${issuer}/.well-known/jwks.json`;
  const audience = opts.audience ?? 'authenticated';

  const jwks = opts.jwks ? createLocalJWKSet(opts.jwks) : getJwks(jwksUri);

  let payload: JWTPayload;
  try {
    const result = await jwtVerify(token, jwks, {
      issuer,
      audience,
      algorithms: ['RS256', 'ES256'],
      clockTolerance: opts.clockToleranceSec ?? 5,
    });
    payload = result.payload;
  } catch (err) {
    // jose throws typed errors (JWTExpired, JWTClaimValidationFailed, JWSSignatureVerificationFailed, …)
    // Normalize to AuthError with a compact code so callers can branch.
    const code = mapJoseErrorCode(err);
    throw new AuthError(`jwt verification failed: ${code}`, code);
  }

  if (typeof payload.sub !== 'string') {
    throw new AuthError('jwt missing sub', 'jwt_missing_sub');
  }
  if (typeof payload.exp !== 'number') {
    throw new AuthError('jwt missing exp', 'jwt_missing_exp');
  }
  if (typeof payload.aud !== 'string') {
    throw new AuthError('jwt aud must be a string', 'jwt_invalid_aud');
  }

  const role = typeof payload.role === 'string' ? payload.role : 'authenticated';
  const email = typeof payload.email === 'string' ? payload.email : undefined;

  return {
    sub: payload.sub,
    email,
    role,
    aud: payload.aud,
    exp: payload.exp,
  };
}

function mapJoseErrorCode(err: unknown): string {
  if (err && typeof err === 'object' && 'code' in err && typeof (err as { code: unknown }).code === 'string') {
    return (err as { code: string }).code;
  }
  if (err instanceof Error) return err.name || 'jwt_invalid';
  return 'jwt_invalid';
}
