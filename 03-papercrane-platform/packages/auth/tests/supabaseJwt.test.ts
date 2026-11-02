import { describe, it, expect, beforeAll } from 'vitest';
import {
  generateKeyPair,
  SignJWT,
  exportJWK,
  type JWK,
  type KeyLike,
} from 'jose';
import { verifySupabaseJwt } from '../src/supabaseJwt.js';
import { AuthError } from '../src/errors.js';

const PROJECT_REF = 'abcd1234';
const ISSUER = `https://${PROJECT_REF}.supabase.co/auth/v1`;

let privateKey: KeyLike;
let publicJwk: JWK;

beforeAll(async () => {
  const pair = await generateKeyPair('RS256');
  privateKey = pair.privateKey;
  publicJwk = await exportJWK(pair.publicKey);
  publicJwk.kid = 'test-kid-1';
  publicJwk.alg = 'RS256';
  publicJwk.use = 'sig';
});

const localJwks = () => ({ keys: [publicJwk] });

async function signToken(overrides: {
  iss?: string;
  aud?: string;
  sub?: string;
  email?: string;
  role?: string;
  exp?: number;
  kid?: string;
} = {}): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({
    email: overrides.email ?? 'user@example.com',
    role: overrides.role ?? 'authenticated',
  })
    .setProtectedHeader({ alg: 'RS256', kid: overrides.kid ?? 'test-kid-1' })
    .setIssuer(overrides.iss ?? ISSUER)
    .setAudience(overrides.aud ?? 'authenticated')
    .setSubject(overrides.sub ?? 'user-123')
    .setIssuedAt(now)
    .setExpirationTime(overrides.exp ?? now + 3600)
    .sign(privateKey);
}

describe('verifySupabaseJwt', () => {
  it('decodes a valid token', async () => {
    const token = await signToken();
    const payload = await verifySupabaseJwt(token, {
      projectRef: PROJECT_REF,
      jwks: localJwks(),
    });
    expect(payload.sub).toBe('user-123');
    expect(payload.email).toBe('user@example.com');
    expect(payload.role).toBe('authenticated');
    expect(payload.aud).toBe('authenticated');
    expect(payload.exp).toBeGreaterThan(Math.floor(Date.now() / 1000));
  });

  it('rejects an expired token', async () => {
    const token = await signToken({ exp: Math.floor(Date.now() / 1000) - 10 });
    await expect(
      verifySupabaseJwt(token, { projectRef: PROJECT_REF, jwks: localJwks() }),
    ).rejects.toBeInstanceOf(AuthError);
  });

  it('rejects a token with the wrong issuer', async () => {
    const token = await signToken({ iss: 'https://evil.example.com/auth/v1' });
    await expect(
      verifySupabaseJwt(token, { projectRef: PROJECT_REF, jwks: localJwks() }),
    ).rejects.toBeInstanceOf(AuthError);
  });

  it('rejects a token with the wrong audience', async () => {
    const token = await signToken({ aud: 'some-other-aud' });
    await expect(
      verifySupabaseJwt(token, { projectRef: PROJECT_REF, jwks: localJwks() }),
    ).rejects.toBeInstanceOf(AuthError);
  });

  it('rejects a token signed by an unknown key (bad signature / unknown kid)', async () => {
    // JWKS returns a *different* key than the one that signed the token
    const otherPair = await generateKeyPair('RS256');
    const otherJwk = await exportJWK(otherPair.publicKey);
    otherJwk.kid = 'other-kid';
    otherJwk.alg = 'RS256';
    otherJwk.use = 'sig';
    const token = await signToken({ kid: 'test-kid-1' });
    await expect(
      verifySupabaseJwt(token, {
        projectRef: PROJECT_REF,
        jwks: { keys: [otherJwk] },
      }),
    ).rejects.toBeInstanceOf(AuthError);
  });

  it('rejects a tampered token', async () => {
    const token = await signToken();
    // Tamper with the payload section
    const parts = token.split('.');
    parts[1] = Buffer.from(JSON.stringify({ sub: 'attacker', role: 'admin' })).toString('base64url');
    const tampered = parts.join('.');
    await expect(
      verifySupabaseJwt(tampered, { projectRef: PROJECT_REF, jwks: localJwks() }),
    ).rejects.toBeInstanceOf(AuthError);
  });

  it('supports a custom audience', async () => {
    const token = await signToken({ aud: 'service-role' });
    const payload = await verifySupabaseJwt(token, {
      projectRef: PROJECT_REF,
      audience: 'service-role',
      jwks: localJwks(),
    });
    expect(payload.aud).toBe('service-role');
  });
});
