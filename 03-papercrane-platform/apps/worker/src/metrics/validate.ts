/**
 * Metric integrity guard for the worker persist boundary.
 *
 * Adapters and provider stubs emit metrics under inconsistent casings
 * (`iptm`/`ipsae`/`plddt`) and suffixed aliases (`plddt_mean`/`ipae_mean`),
 * and occasionally with physically impossible values. The UI/export layer
 * resolves canonical labels (see apps/app/lib/export/csv.ts and CompareView),
 * but the value persisted into the Design row was previously the raw, unchecked
 * adapter output — so out-of-casing keys rendered blank and out-of-range junk
 * was indistinguishable from real numbers.
 *
 * `validateMetrics` normalises every known key to its canonical label, drops
 * out-of-range / non-finite known metrics (with a warning rather than a hard
 * failure — we never want to lose a real result over one bad number), and
 * preserves every unknown key and non-numeric passthrough value verbatim.
 */

/** Canonical metric label → the lowercase aliases adapters actually emit. */
interface MetricSpec {
  /** Canonical label stored on the Design row + rendered by the UI. */
  label: string;
  /** Lowercase aliases (the label itself is always an implicit alias). */
  aliases: string[];
  /** Inclusive numeric range a value must fall in to be kept. */
  range: { min: number; max: number };
}

// Mirrors the resolver in apps/app/lib/export/csv.ts so the persisted casing
// matches what the UI/export look up. Ranges follow the standard metric
// definitions: unit-interval scores in [0,1], pLDDT a percentage in [0,100],
// pAE a non-negative distance in Å.
const METRIC_SPECS: MetricSpec[] = [
  { label: 'ipSAE', aliases: ['ipsae'], range: { min: 0, max: 1 } },
  { label: 'ipTM', aliases: ['iptm'], range: { min: 0, max: 1 } },
  { label: 'pDockQ', aliases: ['pdockq'], range: { min: 0, max: 1 } },
  { label: 'pTM', aliases: ['ptm'], range: { min: 0, max: 1 } },
  { label: 'DockQ', aliases: ['dockq'], range: { min: 0, max: 1 } },
  { label: 'pLDDT', aliases: ['plddt', 'plddt_mean'], range: { min: 0, max: 100 } },
  { label: 'pAE', aliases: ['pae', 'ipae_mean', 'ipae'], range: { min: 0, max: Infinity } },
];

/** Lowercased alias → spec (each label keyed by itself too). */
const ALIAS_TO_SPEC = new Map<string, MetricSpec>();
for (const spec of METRIC_SPECS) {
  ALIAS_TO_SPEC.set(spec.label.toLowerCase(), spec);
  for (const a of spec.aliases) ALIAS_TO_SPEC.set(a.toLowerCase(), spec);
}

export interface MetricValidationResult {
  /** Normalised metrics: canonical known keys + preserved passthrough keys. */
  metrics: Record<string, unknown>;
  /** True when no value had to be dropped. */
  valid: boolean;
  /** Human-readable notes for each dropped/coerced value. */
  warnings: string[];
}

/**
 * Validate and normalise raw adapter metrics.
 *
 * Never throws and never hard-fails: a bad value is dropped and noted in
 * `warnings`, leaving every other metric intact so a real result is preserved.
 */
export function validateMetrics(
  raw: Record<string, unknown> | null | undefined,
): MetricValidationResult {
  const metrics: Record<string, unknown> = {};
  const warnings: string[] = [];

  if (raw == null || typeof raw !== 'object') {
    return { metrics, valid: true, warnings };
  }

  for (const [key, value] of Object.entries(raw)) {
    const spec = ALIAS_TO_SPEC.get(key.toLowerCase());

    if (!spec) {
      // Unknown key — preserve verbatim (composite, interfaceSC, provenance,
      // sequence, length, cifFallbackPdb, …).
      metrics[key] = value;
      continue;
    }

    if (typeof value !== 'number') {
      // A known metric carrying a non-numeric value is anomalous but we don't
      // want to silently lose data — keep it under the canonical label.
      metrics[spec.label] = value;
      continue;
    }

    if (!Number.isFinite(value)) {
      warnings.push(`dropped ${spec.label}: non-finite value (${String(value)})`);
      continue;
    }

    if (value < spec.range.min || value > spec.range.max) {
      const hi = spec.range.max === Infinity ? '∞' : String(spec.range.max);
      warnings.push(
        `dropped ${spec.label}: ${value} out of range [${spec.range.min}, ${hi}]`,
      );
      continue;
    }

    metrics[spec.label] = value;
  }

  return { metrics, valid: warnings.length === 0, warnings };
}
