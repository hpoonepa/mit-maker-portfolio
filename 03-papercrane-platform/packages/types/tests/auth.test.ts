import { describe, it, expect } from 'vitest';
import {
  ApiKeyScopeSchema,
  AuthContextSchema,
  TierSchema,
} from '../src/auth.js';

describe('TierSchema', () => {
  it('accepts the three known tiers', () => {
    expect(TierSchema.parse('free')).toBe('free');
    expect(TierSchema.parse('pro')).toBe('pro');
    expect(TierSchema.parse('frontier')).toBe('frontier');
  });

  it('rejects unknown tiers', () => {
    expect(() => TierSchema.parse('enterprise' as unknown)).toThrow();
  });
});

describe('ApiKeyScopeSchema', () => {
  const expectedScopes = [
    'jobs:read',
    'jobs:write',
    'designs:read',
    'targets:write',
    'usage:read',
    'usage:write',
    'keys:manage',
    '*',
  ] as const;

  it.each(expectedScopes)('accepts the %s scope', (scope) => {
    expect(ApiKeyScopeSchema.parse(scope)).toBe(scope);
  });

  it('accepts usage:write specifically (seed-consume endpoint)', () => {
    expect(ApiKeyScopeSchema.parse('usage:write')).toBe('usage:write');
  });

  it('rejects unknown scopes', () => {
    expect(() => ApiKeyScopeSchema.parse('admin:all' as unknown)).toThrow();
    expect(() => ApiKeyScopeSchema.parse('' as unknown)).toThrow();
  });
});

describe('AuthContextSchema', () => {
  const base = {
    userId: '550e8400-e29b-41d4-a716-446655440000',
    orgSlug: 'acme',
    tier: 'pro' as const,
    scopes: ['usage:write' as const],
  };

  it('accepts a minimal auth context with usage:write scope', () => {
    const parsed = AuthContextSchema.parse(base);
    expect(parsed.scopes).toContain('usage:write');
  });

  it('accepts multiple scopes including usage:write', () => {
    const parsed = AuthContextSchema.parse({
      ...base,
      scopes: ['usage:read', 'usage:write', 'jobs:write'],
    });
    expect(parsed.scopes).toHaveLength(3);
  });

  it('requires at least one scope', () => {
    expect(() =>
      AuthContextSchema.parse({ ...base, scopes: [] }),
    ).toThrow();
  });

  it('rejects unknown keys (.strict())', () => {
    expect(() =>
      AuthContextSchema.parse({ ...base, extra: 'nope' } as unknown),
    ).toThrow();
  });

  it('rejects invalid orgSlug format', () => {
    expect(() =>
      AuthContextSchema.parse({ ...base, orgSlug: 'Acme Corp' }),
    ).toThrow();
  });
});
