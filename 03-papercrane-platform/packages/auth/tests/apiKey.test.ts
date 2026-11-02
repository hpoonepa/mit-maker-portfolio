import { describe, it, expect } from 'vitest';
import {
  generateApiKey,
  hashApiKey,
  verifyApiKey,
  hasScope,
  API_KEY_PREFIX_LENGTH,
} from '../src/apiKey.js';

describe('generateApiKey', () => {
  it('produces a live key with the correct format', async () => {
    const { fullKey, prefix, hash } = await generateApiKey('live');
    // pc_live_sk_ + 26 base62 chars
    expect(fullKey).toMatch(/^pc_live_sk_[0-9A-Za-z]{26}$/);
    expect(prefix).toHaveLength(API_KEY_PREFIX_LENGTH);
    expect(fullKey.startsWith(prefix)).toBe(true);
    expect(hash).toMatch(/^\$argon2id\$/);
  });

  it('produces a test key with the correct format', async () => {
    const { fullKey, prefix } = await generateApiKey('test');
    expect(fullKey).toMatch(/^pc_test_sk_[0-9A-Za-z]{26}$/);
    expect(prefix).toBe(fullKey.slice(0, API_KEY_PREFIX_LENGTH));
  });

  it('generates unique keys across calls', async () => {
    const a = await generateApiKey('live');
    const b = await generateApiKey('live');
    expect(a.fullKey).not.toBe(b.fullKey);
    expect(a.hash).not.toBe(b.hash);
  });
});

describe('hashApiKey + verifyApiKey', () => {
  it('roundtrips a correct key', async () => {
    const { fullKey } = await generateApiKey('live');
    const hash = await hashApiKey(fullKey);
    await expect(verifyApiKey(fullKey, hash)).resolves.toBe(true);
  });

  it('rejects a wrong key', async () => {
    const { fullKey } = await generateApiKey('live');
    const hash = await hashApiKey(fullKey);
    await expect(verifyApiKey('pc_live_sk_' + 'x'.repeat(26), hash)).resolves.toBe(false);
  });

  it('rejects an empty key', async () => {
    const { fullKey } = await generateApiKey('live');
    const hash = await hashApiKey(fullKey);
    await expect(verifyApiKey('', hash)).resolves.toBe(false);
  });

  it('rejects when hash is malformed', async () => {
    await expect(verifyApiKey('pc_live_sk_abc', 'not-a-valid-argon2-hash')).resolves.toBe(false);
  });
});

describe('hasScope', () => {
  it('returns true when exact scope present', () => {
    expect(hasScope(['jobs:read', 'jobs:write'], 'jobs:read')).toBe(true);
  });

  it('returns false when scope missing', () => {
    expect(hasScope(['jobs:read'], 'jobs:write')).toBe(false);
  });

  it('treats "*" as wildcard matching anything', () => {
    expect(hasScope(['*'], 'jobs:write')).toBe(true);
    expect(hasScope(['*'], 'anything:at:all')).toBe(true);
  });

  it('returns false for empty scope list', () => {
    expect(hasScope([], 'jobs:read')).toBe(false);
  });
});
