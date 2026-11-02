/**
 * Bootstrap 95% CI for hit rate, per plan 04 §8.
 *
 * Treats each seed as an independent Bernoulli trial (hit or miss) and
 * resamples the vector with replacement N times (default 10,000), computing
 * the hit rate for each resample. The 2.5% and 97.5% percentiles of the
 * resampled rates are the CI bounds.
 *
 * Why a seeded RNG:
 *   Leaderboard output must be deterministic: the same (run, seed vector)
 *   should produce the same CI on every render so users comparing tabs see
 *   identical numbers. We use a tiny splitmix64 PRNG seeded by the hash of
 *   the input vector; good enough for bootstrapping hit rates.
 */

const DEFAULT_RESAMPLES = 10_000;
const LOWER_PCT = 0.025;
const UPPER_PCT = 0.975;

export interface BootstrapResult {
  hitRate: number;
  ci: readonly [number, number];
  resamples: number;
}

/**
 * Compute hit rate + 95% bootstrap CI.
 *
 * @param hits  Array of booleans (or 0/1 numbers): one entry per seed.
 * @param n     Resample count. Default 10,000 (plan 04 §8).
 * @param seed  Optional explicit seed. If omitted, derived from `hits`.
 */
export function bootstrapHitRate(
  hits: readonly (boolean | number)[],
  n: number = DEFAULT_RESAMPLES,
  seed?: number
): BootstrapResult {
  const binary = hits.map((h) => (h ? 1 : 0));
  const k = binary.length;

  if (k === 0) {
    return { hitRate: 0, ci: [0, 0], resamples: 0 };
  }
  if (k === 1) {
    const r = binary[0]!;
    return { hitRate: r, ci: [r, r], resamples: 0 };
  }

  const rng = makeRng(seed ?? hashVector(binary));
  const rates = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    for (let j = 0; j < k; j++) {
      const idx = Math.floor(rng() * k);
      sum += binary[idx]!;
    }
    rates[i] = sum / k;
  }

  rates.sort();
  const lo = rates[Math.floor(n * LOWER_PCT)]!;
  const hi = rates[Math.min(n - 1, Math.floor(n * UPPER_PCT))]!;
  const hitRate = binary.reduce((a: number, b: number) => a + b, 0) / k;

  return { hitRate, ci: [lo, hi], resamples: n };
}

// splitmix64-ish: tiny, deterministic, good enough for resampling
function makeRng(seed: number): () => number {
  let state = seed >>> 0 || 1;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashVector(v: readonly number[]): number {
  // FNV-1a over the binary vector
  let h = 2166136261 >>> 0;
  for (let i = 0; i < v.length; i++) {
    h ^= v[i]!;
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
