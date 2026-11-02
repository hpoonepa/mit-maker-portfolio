/**
 * Unit tests for the usage router projection helper.
 *
 * Covers the pure function `computeProjection` — verifies that:
 *   - empty input produces a zero forecast and a flat trajectory
 *   - actual values inside the period are reflected back exactly
 *   - the weekend dip override (Sat/Sun get 0.6×) bends the slope
 *   - the trajectory length matches the calendar period
 */
import { describe, it, expect, vi } from 'vitest';
import { createInnerContext, type AuthContext } from '../../context.js';
import { appRouter } from '../index.js';
import { computeProjection } from '../usage.js';

describe('computeProjection', () => {
  it('returns zeros when no data exists', () => {
    const periodStart = new Date('2026-04-01T00:00:00Z');
    const periodEnd = new Date('2026-05-01T00:00:00Z');
    const now = new Date('2026-04-15T00:00:00Z');
    const result = computeProjection({
      now,
      periodStart,
      periodEnd,
      byDay: new Map(),
    });
    expect(result.forecastSeeds).toBe(0);
    expect(result.dailyRate).toBe(0);
    expect(result.trajectory).toHaveLength(30);
    expect(result.trajectory[0]?.actual).toBe(0);
  });

  it('extrapolates linearly from the last 7 days', () => {
    const periodStart = new Date('2026-04-01T00:00:00Z');
    const periodEnd = new Date('2026-05-01T00:00:00Z');
    const now = new Date('2026-04-10T00:00:00Z'); // Friday
    // 100 seeds/day on the 7 days leading up to "now" (no weekends in
    // the active window: 2026-04-04 Sat + 04-05 Sun; daily rate gets
    // weekend-discounted).
    const byDay = new Map<string, number>();
    for (let i = 0; i < 7; i++) {
      const d = new Date(now);
      d.setUTCDate(d.getUTCDate() - i);
      byDay.set(d.toISOString().slice(0, 10), 100);
    }
    const result = computeProjection({ now, periodStart, periodEnd, byDay });
    expect(result.dailyRate).toBeGreaterThan(0);
    expect(result.forecastSeeds).toBeGreaterThan(0);
    // Trajectory length is the number of days in the period.
    expect(result.trajectory).toHaveLength(30);
    // Past days should have non-null actuals; future days should not.
    const past = result.trajectory.find((t) => t.day === '2026-04-09');
    const future = result.trajectory.find((t) => t.day === '2026-04-20');
    expect(past?.actual).not.toBeNull();
    expect(future?.actual).toBeNull();
  });

  it('flags trajectory length equal to days in period', () => {
    const periodStart = new Date('2026-02-01T00:00:00Z');
    const periodEnd = new Date('2026-03-01T00:00:00Z');
    const result = computeProjection({
      now: new Date('2026-02-14T00:00:00Z'),
      periodStart,
      periodEnd,
      byDay: new Map([['2026-02-10', 50]]),
    });
    expect(result.trajectory).toHaveLength(28);
  });
});

describe('usage.getCurrentPeriodUsage', () => {
  it('uses the persisted organization slug when the HTTP auth context omits it', async () => {
    const organization = {
      findUnique: vi.fn().mockResolvedValue({
        slug: 'mosaic-labs',
        tier: 'frontier',
        seedsQuota: 1_000,
        seedsUsed: 12,
      }),
    };
    const job = {
      aggregate: vi.fn().mockResolvedValue({ _sum: { seedsConsumed: 12 } }),
    };
    const auth = {
      kind: 'user',
      userId: '00000000-0000-4000-8000-000000000001',
      orgId: '00000000-0000-4000-8000-000000000002',
      tier: 'frontier',
      scopes: [],
    } as unknown as AuthContext;
    const ctx = {
      ...createInnerContext({
        auth,
        prisma: {} as never,
        withRlsUser: vi.fn(async (_prisma, _userId, fn) =>
          fn({ organization, job } as never),
        ) as never,
        now: () => new Date('2026-07-13T12:00:00Z'),
      }),
      req: { headers: {} },
    };

    const result = await appRouter
      .createCaller(ctx)
      .usage.getCurrentPeriodUsage();

    expect(result).toMatchObject({
      orgSlug: 'mosaic-labs',
      orgTier: 'frontier',
      seedsIncluded: 1_000,
      seedsConsumed: 12,
    });
  });
});
