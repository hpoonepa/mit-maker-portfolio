import { describe, expect, it } from 'vitest';
import {
  mean,
  stdev,
  zScore,
  detectDrift,
  incidentTitle,
  incidentBody,
  type DriftRow,
} from './drift-detect.js';

describe('mean / stdev / zScore', () => {
  it('mean of empty is 0', () => {
    expect(mean([])).toBe(0);
  });

  it('computes sample mean', () => {
    expect(mean([1, 2, 3, 4])).toBeCloseTo(2.5, 10);
  });

  it('stdev returns 0 for <2 points', () => {
    expect(stdev([])).toBe(0);
    expect(stdev([0.5])).toBe(0);
  });

  it('computes sample stdev (n-1)', () => {
    // [1,2,3,4,5] -> mean 3, ssq = 10, var = 10/4 = 2.5, sd ≈ 1.5811
    expect(stdev([1, 2, 3, 4, 5])).toBeCloseTo(1.5811388, 4);
  });

  it('zScore returns 0 when stdev is 0', () => {
    expect(zScore(0.5, 0.4, 0)).toBe(0);
  });

  it('zScore sign matches direction', () => {
    expect(zScore(0.6, 0.4, 0.1)).toBeCloseTo(2, 10);
    expect(zScore(0.2, 0.4, 0.1)).toBeCloseTo(-2, 10);
  });
});

describe('detectDrift', () => {
  const stable4wk = [
    { weekStart: '2026-03-02', hitRate: 0.40 },
    { weekStart: '2026-03-09', hitRate: 0.41 },
    { weekStart: '2026-03-16', hitRate: 0.39 },
    { weekStart: '2026-03-23', hitRate: 0.40 },
  ];

  it('returns null when history has fewer than 5 points', () => {
    const row: DriftRow = { toolId: 't', targetId: 'x', history: stable4wk };
    expect(detectDrift(row)).toBeNull();
  });

  it('flags a large positive spike as drift=up', () => {
    const row: DriftRow = {
      toolId: 'papercrane-v4',
      targetId: 'il7ra',
      history: [
        ...stable4wk,
        { weekStart: '2026-03-30', hitRate: 0.80 }, // way above 4wk mean ~0.40
      ],
    };
    const v = detectDrift(row, 2);
    expect(v).not.toBeNull();
    expect(v!.drifted).toBe(true);
    expect(v!.direction).toBe('up');
    expect(v!.zScore).toBeGreaterThan(2);
    expect(v!.latestHitRate).toBeCloseTo(0.80, 10);
    expect(v!.baselineMean).toBeCloseTo(0.40, 2);
  });

  it('flags a large negative dip as drift=down', () => {
    const row: DriftRow = {
      toolId: 'protenix',
      targetId: 'pd-l1',
      history: [
        ...stable4wk,
        { weekStart: '2026-03-30', hitRate: 0.05 },
      ],
    };
    const v = detectDrift(row, 2);
    expect(v!.drifted).toBe(true);
    expect(v!.direction).toBe('down');
    expect(v!.zScore).toBeLessThan(-2);
  });

  it('does NOT flag small fluctuations within the band', () => {
    const row: DriftRow = {
      toolId: 'bindcraft',
      targetId: 'rbd',
      history: [
        ...stable4wk,
        { weekStart: '2026-03-30', hitRate: 0.42 }, // within 1 stdev
      ],
    };
    const v = detectDrift(row, 2);
    expect(v!.drifted).toBe(false);
    expect(v!.direction).toBe('flat');
  });

  it('sorts history even when given out of order', () => {
    const row: DriftRow = {
      toolId: 't',
      targetId: 'x',
      history: [
        { weekStart: '2026-03-30', hitRate: 0.80 }, // latest, out of order
        { weekStart: '2026-03-02', hitRate: 0.40 },
        { weekStart: '2026-03-16', hitRate: 0.39 },
        { weekStart: '2026-03-09', hitRate: 0.41 },
        { weekStart: '2026-03-23', hitRate: 0.40 },
      ],
    };
    const v = detectDrift(row, 2);
    expect(v!.weekStart).toBe('2026-03-30');
    expect(v!.drifted).toBe(true);
  });

  it('respects custom z-threshold (stricter threshold suppresses drift)', () => {
    const row: DriftRow = {
      toolId: 't',
      targetId: 'x',
      history: [
        { weekStart: '2026-03-02', hitRate: 0.40 },
        { weekStart: '2026-03-09', hitRate: 0.42 },
        { weekStart: '2026-03-16', hitRate: 0.38 },
        { weekStart: '2026-03-23', hitRate: 0.41 },
        { weekStart: '2026-03-30', hitRate: 0.48 }, // moderately high
      ],
    };
    expect(detectDrift(row, 2)!.drifted).toBe(true);
    expect(detectDrift(row, 4)!.drifted).toBe(false);
  });

  it('z-score is 0 when baseline stdev is 0', () => {
    const row: DriftRow = {
      toolId: 't',
      targetId: 'x',
      history: [
        { weekStart: '2026-03-02', hitRate: 0.40 },
        { weekStart: '2026-03-09', hitRate: 0.40 },
        { weekStart: '2026-03-16', hitRate: 0.40 },
        { weekStart: '2026-03-23', hitRate: 0.40 },
        { weekStart: '2026-03-30', hitRate: 0.80 },
      ],
    };
    const v = detectDrift(row, 2);
    expect(v!.zScore).toBe(0);
    expect(v!.drifted).toBe(false); // 0 !> 2 -> no drift flag
  });
});

describe('incident formatting', () => {
  const sample = {
    toolId: 'papercrane-v4',
    targetId: 'il7ra',
    latestHitRate: 0.80,
    baselineMean: 0.40,
    baselineStdev: 0.01,
    zScore: 40,
    drifted: true,
    direction: 'up' as const,
    weekStart: '2026-03-30',
  };

  it('title matches the plan 04 §3 format', () => {
    expect(incidentTitle(sample)).toBe(
      'benchmark-incident: papercrane-v4/il7ra drift 2026-03-30',
    );
  });

  it('body contains tool, target, week, and z-score', () => {
    const body = incidentBody(sample);
    expect(body).toContain('papercrane-v4');
    expect(body).toContain('il7ra');
    expect(body).toContain('2026-03-30');
    expect(body).toContain('40.00');
    expect(body).toContain('80.0%');
    expect(body).toContain('40.0%');
  });
});
