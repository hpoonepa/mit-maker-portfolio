import { randomBytes, timingSafeEqual } from 'node:crypto';
import argon2 from 'argon2';
import type { ApiKeyScope } from '@papercrane/types';

/**
 * API key format: `pc_<env>_sk_<26 chars base62>`
 *   - env: 'live' or 'test'
 *   - 26 base62 chars = ~154 bits of entropy (base62 char ≈ 5.954 bits)
 *
 * Storage: we never store the plaintext. The DB holds:
 *   - `prefix` (first 8 chars) — shown in UI for identification
 *   - `hash`   — argon2id(fullKey) — used for verification
 *
 * Verification uses `argon2.verify`, which is timing-safe and constant-work
 * for the configured parameters.
 */

const BASE62_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
const BASE62_LENGTH = 26;

export const API_KEY_PREFIX_LENGTH = 8;

/**
 * Argon2id parameters.
 *
 * - `memoryCost: 2^16` KiB = 64 MiB of RAM per hash
 * - `timeCost: 3` iterations
 * - `parallelism: 1` lane
 *
 * These satisfy OWASP 2023 minimums (m=19456, t=2) with headroom. A single
 * verification takes ~50-150ms on a modern server core, which is acceptable
 * for API authentication and makes offline brute-forcing expensive.
 *
 * If we ever bump these, existing hashes remain verifiable (argon2 encodes
 * params in the hash string). To migrate, rehash on successful login.
 */
export const ARGON2_OPTS = {
  type: argon2.argon2id,
  memoryCost: 2 ** 16, // 64 MiB
  timeCost: 3,
  parallelism: 1,
} as const;

export type ApiKeyEnv = 'live' | 'test';

export interface GeneratedApiKey {
  /** Full plaintext key — show to user ONCE, never store. */
  fullKey: string;
  /** First 8 chars; store in DB for UI display (e.g. "pc_live_"). */
  prefix: string;
  /** argon2id hash of fullKey; store in DB with a unique index. */
  hash: string;
}

/**
 * Produce `n` base62 characters using crypto-grade randomness.
 * Uses rejection sampling to avoid modulo bias.
 */
function randomBase62(n: number): string {
  const out: string[] = [];
  // Pull more bytes than we need; reject any >= 248 (largest multiple of 62 below 256).
  const maxAcceptable = 256 - (256 % BASE62_ALPHABET.length); // 248
  while (out.length < n) {
    const buf = randomBytes(n * 2);
    for (let i = 0; i < buf.length && out.length < n; i++) {
      const byte = buf[i]!;
      if (byte < maxAcceptable) {
        out.push(BASE62_ALPHABET[byte % BASE62_ALPHABET.length]!);
      }
    }
  }
  return out.join('');
}

/**
 * Generate a new API key and its argon2id hash.
 * Callers store `{ prefix, hash }` and reveal `fullKey` to the user exactly once.
 */
export async function generateApiKey(env: ApiKeyEnv): Promise<GeneratedApiKey> {
  const random = randomBase62(BASE62_LENGTH);
  const fullKey = `pc_${env}_sk_${random}`;
  const prefix = fullKey.slice(0, API_KEY_PREFIX_LENGTH);
  const hash = await hashApiKey(fullKey);
  return { fullKey, prefix, hash };
}

/**
 * Hash an API key with argon2id using {@link ARGON2_OPTS}.
 */
export async function hashApiKey(key: string): Promise<string> {
  return argon2.hash(key, ARGON2_OPTS);
}

/**
 * Verify an incoming API key against a stored argon2id hash.
 * Returns false on malformed hash/key rather than throwing — callers treat
 * "not verified" uniformly regardless of cause to avoid oracle leaks.
 */
export async function verifyApiKey(incoming: string, storedHash: string): Promise<boolean> {
  if (!incoming || !storedHash) return false;
  try {
    return await argon2.verify(storedHash, incoming);
  } catch {
    return false;
  }
}

/**
 * Check whether a scope set satisfies a required scope.
 *
 * `'*'` is a wildcard that grants every scope — use sparingly (owner keys only).
 * Otherwise, match is exact.
 */
export function hasScope(scopes: ApiKeyScope[], required: ApiKeyScope): boolean {
  if (scopes.length === 0) return false;
  if (scopes.includes('*')) return true;
  return scopes.includes(required);
}

// Re-exported for callers that want to do their own constant-time comparisons.
export { timingSafeEqual };
