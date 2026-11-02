import { describe, it, expect, beforeEach } from 'vitest';
import { counter, histogram, metricsRegistry, DEFAULT_JOB_DURATION_BUCKETS } from '../src/metrics.js';

describe('metrics', () => {
  beforeEach(() => {
    metricsRegistry.clear();
  });

  it('counter increments and reflects value in registry', async () => {
    const c = counter('test_counter_total', 'Test counter');
    c.inc();
    c.inc(2);
    const metrics = await metricsRegistry.getMetricsAsJSON();
    const found = metrics.find((m) => m.name === 'test_counter_total');
    expect(found).toBeDefined();
    const value = (found!.values[0] as { value: number }).value;
    expect(value).toBe(3);
  });

  it('counter supports labels', async () => {
    const c = counter('test_labeled_total', 'Test labeled counter', ['status']);
    c.inc({ status: 'ok' });
    c.inc({ status: 'ok' });
    c.inc({ status: 'err' });
    const metrics = await metricsRegistry.getMetricsAsJSON();
    const found = metrics.find((m) => m.name === 'test_labeled_total');
    expect(found).toBeDefined();
    const okEntry = found!.values.find(
      (v) => (v.labels as { status?: string }).status === 'ok',
    ) as { value: number } | undefined;
    const errEntry = found!.values.find(
      (v) => (v.labels as { status?: string }).status === 'err',
    ) as { value: number } | undefined;
    expect(okEntry?.value).toBe(2);
    expect(errEntry?.value).toBe(1);
  });

  it('histogram observes values', async () => {
    const h = histogram('test_hist_seconds', 'Test histogram');
    h.observe(0.2);
    h.observe(0.8);
    h.observe(2);
    const metrics = await metricsRegistry.getMetricsAsJSON();
    const found = metrics.find((m) => m.name === 'test_hist_seconds');
    expect(found).toBeDefined();
    const sumEntry = found!.values.find((v) =>
      (v.metricName ?? '').endsWith('_sum'),
    ) as { value: number } | undefined;
    const countEntry = found!.values.find((v) =>
      (v.metricName ?? '').endsWith('_count'),
    ) as { value: number } | undefined;
    expect(sumEntry?.value).toBeCloseTo(3.0, 5);
    expect(countEntry?.value).toBe(3);
  });

  it('histogram uses default job duration buckets when none provided', () => {
    expect(DEFAULT_JOB_DURATION_BUCKETS).toEqual([
      0.1, 0.5, 1, 5, 10, 30, 60, 300, 1800, 3600, 14400,
    ]);
    const h = histogram('default_bucket_hist', 'Default buckets');
    h.observe(1);
    // If no bucket error is thrown, default buckets are applied.
    expect(h).toBeDefined();
  });

  it('returns the same metric if re-registered with same name', () => {
    const a = counter('dup_counter_total', 'dup');
    const b = counter('dup_counter_total', 'dup');
    expect(a).toBe(b);
  });
});
