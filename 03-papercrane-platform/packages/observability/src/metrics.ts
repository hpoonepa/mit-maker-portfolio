import {
  Counter,
  Histogram,
  Registry,
  collectDefaultMetrics,
  type CounterConfiguration,
  type HistogramConfiguration,
} from 'prom-client';

/**
 * Default histogram buckets (in seconds) for job-duration-style metrics. Covers
 * sub-second API calls up through 4h Modal/Vast batch jobs.
 */
export const DEFAULT_JOB_DURATION_BUCKETS: readonly number[] = [
  0.1, 0.5, 1, 5, 10, 30, 60, 300, 1800, 3600, 14400,
];

/**
 * Shared Prometheus registry. Apps should expose `/metrics` by calling
 * `await metricsRegistry.metrics()`.
 */
export const metricsRegistry = new Registry();

let defaultMetricsStarted = false;

/**
 * Enable Node.js process metrics (cpu, memory, event loop lag, etc). Idempotent.
 */
export function enableDefaultMetrics(prefix?: string): void {
  if (defaultMetricsStarted) return;
  collectDefaultMetrics({
    register: metricsRegistry,
    prefix: prefix ?? 'papercrane_',
  });
  defaultMetricsStarted = true;
}

/**
 * Register (or retrieve, if already registered) a counter. Re-registering with
 * the same name returns the existing counter, which makes hot-reload during
 * tests / dev safe.
 */
export function counter<T extends string = string>(
  name: string,
  help: string,
  labelNames?: readonly T[],
): Counter<T> {
  const existing = metricsRegistry.getSingleMetric(name);
  if (existing) {
    return existing as Counter<T>;
  }
  const config: CounterConfiguration<T> = {
    name,
    help,
    registers: [metricsRegistry],
    labelNames: (labelNames ? [...labelNames] : []) as T[],
  };
  return new Counter<T>(config);
}

/**
 * Register (or retrieve) a histogram. Defaults to `DEFAULT_JOB_DURATION_BUCKETS`.
 */
export function histogram<T extends string = string>(
  name: string,
  help: string,
  buckets?: readonly number[],
  labelNames?: readonly T[],
): Histogram<T> {
  const existing = metricsRegistry.getSingleMetric(name);
  if (existing) {
    return existing as Histogram<T>;
  }
  const config: HistogramConfiguration<T> = {
    name,
    help,
    registers: [metricsRegistry],
    buckets: [...(buckets ?? DEFAULT_JOB_DURATION_BUCKETS)],
    labelNames: (labelNames ? [...labelNames] : []) as T[],
  };
  return new Histogram<T>(config);
}

export type { Counter, Histogram } from 'prom-client';
