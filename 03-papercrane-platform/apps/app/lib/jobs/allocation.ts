/**
 * Pure design-count allocation across a multi-tool pipeline.
 *
 * Given a total number of designs and the tools the user picked, decide how
 * many designs each tool should produce. Three strategies:
 *
 * - `even`  : split as evenly as possible; leftover designs go +1 to the
 *              first tools in selection order.
 * - `auto`  : weight each tool by a static prior, normalize, scale to the
 *              total, then round with the largest-remainder method so the
 *              parts sum EXACTLY to the total. Every tool is guaranteed at
 *              least 1 design (when the total is >= the tool count).
 * - `manual`: pass the user's per-tool counts straight through (the caller
 *              validates the sum via {@link manualSumValid}).
 *
 * This module is intentionally side-effect free so it can be unit-tested in
 * isolation and reused by both the wizard UI and the submit path.
 */

export type AllocationStrategy = "auto" | "even" | "manual";

/**
 * Static per-tool-slug weight priors used by the `auto` strategy. Higher
 * weight => more designs. Tools absent from this map fall back to a neutral
 * weight of 1, which makes `auto` degenerate to an even split.
 *
 * v1 HEURISTIC: these numbers are a hand-tuned guess, not learned from
 * outcome data. Backbone / end-to-end binder generators get a modest boost
 * (they are the long pole and benefit most from extra sampling); pure
 * structure-prediction / validation tools sit slightly below neutral. Revisit
 * once we have real per-tool hit-rate telemetry.
 */
export const TOOL_WEIGHT_PRIOR: Record<string, number> = {
  // End-to-end / backbone binder design: favor more samples here.
  bindcraft: 1.3,
  boltzgen: 1.2,
  rfdiffusion: 1.1,
  // Sequence design: neutral-ish.
  proteinmpnn: 1.0,
  ligandmpnn: 1.0,
  solublempnn: 0.9,
  // Structure prediction / validation: needs fewer designs than generators.
  boltz2: 0.8,
  chai1: 0.8,
};

export interface AllocateOpts {
  strategy: AllocationStrategy;
  totalDesigns: number;
  /** Stable order = selection order. Used for deterministic tie-breaking. */
  toolIds: string[];
  /** Required when strategy === 'manual'. */
  manualCounts?: Record<string, number>;
  /** Defaults to {@link TOOL_WEIGHT_PRIOR}. */
  weightPrior?: Record<string, number>;
}

/**
 * Even split: floor(total / n) to every tool, then hand the remainder out
 * +1-at-a-time to the first `remainder` tools by stable order.
 */
function allocateEven(
  toolIds: string[],
  total: number,
): Record<string, number> {
  const n = toolIds.length;
  const base = Math.floor(total / n);
  let remainder = total - base * n;
  const out: Record<string, number> = {};
  for (const id of toolIds) {
    out[id] = base + (remainder > 0 ? 1 : 0);
    if (remainder > 0) remainder -= 1;
  }
  return out;
}

/**
 * Weighted split with largest-remainder rounding. Parts always sum to `total`
 * exactly, and every tool gets >= 1 design when `total >= toolIds.length`.
 */
function allocateAuto(
  toolIds: string[],
  total: number,
  weightPrior: Record<string, number>,
): Record<string, number> {
  const n = toolIds.length;
  const weights = toolIds.map((id) => weightPrior[id] ?? 1);
  const weightSum = weights.reduce((a, b) => a + b, 0);

  // Ideal (fractional) quota per tool.
  const quotas = weights.map((w) => (w / weightSum) * total);

  // Largest-remainder: floor everyone, then give the leftover +1s to the
  // tools with the biggest fractional parts (ties broken by stable order).
  const counts = quotas.map((q) => Math.floor(q));
  let leftover = total - counts.reduce((a, b) => a + b, 0);

  const order = quotas
    .map((q, i) => ({ i, frac: q - Math.floor(q) }))
    .sort((a, b) => (b.frac === a.frac ? a.i - b.i : b.frac - a.frac));

  let k = 0;
  while (leftover > 0) {
    const idx = order[k % n]!.i;
    counts[idx] = (counts[idx] ?? 0) + 1;
    leftover -= 1;
    k += 1;
  }

  // Guarantee a floor of 1 per tool by reallocating from the richest tools.
  // This preserves the exact sum. Only achievable when total >= n.
  if (total >= n) {
    let guard = 0;
    const maxIters = n * n + n;
    while (counts.some((c) => c < 1) && guard < maxIters) {
      const zeroIdx = counts.findIndex((c) => c < 1);
      // Donor = the tool with the most designs (earliest on ties).
      let donor = 0;
      for (let i = 1; i < n; i++) {
        if ((counts[i] ?? 0) > (counts[donor] ?? 0)) donor = i;
      }
      if ((counts[donor] ?? 0) <= 1) break;
      counts[donor] = (counts[donor] ?? 0) - 1;
      counts[zeroIdx] = (counts[zeroIdx] ?? 0) + 1;
      guard += 1;
    }
  }

  const out: Record<string, number> = {};
  toolIds.forEach((id, i) => {
    out[id] = counts[i] ?? 0;
  });
  return out;
}

/**
 * Manual: echo the caller's counts, defaulting any missing tool to 0 so the
 * result always carries every toolId as a key. The caller is responsible for
 * validating the sum (see {@link manualSumValid}).
 */
function allocateManual(
  toolIds: string[],
  manualCounts: Record<string, number>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const id of toolIds) {
    out[id] = manualCounts[id] ?? 0;
  }
  return out;
}

export function allocate(opts: AllocateOpts): Record<string, number> {
  const { strategy, totalDesigns, toolIds } = opts;

  if (toolIds.length === 0) return {};

  switch (strategy) {
    case "even":
      return allocateEven(toolIds, totalDesigns);
    case "manual":
      return allocateManual(toolIds, opts.manualCounts ?? {});
    case "auto":
      return allocateAuto(
        toolIds,
        totalDesigns,
        opts.weightPrior ?? TOOL_WEIGHT_PRIOR,
      );
    default: {
      // Exhaustiveness guard: unreachable for valid AllocationStrategy.
      const _never: never = strategy;
      return _never;
    }
  }
}

/**
 * True iff the manual counts (missing tools treated as 0, no negatives) sum
 * exactly to `total` across the given `toolIds`.
 */
export function manualSumValid(
  manualCounts: Record<string, number>,
  toolIds: string[],
  total: number,
): boolean {
  let acc = 0;
  for (const id of toolIds) {
    const v = manualCounts[id] ?? 0;
    if (v < 0 || !Number.isFinite(v)) return false;
    acc += v;
  }
  return acc === total;
}
