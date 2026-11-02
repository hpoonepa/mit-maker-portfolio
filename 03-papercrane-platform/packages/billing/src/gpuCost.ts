/**
 * GPU cost calculator.
 *
 * Pure functions only — no I/O, no Prisma. The tRPC `jobs.submit` mutation
 * uses these to project a dollar cost from the tool's manifest BEFORE the
 * job is enqueued, and the worker uses them to reconcile against the
 * provider's reported runtime AFTER the job finishes.
 *
 * Prices below are Modal's official on-demand per-second GPU rates
 * (modal.com/pricing, observed 2026-06-27), rounded to the precision the
 * `gpu_spends.estimated_usd` column stores. Keys match the GPU strings the
 * tool manifests declare in `compute.gpu`.
 *
 * NOTE: these are GPU-only base rates. Modal also bills CPU cores + memory
 * on top (~+25% on a typical job), per-second rounding adds a little more,
 * and we'd rather over-debit the beta cap than under-debit. So the pre-flight
 * estimate multiplies by `COST_SAFETY_MARGIN` (see `estimateJobCost`). The
 * post-run reconciliation path stays true-cost (no margin).
 *
 * When a manifest reports a GPU we don't recognise, we fall back to the
 * HIGHEST known rate so an unknown GPU can never under-count.
 */

import { Prisma } from "@papercrane/db";

export const GPU_PRICE_PER_SECOND_USD: Record<string, number> = {
  T4: 0.000164, // ~$0.59/hr
  L4: 0.000222, // ~$0.80/hr
  A10: 0.000306, // ~$1.10/hr
  A10G: 0.000306, // ~$1.10/hr (AWS name for A10)
  L40S: 0.000542, // ~$1.95/hr
  "A100-40GB": 0.000583, // ~$2.10/hr
  "A100-80GB": 0.000694, // ~$2.50/hr
  H100: 0.001097, // ~$3.95/hr
  "H100-80GB": 0.001097, // ~$3.95/hr (alias)
  H200: 0.001261, // ~$4.54/hr
  B200: 0.001736, // ~$6.25/hr
};

/**
 * Conservative fallback rate for an unrecognised GPU: the highest known rate,
 * so an unknown GPU over-estimates rather than under-counting the cap.
 */
const FALLBACK_PRICE_PER_SECOND_USD = Math.max(
  ...Object.values(GPU_PRICE_PER_SECOND_USD),
);

/** Label for the fallback rate (the priciest known GPU), kept in sync. */
export const DEFAULT_FALLBACK_GPU =
  Object.entries(GPU_PRICE_PER_SECOND_USD).find(
    ([, price]) => price === FALLBACK_PRICE_PER_SECOND_USD,
  )?.[0] ?? "A100-80GB";

/** Last-resort estimate when the manifest omits `estSecondsPerDesign`. */
export const DEFAULT_SECONDS_PER_DESIGN = 120;

/**
 * Multiplier applied to the GPU-only pre-flight estimate to cover Modal's
 * CPU+memory add-on, per-second rounding, and minor variance. Tunable via
 * `PAPERCRANE_COST_SAFETY_MARGIN` (must be >= 1). Estimates round UP so the
 * beta spend cap blocks early rather than late.
 */
export const DEFAULT_COST_SAFETY_MARGIN = 1.4;

export function getCostSafetyMargin(): number {
  const raw = Number(process.env.PAPERCRANE_COST_SAFETY_MARGIN);
  return Number.isFinite(raw) && raw >= 1 ? raw : DEFAULT_COST_SAFETY_MARGIN;
}

export interface EstimateJobCostOpts {
  gpuType: string;
  estSecondsPerDesign: number;
  numSeeds: number;
}

export interface EstimateJobCostBreakdown {
  gpuType: string;
  /** True when we substituted DEFAULT_FALLBACK_GPU because gpuType was unknown. */
  fallbackUsed: boolean;
  pricePerSecondUsd: number;
  secondsPerDesign: number;
  numSeeds: number;
  perSeedUsd: number;
  /** Safety multiplier applied to the GPU-only total (see COST_SAFETY_MARGIN). */
  safetyMargin: number;
}

export interface EstimateJobCostResult {
  /** Total estimated cost as a Decimal so callers can persist without rounding. */
  usd: Prisma.Decimal;
  breakdown: EstimateJobCostBreakdown;
}

/**
 * Round a positive number to 4 decimal places before handing it to Decimal.
 * Prisma's Decimal constructor accepts a string, which is the safest way to
 * avoid float drift biting us on numbers like `0.1 + 0.2`.
 */
function toDecimal(value: number): Prisma.Decimal {
  // Guard against negative inputs (shouldn't happen) and NaN.
  const safe = Number.isFinite(value) && value > 0 ? value : 0;
  return new Prisma.Decimal(safe.toFixed(4));
}

/**
 * Project a dollar cost for a job from its tool manifest. Returns both the
 * total and a breakdown for UI display.
 */
export function estimateJobCost(opts: EstimateJobCostOpts): EstimateJobCostResult {
  const { gpuType, estSecondsPerDesign, numSeeds } = opts;
  const knownPrice = GPU_PRICE_PER_SECOND_USD[gpuType];
  const fallbackUsed = knownPrice === undefined;
  const pricePerSecondUsd: number =
    knownPrice ?? FALLBACK_PRICE_PER_SECOND_USD;
  const secondsPerDesign =
    estSecondsPerDesign > 0 ? estSecondsPerDesign : DEFAULT_SECONDS_PER_DESIGN;
  const safeSeeds = Math.max(1, Math.floor(numSeeds));
  const safetyMargin = getCostSafetyMargin();

  const perSeedUsd = pricePerSecondUsd * secondsPerDesign;
  const totalUsd = perSeedUsd * safeSeeds * safetyMargin;

  return {
    usd: toDecimal(totalUsd),
    breakdown: {
      gpuType: fallbackUsed ? DEFAULT_FALLBACK_GPU : gpuType,
      fallbackUsed,
      pricePerSecondUsd,
      secondsPerDesign,
      numSeeds: safeSeeds,
      perSeedUsd: Number(perSeedUsd.toFixed(6)),
      safetyMargin,
    },
  };
}

/**
 * Post-completion reconciliation: convert Modal-reported runtime seconds to
 * a dollar amount. Returns `null` when the GPU is unknown AND the caller
 * doesn't want a fallback (pass `allowFallback: false`).
 */
export function actualCostFromModalSeconds(
  gpuType: string,
  secondsActual: number,
  allowFallback = true,
): Prisma.Decimal | null {
  const known = GPU_PRICE_PER_SECOND_USD[gpuType];
  let price: number;
  if (known === undefined) {
    if (!allowFallback) return null;
    price = FALLBACK_PRICE_PER_SECOND_USD;
  } else {
    price = known;
  }
  const safeSeconds = Math.max(0, secondsActual);
  return toDecimal(price * safeSeconds);
}
