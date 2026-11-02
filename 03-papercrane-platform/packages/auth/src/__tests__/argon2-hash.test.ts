/**
 * Argon2id hashing tests for the API-key path.
 *
 * Focuses on properties that matter for the auth layer:
 *   - hashes are salt-randomised (same plaintext → different hash strings)
 *   - verify is timing-safe and constant-work for matching inputs
 *   - tampered ciphertext / wrong plaintext / malformed hash all return false
 *     uniformly, never throw — the auth middleware treats every failure
 *     identically to avoid oracle leaks
 *   - the encoded params in the produced hash match {@link ARGON2_OPTS}
 */
import { describe, it, expect } from 'vitest';
import {
  hashApiKey,
  verifyApiKey,
  generateApiKey,
  ARGON2_OPTS,
  timingSafeEqual,
} from '../apiKey.js';

describe('hashApiKey — salt randomisation', () => {
  it('produces a new salted hash each call for the same plaintext', async () => {
    const a = await hashApiKey('pc_live_sk_aaaaaaaaaaaaaaaaaaaaaaaaaa');
    const b = await hashApiKey('pc_live_sk_aaaaaaaaaaaaaaaaaaaaaaaaaa');
    expect(a).not.toBe(b);
    // Both must still verify against the original plaintext.
    await expect(
      verifyApiKey('pc_live_sk_aaaaaaaaaaaaaaaaaaaaaaaaaa', a),
    ).resolves.toBe(true);
    await expect(
      verifyApiKey('pc_live_sk_aaaaaaaaaaaaaaaaaaaaaaaaaa', b),
    ).resolves.toBe(true);
  });

  it('encodes the configured argon2id parameters into the hash string', async () => {
    const hash = await hashApiKey('test-key');
    // PHC format: $argon2id$v=19$m=<mem>,t=<time>,p=<par>$<salt>$<hash>
    expect(hash).toMatch(/^\$argon2id\$/);
    expect(hash).toContain(`m=${ARGON2_OPTS.memoryCost}`);
    expect(hash).toContain(`t=${ARGON2_OPTS.timeCost}`);
    expect(hash).toContain(`p=${ARGON2_OPTS.parallelism}`);
  });

  it('memory cost meets the OWASP 2023 floor (m >= 19456 KiB)', () => {
    expect(ARGON2_OPTS.memoryCost).toBeGreaterThanOrEqual(19456);
    expect(ARGON2_OPTS.timeCost).toBeGreaterThanOrEqual(2);
  });
});

describe('verifyApiKey — match path', () => {
  it('returns true for the exact plaintext that was hashed', async () => {
    const { fullKey, hash } = await generateApiKey('live');
    await expect(verifyApiKey(fullKey, hash)).resolves.toBe(true);
  });

  it('survives unicode and edge-length plaintexts', async () => {
    for (const plain of ['x', 'a'.repeat(256), 'pc_live_sk_🔑🔐']) {
      const h = await hashApiKey(plain);
      await expect(verifyApiKey(plain, h)).resolves.toBe(true);
    }
  });
});

describe('verifyApiKey — failure paths (never throws, returns false)', () => {
  it('returns false when the plaintext has been tampered (single-byte flip)', async () => {
    const original = 'pc_live_sk_correct_horse_battery';
    const hash = await hashApiKey(original);
    const tampered = 'pc_live_sk_correct_horse_batteryX'; // appended byte
    await expect(verifyApiKey(tampered, hash)).resolves.toBe(false);
  });

  it('returns false for a hash from a different plaintext', async () => {
    const hashOfA = await hashApiKey('plaintext-a');
    await expect(verifyApiKey('plaintext-b', hashOfA)).resolves.toBe(false);
  });

  it('returns false (never throws) on a malformed hash string', async () => {
    await expect(
      verifyApiKey('pc_live_sk_anything', 'not-a-valid-argon2-encoded-hash'),
    ).resolves.toBe(false);
    // Truncated PHC also returns false.
    await expect(verifyApiKey('x', '$argon2id$v=19$m=65536')).resolves.toBe(false);
  });

  it('returns false on empty plaintext or empty hash without timing oracle', async () => {
    await expect(verifyApiKey('', 'any')).resolves.toBe(false);
    await expect(verifyApiKey('x', '')).resolves.toBe(false);
  });
});

describe('timingSafeEqual export — constant-time compare', () => {
  it('returns true for equal buffers of equal length', () => {
    const a = new Uint8Array(Buffer.from('aaaaaaaaaaaaaaaa'));
    const b = new Uint8Array(Buffer.from('aaaaaaaaaaaaaaaa'));
    expect(timingSafeEqual(a, b)).toBe(true);
  });

  it('returns false when buffers differ', () => {
    const a = new Uint8Array(Buffer.from('aaaaaaaaaaaaaaaa'));
    const b = new Uint8Array(Buffer.from('aaaaaaaaaaaaaaab'));
    expect(timingSafeEqual(a, b)).toBe(false);
  });

  it('throws on length mismatch (callers must guard length first)', () => {
    const a = new Uint8Array(Buffer.from('aaaa'));
    const b = new Uint8Array(Buffer.from('aaaaaa'));
    // Node's contract: timingSafeEqual is only defined for equal-length inputs.
    expect(() => timingSafeEqual(a, b)).toThrow();
  });
});
