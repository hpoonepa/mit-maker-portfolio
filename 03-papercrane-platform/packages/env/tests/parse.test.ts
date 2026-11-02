import { describe, expect, it, vi } from 'vitest';
import { ApiEnvSchema } from '../src/schema.js';
import { parseEnv, parseEnvSafe } from '../src/parse.js';

const VALID_API_ENV: NodeJS.ProcessEnv = {
  NODE_ENV: 'production',
  DATABASE_URL: 'postgresql://user:password@example.com:5432/db',
  DIRECT_URL: 'postgresql://user:password@example.com:5432/db',
  REDIS_URL: 'redis://example.com:6379',
  NEXT_PUBLIC_SUPABASE_URL: 'https://example.supabase.co',
  NEXT_PUBLIC_SUPABASE_ANON_KEY: 'anon-value',
  SUPABASE_PROJECT_REF: 'example',
  SUPABASE_SERVICE_ROLE_KEY: 'service-role-value',
  MODAL_CREDENTIAL_ENCRYPTION_KEY: Buffer.alloc(32, 1).toString('base64'),
  STRIPE_SECRET_KEY: 'sk_test_example',
  STRIPE_WEBHOOK_SECRET: 'whsec_example',
  SENTRY_DSN: 'https://key@example.ingest.sentry.io/1',
};

describe('parseEnvSafe', () => {
  it('accepts a complete production API environment', () => {
    const result = parseEnvSafe(ApiEnvSchema, VALID_API_ENV, { service: 'api' });

    expect(result.ok).toBe(true);
    expect(result.data?.DATABASE_URL).toBe(VALID_API_ENV.DATABASE_URL);
  });

  it('enforces the production-required overlay', () => {
    const env = { ...VALID_API_ENV };
    delete env.REDIS_URL;
    const result = parseEnvSafe(ApiEnvSchema, env, { service: 'api' });

    expect(result.ok).toBe(false);
    expect(result.missing).toContain('REDIS_URL');
  });

  it('stubs missing required values in test mode', () => {
    const result = parseEnvSafe(ApiEnvSchema, { NODE_ENV: 'test' }, { service: 'api' });

    expect(result.ok).toBe(true);
    expect(result.missing).toEqual([]);
  });

  it('rejects malformed secrets even in test mode', () => {
    const result = parseEnvSafe(
      ApiEnvSchema,
      { ...VALID_API_ENV, NODE_ENV: 'test', STRIPE_SECRET_KEY: 'not-a-key' },
      { service: 'api' },
    );

    expect(result.ok).toBe(false);
    expect(result.malformed.map((item) => item.name)).toContain('STRIPE_SECRET_KEY');
  });
});

describe('parseEnv', () => {
  it('never writes secret values in its failure report', () => {
    const err = vi.fn();
    const secret = 'service-role-must-not-leak';

    expect(() =>
      parseEnv(
        ApiEnvSchema,
        {
          NODE_ENV: 'production',
          SUPABASE_SERVICE_ROLE_KEY: secret,
        },
        { service: 'api', err },
      ),
    ).toThrow(/invalid environment/i);

    const output = err.mock.calls.flat().join('\n');
    expect(output).not.toContain(secret);
    expect(output).toContain('DATABASE_URL');
  });
});
