/**
 * ProvenanceBadge: surfaces the recorded `designs.provenance`, with absent
 * or unrecognised values kept unverified.
 *
 * The column exists precisely because fabricated dev rows were
 * indistinguishable from real GPU output. Anything that isn't 'real' gets an
 * amber, outlined, impossible-to-miss marker. Amber is reserved for this in
 * the designs surface so the warning never competes with a metric badge.
 */

import { cn } from "@/lib/utils";
import { normaliseDesignProvenance } from "@papercrane/types";

export type ProvenanceLevel = "real" | "synthetic" | "stub" | "unknown";

export function normaliseProvenance(
  provenance: string | null | undefined,
): ProvenanceLevel {
  return normaliseDesignProvenance(provenance);
}

/** True when origin is fabricated or unverified and must be flagged. */
export function isFabricated(provenance: string | null | undefined): boolean {
  return normaliseProvenance(provenance) !== "real";
}

const COPY: Record<Exclude<ProvenanceLevel, "real">, { tag: string; detail: string }> = {
  synthetic: {
    tag: "Example data",
    detail:
      "Example data from a synthetic development fixture.",
  },
  stub: {
    tag: "Example data",
    detail:
      "Example data: placeholder metrics from the Modal stub path, generated without a GPU run.",
  },
  unknown: {
    tag: "Unverified origin",
    detail:
      "Origin unverified. GPU execution has not been confirmed for this design.",
  },
};

/**
 * Inline pill for list rows, table cells and cards. Renders nothing for real
 * model output so genuine results stay uncluttered.
 */
export function ProvenanceBadge({
  provenance,
  className,
}: {
  provenance: string | null | undefined;
  className?: string;
}) {
  const level = normaliseProvenance(provenance);
  if (level === "real") return null;
  const { tag, detail } = COPY[level];
  return (
    <span
      title={detail}
      className={cn(
        "inline-flex shrink-0 items-center rounded-md border border-amber-500 bg-amber-50 px-1.5 py-0.5",
        "font-sans text-[9px] font-semibold text-amber-800",
        className,
      )}
    >
      {tag}
      <span className="sr-only">. {detail}</span>
    </span>
  );
}

/**
 * Full-width banner for the detail view. Non-dismissable: a fabricated design
 * must never be mistakable for a genuine result.
 */
export function ProvenanceBanner({
  provenance,
  className,
}: {
  provenance: string | null | undefined;
  className?: string;
}) {
  const level = normaliseProvenance(provenance);
  if (level === "real") return null;
  const { detail } = COPY[level];
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-lg border-2 border-amber-500/70 bg-amber-100/70 px-5 py-4",
        className,
      )}
    >
      <span className="mt-0.5 inline-flex shrink-0 items-center rounded-md bg-amber-600 px-2 py-1 font-sans text-[12px] font-bold text-white">
        {level}
      </span>
      <div className="font-sans text-[13px] leading-relaxed text-amber-900">
        <span className="font-semibold uppercase tracking-[0.08em]">
          Execution provenance
        </span>{" "}
        {detail}
      </div>
    </div>
  );
}
