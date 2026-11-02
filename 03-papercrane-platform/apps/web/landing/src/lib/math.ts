import bezier from "bezier-easing";

export const math = {
  fit(
    v: number,
    fMin: number,
    fMax: number,
    tMin: number,
    tMax: number,
    easing?: (t: number) => number,
  ): number {
    const t = (v - fMin) / (fMax - fMin);
    const clamped = Math.max(0, Math.min(1, t));
    const eased = easing ? easing(clamped) : clamped;
    return tMin + eased * (tMax - tMin);
  },
  clamp(v: number, lo: number, hi: number): number {
    return Math.max(lo, Math.min(hi, v));
  },
};

const _lusion = bezier(0.35, 0, 0, 1);

export const ease = {
  cubicInOut: (t: number) =>
    t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
  // Verified from Lusion's bundle: cubic-bezier(0.35, 0, 0, 1).
  lusion: (t: number) => _lusion(t),
  backOut: (t: number) =>
    1 + 2.70158 * Math.pow(t - 1, 3) + 1.70158 * Math.pow(t - 1, 2),
};
