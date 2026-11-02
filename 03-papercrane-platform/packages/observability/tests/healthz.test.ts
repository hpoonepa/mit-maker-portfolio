import { describe, it, expect } from 'vitest';
import { buildHealthResponse } from '../src/healthz.js';

describe('buildHealthResponse', () => {
  it('returns ok=true when all checks pass', async () => {
    const resp = await buildHealthResponse({
      db: async () => true,
      cache: async () => true,
    });
    expect(resp.ok).toBe(true);
    expect(resp.checks.db?.ok).toBe(true);
    expect(resp.checks.cache?.ok).toBe(true);
  });

  it('returns ok=false (degraded) when any check fails', async () => {
    const resp = await buildHealthResponse({
      db: async () => true,
      cache: async () => false,
    });
    expect(resp.ok).toBe(false);
    expect(resp.checks.db?.ok).toBe(true);
    expect(resp.checks.cache?.ok).toBe(false);
  });

  it('treats thrown errors as failed checks with error message', async () => {
    const resp = await buildHealthResponse({
      db: async () => {
        throw new Error('connection refused');
      },
    });
    expect(resp.ok).toBe(false);
    expect(resp.checks.db?.ok).toBe(false);
    expect(resp.checks.db?.error).toContain('connection refused');
  });

  it('handles empty check set as ok=true', async () => {
    const resp = await buildHealthResponse({});
    expect(resp.ok).toBe(true);
    expect(resp.checks).toEqual({});
  });

  it('runs checks in parallel', async () => {
    const delays = [50, 50, 50];
    const start = Date.now();
    const resp = await buildHealthResponse({
      a: () => new Promise((r) => setTimeout(() => r(true), delays[0])),
      b: () => new Promise((r) => setTimeout(() => r(true), delays[1])),
      c: () => new Promise((r) => setTimeout(() => r(true), delays[2])),
    });
    const elapsed = Date.now() - start;
    expect(resp.ok).toBe(true);
    // Parallel: ~50ms, not 150ms. Give generous slack for CI.
    expect(elapsed).toBeLessThan(140);
  });
});
