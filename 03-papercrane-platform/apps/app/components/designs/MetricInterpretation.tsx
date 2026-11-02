/**
 * MetricInterpretation: turns raw Design metrics into a verdict a
 * non-scientist can read, without ever implying a binding probability.
 *
 * The verdict is a *scoring heuristic over in-silico metrics*, nothing more.
 * It reuses the project's own pre-registered hit definition so the badge is
 * auditable rather than invented:
 *
 *   benchmark/methodology-v1.0.md §"Hit definition"
 *     hit = (ipSAE >= 0.70) AND (DockQ >= 0.23) AND (pTMEnergy <= -1.2)
 *
 * Metric key names + valid ranges come from the persist-boundary validator,
 * apps/worker/src/metrics/validate.ts. That validator normalises adapter
 * output to canonical labels (`ipSAE`, `DockQ`, `pLDDT`, `pAE`, `ipTM`), but
 * pTMEnergy is not a known spec there, so it survives verbatim in whatever
 * casing the adapter emitted (`ptmenergy` in the demo seed). Every lookup
 * here is therefore case-insensitive over the documented alias set.
 *
 * Per docs/LLM-META-SCORER.md this must never be presented as `P(bind)`, a
 * predicted hit, or an experimental success rate: only as structural
 * confidence / predicted interface quality.
 */

import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/* Metric resolution                                                    */

/**
 * Canonical metric label → lowercase aliases, mirroring METRIC_SPECS in
 * apps/worker/src/metrics/validate.ts. `pTMEnergy` is an unknown key to that
 * validator (preserved verbatim), so its aliases are the casings actually
 * emitted downstream (`ptmenergy` in packages/db seed + benchmark schema).
 */
const METRIC_ALIASES: Record<string, string[]> = {
  ipSAE: [
    "ipsae",
    "min_ipsae",
    "best_ipsae",
    "computational__boltz2_min_ipsae",
  ],
  DockQ: ["dockq"],
  pTMEnergy: ["ptmenergy", "ptm_energy"],
  ipTM: ["iptm"],
  pLDDT: ["plddt", "plddt_mean"],
  pAE: ["pae", "ipae", "ipae_mean"],
};

/** Whether a stored key is a documented alias for a canonical metric. */
export function isMetricKey(key: string, canonical: string): boolean {
  const lowerKey = key.toLowerCase();
  return [canonical, ...(METRIC_ALIASES[canonical] ?? [])].some(
    (candidate) => candidate.toLowerCase() === lowerKey,
  );
}

/** Case-insensitive numeric lookup across a metric's documented aliases. */
export function readMetric(
  metrics: Record<string, unknown> | null | undefined,
  canonical: string,
): number | null {
  if (!metrics) return null;
  for (const [key, value] of Object.entries(metrics)) {
    if (!isMetricKey(key, canonical)) continue;
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

/* ------------------------------------------------------------------ */
/* Verdict model                                                        */

export type VerdictLevel = "strong" | "promising" | "weak" | "inconclusive";

export interface CriterionReading {
  /** Canonical metric label. */
  metric: string;
  /** Observed value, or null when the metric is absent from the JSONB blob. */
  value: number | null;
  /** Pre-registered threshold from benchmark/methodology-v1.0.md. */
  threshold: number;
  /** Which side of the threshold counts as good. */
  direction: "atLeast" | "atMost";
  /** Decimal places for display. */
  digits: number;
  /** null when the value is missing: never guessed. */
  met: boolean | null;
  /** One plain sentence about what this metric measures. */
  plain: string;
}

export interface DesignVerdict {
  level: VerdictLevel;
  /** Badge text: "Strong" | "Promising" | "Weak" | "Inconclusive". */
  label: string;
  /** One plain-language sentence for a non-scientist. */
  headline: string;
  /** Criteria met out of `total` (0 when any input is missing). */
  met: number;
  total: number;
  criteria: CriterionReading[];
  /** Canonical labels of criteria metrics that were absent. */
  missing: string[];
}

/** Pre-registered hit criteria: benchmark/methodology-v1.0.md line 68. */
const CRITERIA: Array<
  Pick<
    CriterionReading,
    "metric" | "threshold" | "direction" | "digits" | "plain"
  >
> = [
  {
    metric: "ipSAE",
    threshold: 0.7,
    direction: "atLeast",
    digits: 2,
    plain:
      "How confident the model is about the contact between your binder and the target: higher means a better-defined interface.",
  },
  {
    metric: "DockQ",
    threshold: 0.23,
    direction: "atLeast",
    digits: 2,
    plain:
      "How closely the predicted binder/target pose resembles a real docked complex: 0.23 is the standard cutoff for an acceptable pose.",
  },
  {
    metric: "pTMEnergy",
    threshold: -1.2,
    direction: "atMost",
    digits: 2,
    plain:
      "An energy-style read of the interface that is independent of ipSAE: more negative means a tighter predicted interface.",
  },
];

/** Context metrics shown alongside the verdict but not part of it. */
const CONTEXT_METRICS: Array<{
  metric: string;
  digits: number;
  plain: string;
}> = [
  {
    metric: "ipTM",
    digits: 2,
    plain:
      "The folding model's own 0–1 confidence that the two chains are arranged correctly relative to each other.",
  },
  {
    metric: "pLDDT",
    digits: 1,
    plain:
      "How confident the model is in the shape of each individual residue, on a 0–100 scale: above ~80 is a well-formed fold.",
  },
  {
    metric: "pAE",
    digits: 2,
    plain:
      "The model's expected positional error in ångströms: lower means the two chains are pinned down more precisely.",
  },
];

/**
 * Score a design against the pre-registered criteria.
 *
 * Deliberately conservative: if any criterion metric is absent we return
 * "Inconclusive" rather than extrapolating from the metrics we do have.
 */
export function interpretDesign(
  metrics: Record<string, unknown> | null | undefined,
): DesignVerdict {
  const criteria: CriterionReading[] = CRITERIA.map((c) => {
    const value = readMetric(metrics, c.metric);
    const met =
      value == null
        ? null
        : c.direction === "atLeast"
          ? value >= c.threshold
          : value <= c.threshold;
    return { ...c, value, met };
  });

  const missing = criteria.filter((c) => c.value == null).map((c) => c.metric);
  const total = criteria.length;

  if (missing.length > 0) {
    return {
      level: "inconclusive",
      label: "Inconclusive",
      headline: `Not enough was measured to judge this design: ${listify(
        missing,
      )} ${missing.length === 1 ? "is" : "are"} missing.`,
      met: 0,
      total,
      criteria,
      missing,
    };
  }

  const met = criteria.filter((c) => c.met === true).length;

  if (met === total) {
    return {
      level: "strong",
      label: "Strong",
      headline:
        "Clears all three pre-registered checks: the strongest structural confidence this scoring can report.",
      met,
      total,
      criteria,
      missing,
    };
  }
  if (met === total - 1) {
    return {
      level: "promising",
      label: "Promising",
      headline:
        "Clears most of the pre-registered checks: worth a closer look, but the interface signal is not unanimous.",
      met,
      total,
      criteria,
      missing,
    };
  }
  return {
    level: "weak",
    label: "Weak",
    headline:
      "Falls short on most of the pre-registered checks: the predicted interface quality is low.",
    met,
    total,
    criteria,
    missing,
  };
}

function listify(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** "ipSAE 0.78 (strong: ≥ 0.70)": value next to the threshold it was judged on. */
export function formatCriterion(c: CriterionReading): string {
  const op = c.direction === "atLeast" ? "≥" : "≤";
  const threshold = formatNumber(c.threshold, c.digits);
  if (c.value == null) return `${c.metric}: (strong: ${op} ${threshold})`;
  return `${c.metric} ${formatNumber(c.value, c.digits)} (strong: ${op} ${threshold})`;
}

function formatNumber(v: number, digits: number): string {
  return v.toFixed(digits).replace("-", "−");
}

/* ------------------------------------------------------------------ */
/* Badge                                                                */

const BADGE_STYLES: Record<VerdictLevel, string> = {
  strong: "border-ink bg-ink text-paper",
  promising: "border-lattice-strong bg-paper text-ink",
  weak: "border-lattice bg-paper text-graphite-soft",
  inconclusive:
    "border-dashed border-lattice-strong bg-paper-fold/60 text-graphite-soft",
};

/**
 * Compact verdict pill for list rows and cards. Amber is reserved for the
 * provenance warning, so the verdict ladder stays monochrome.
 */
export function DesignVerdictBadge({
  verdict,
  className,
}: {
  verdict: DesignVerdict;
  className?: string;
}) {
  const detail =
    verdict.level === "inconclusive"
      ? `Inconclusive: missing ${listify(verdict.missing)}`
      : `${verdict.met} of ${verdict.total} pre-registered checks met · ${verdict.criteria
          .map(formatCriterion)
          .join(" · ")}`;
  return (
    <span
      title={detail}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-md border px-1.5 py-0.5",
        "font-sans text-[9px]",
        BADGE_STYLES[verdict.level],
        className,
      )}
    >
      {verdict.label}
      {verdict.level !== "inconclusive" && (
        <span className="opacity-70 tabular-nums">
          {verdict.met}/{verdict.total}
        </span>
      )}
      <span className="sr-only">. {detail}</span>
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Full panel                                                           */

/**
 * Detail-view panel: the verdict, every criterion shown next to the
 * threshold it was judged against, the supporting metrics, and a collapsed
 * "How to read these numbers" explainer.
 */
export function MetricInterpretation({
  metrics,
  className,
}: {
  metrics: Record<string, unknown> | null | undefined;
  className?: string;
}) {
  const verdict = interpretDesign(metrics);
  const context = CONTEXT_METRICS.map((c) => ({
    ...c,
    value: readMetric(metrics, c.metric),
  }));

  return (
    <section
      aria-labelledby="metric-interpretation-title"
      className={cn(
        "rounded-lg border border-lattice bg-paper-fold/40 p-5",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3
            id="metric-interpretation-title"
            className="font-sans text-[12px] text-ink"
          >
            What these numbers mean
          </h3>
          <p className="mt-0.5 font-sans text-[9px] text-graphite-soft">
            Structural confidence · computational only
          </p>
        </div>
        <DesignVerdictBadge verdict={verdict} className="mt-0.5" />
      </div>

      <p className="mt-4 font-sans text-[13px] leading-relaxed text-graphite">
        {verdict.headline}
      </p>

      <div className="mt-5 pt-4">
        <div className="font-sans text-[9px] text-graphite-soft">
          Pre-registered checks{" "}
          {verdict.level === "inconclusive"
            ? "· incomplete"
            : `· ${verdict.met} of ${verdict.total} met`}
        </div>
        <ul className="mt-2.5 space-y-2">
          {verdict.criteria.map((c) => (
            <li
              key={c.metric}
              className="flex items-baseline justify-between gap-3"
              title={c.plain}
            >
              <span className="font-sans text-[12px] text-graphite">
                {c.metric}
              </span>
              <span className="flex items-baseline gap-2 text-right">
                <span
                  className={cn(
                    "font-mono text-[13px] tabular-nums",
                    c.met === null ? "text-graphite-soft" : "text-ink",
                  )}
                >
                  {c.value == null ? "N/A" : formatNumber(c.value, c.digits)}
                </span>
                <span className="font-mono text-[10px] tabular-nums text-graphite-soft">
                  strong: {c.direction === "atLeast" ? "≥" : "≤"}{" "}
                  {formatNumber(c.threshold, c.digits)}
                </span>
                <span
                  aria-hidden
                  className={cn(
                    "w-3 font-mono text-[11px]",
                    c.met === true
                      ? "text-ink"
                      : c.met === false
                        ? "text-graphite-soft"
                        : "text-graphite-soft/60",
                  )}
                >
                  {c.met === true ? "✓" : c.met === false ? "✗" : "?"}
                </span>
                <span className="sr-only">
                  {c.met === true
                    ? "meets threshold"
                    : c.met === false
                      ? "below threshold"
                      : "not measured"}
                </span>
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2.5 font-sans text-[10px] leading-relaxed text-graphite-soft">
          Thresholds are the project&apos;s pre-registered definition
          (benchmark methodology v1.0), fixed before any results were scored.
        </p>
      </div>

      {context.some((c) => c.value != null) && (
        <div className="mt-5 pt-4">
          <div className="font-sans text-[9px] text-graphite-soft">
            Supporting numbers · not part of the verdict
          </div>
          <ul className="mt-2.5 space-y-2">
            {context
              .filter((c) => c.value != null)
              .map((c) => (
                <li
                  key={c.metric}
                  className="flex items-baseline justify-between gap-3"
                  title={c.plain}
                >
                  <span className="font-sans text-[12px] text-graphite">
                    {c.metric}
                  </span>
                  <span className="font-mono text-[13px] tabular-nums text-ink">
                    {formatNumber(c.value as number, c.digits)}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      )}

      <HowToReadPanel />

      <p className="mt-4 border-t border-lattice pt-4 font-sans text-[11px] leading-relaxed text-amber-800">
        This is a scoring heuristic over predicted structures, not a
        prediction that the binder will work. It is not a probability of
        binding and not an experimental success rate. Only a wet-lab assay can
        tell you whether a design binds.
      </p>
    </section>
  );
}

/** Collapsible glossary. `<details>` so it needs no client state. */
export function HowToReadPanel({ className }: { className?: string }) {
  const entries = [...CRITERIA, ...CONTEXT_METRICS];
  return (
    <details
      className={cn("mt-5 border-t border-lattice pt-4", className)}
    >
      <summary className="cursor-pointer list-none font-sans text-[9px] text-graphite-soft hover:text-graphite">
        How to read these numbers ▾
      </summary>
      <dl className="mt-3 space-y-2.5">
        {entries.map((e) => (
          <div key={e.metric}>
            <dt className="font-sans text-[12px] text-ink">
              {e.metric}
            </dt>
            <dd className="mt-0.5 font-sans text-[12px] leading-relaxed text-graphite">
              {e.plain}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 font-sans text-[12px] leading-relaxed text-graphite">
        <span className="font-semibold text-ink">What to do next:</span> order
        or test the &ldquo;Strong&rdquo; designs first and treat
        &ldquo;Promising&rdquo; as backups: the numbers rank candidates
        against each other, they do not tell you any single one will bind.
      </p>
    </details>
  );
}
