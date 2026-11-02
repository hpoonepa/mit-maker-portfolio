/**
 * Formatting helpers for the public leaderboard.
 *
 * Keep these pure + deterministic. They run on both the server (RSC) and
 * the client (filter bar re-renders) so anything time-zone-sensitive must
 * take its reference time as an argument rather than reading the clock.
 */

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "N/A";
  return `${(value * 100).toFixed(digits)}%`;
}

/**
 * "±4%" style CI half-width. `ci` is the (lo, hi) tuple, 0..1 scale.
 * Returns null if either bound is missing so the caller can hide the chip.
 */
export function formatCi(ci: readonly [number, number] | null | undefined): string | null {
  if (!ci) return null;
  const [lo, hi] = ci;
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  const half = ((hi - lo) / 2) * 100;
  return `±${half.toFixed(1)}%`;
}

/**
 * Dollars-per-hit. Cheap-and-clear: `$0.89` for routine values, `$N/A` for
 * infinite (no hits = undefined cost per hit) or negative.
 */
export function formatCostPerHit(costUsd: number | null | undefined, hits: number): string {
  if (costUsd == null || !Number.isFinite(costUsd) || hits <= 0) return "$N/A";
  const cph = costUsd / hits;
  if (cph < 1) return `$${cph.toFixed(2)}`;
  if (cph < 100) return `$${cph.toFixed(1)}`;
  return `$${Math.round(cph)}`;
}

/**
 * Coefficient of variation over an array of per-run hit rates (each 0..1).
 * CV = stddev / mean. Returns null when `values.length < 2` or mean ≈ 0.
 */
export function coefficientOfVariation(values: readonly number[]): number | null {
  if (values.length < 2) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  if (mean < 1e-9) return null;
  const variance =
    values.reduce((acc, v) => acc + (v - mean) ** 2, 0) / (values.length - 1);
  return Math.sqrt(variance) / mean;
}

export function formatCv(cv: number | null | undefined): string {
  if (cv == null || !Number.isFinite(cv)) return "N/A";
  return cv.toFixed(2);
}

/**
 * "2h ago", "3d ago" relative age: used for the "Updated Xh ago" header.
 * `now` is an argument so server-rendered strings stay deterministic.
 */
export function formatAge(iso: string | Date, now: Date = new Date()): string {
  const then = typeof iso === "string" ? new Date(iso) : iso;
  const ms = now.getTime() - then.getTime();
  if (ms < 0) return "just now";
  const min = Math.floor(ms / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  return `${mo}mo ago`;
}

export function formatInt(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "N/A";
  return Math.round(n).toLocaleString();
}

/** Short SHA: "4f9d2e1" from "4f9d2e1abc..." */
export function shortSha(sha: string | null | undefined, len = 7): string {
  if (!sha) return "N/A";
  return sha.replace(/^sha256:/, "").slice(0, len);
}
