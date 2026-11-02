/**
 * CSV serialisation for Design[].
 *
 * Columns
 * -------
 * Fixed leading columns (stable order so spreadsheets diff cleanly):
 *   id, seed, sequence, length, tool
 * followed by a DYNAMIC set of metric columns: the union of every metric
 * present across the exported designs, rendered under canonical labels
 * (ipSAE, ipTM, pAE, pDockQ, DockQ, pTM, pLDDT, …). A design missing a given
 * metric exports a blank cell for that column.
 *
 * Metric keys are resolved CASE-INSENSITIVELY and across common aliases, so
 * the lowercase/suffixed keys the worker and adapters actually emit
 * (iptm, ipsae, pae/ipae_mean, pdockq, plddt/plddt_mean, dockq, ptm) all land
 * in the right column instead of exporting blank. This mirrors the `pick()`
 * resolver in components/designs/CompareView.tsx.
 *
 * Quoting follows RFC 4180: any field containing a comma, double-quote, CR,
 * or LF is wrapped in double quotes and embedded quotes are doubled.
 */

import { normaliseDesignProvenance } from "@papercrane/types";

export interface CsvDesignInput {
  id: string;
  seed: number;
  sequence?: string | null;
  length?: number | null;
  tool?: string | null;
  provenance?: string | null;
  metrics?: Record<string, number | undefined>;
}

/** Fixed, always-present leading columns (in order). */
export const CSV_LEADING_COLUMNS = [
  "id",
  "seed",
  "sequence",
  "length",
  "tool",
  "provenance",
] as const;

/**
 * Canonical metric column specs. `label` is the header text; `aliases` are
 * the lowercase variants the worker/adapters emit. Resolution is always
 * case-insensitive, and the label itself is implicitly an alias. Order here
 * defines header order for known metrics (best ranking metric first).
 */
interface MetricSpec {
  label: string;
  aliases: string[];
}

const METRIC_SPECS: MetricSpec[] = [
  { label: "ipSAE", aliases: ["ipsae"] },
  { label: "ipTM", aliases: ["iptm"] },
  { label: "pAE", aliases: ["pae", "ipae_mean", "ipae"] },
  { label: "pDockQ", aliases: ["pdockq"] },
  { label: "DockQ", aliases: ["dockq"] },
  { label: "pTM", aliases: ["ptm"] },
  { label: "pLDDT", aliases: ["plddt", "plddt_mean"] },
];

/** Lowercased alias → canonical label (includes each label keyed by itself). */
const ALIAS_TO_LABEL = new Map<string, string>();
for (const spec of METRIC_SPECS) {
  ALIAS_TO_LABEL.set(spec.label.toLowerCase(), spec.label);
  for (const a of spec.aliases) ALIAS_TO_LABEL.set(a.toLowerCase(), spec.label);
}
const KNOWN_LABEL_ORDER = new Map<string, number>(
  METRIC_SPECS.map((s, i) => [s.label, i]),
);

/** RFC 4180 quoting. Numeric/empty values pass through unquoted. */
export function csvEscape(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "";
  }
  const s = String(value);
  if (/[",\r\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

/**
 * Resolve the value for a canonical metric column from a design's metrics,
 * matching the column label and all of its aliases case-insensitively.
 */
function resolveMetric(
  metrics: Record<string, number | undefined> | undefined,
  column: string,
): number | undefined {
  if (!metrics) return undefined;
  // For known columns, the column maps to a label; for unknown (passthrough)
  // columns the column IS the raw key: both are handled by lowercase match.
  const wantLabel = ALIAS_TO_LABEL.get(column.toLowerCase());
  for (const [key, value] of Object.entries(metrics)) {
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    const lower = key.toLowerCase();
    if (wantLabel) {
      if (ALIAS_TO_LABEL.get(lower) === wantLabel) return value;
    } else if (lower === column.toLowerCase()) {
      return value;
    }
  }
  return undefined;
}

/**
 * Compute the dynamic metric column labels present across the given designs.
 * Known metrics come first in canonical order; any unrecognised keys are
 * appended (deduped, by display key) in sorted order so the header is stable.
 */
function metricColumns(designs: CsvDesignInput[]): string[] {
  const known = new Set<string>();
  const unknown = new Set<string>();
  for (const d of designs) {
    if (!d.metrics) continue;
    for (const [key, value] of Object.entries(d.metrics)) {
      if (typeof value !== "number" || !Number.isFinite(value)) continue;
      const label = ALIAS_TO_LABEL.get(key.toLowerCase());
      if (label) known.add(label);
      else unknown.add(key);
    }
  }
  const knownCols = [...known].sort(
    (a, b) => (KNOWN_LABEL_ORDER.get(a) ?? 0) - (KNOWN_LABEL_ORDER.get(b) ?? 0),
  );
  const unknownCols = [...unknown].sort();
  return [...knownCols, ...unknownCols];
}

export function formatCsvRow(d: CsvDesignInput, metricCols: string[]): string {
  const cells: unknown[] = [
    d.id,
    d.seed,
    d.sequence ?? "",
    d.length ?? "",
    d.tool ?? "",
    normaliseDesignProvenance(d.provenance),
    ...metricCols.map((col) => resolveMetric(d.metrics, col)),
  ];
  return cells.map(csvEscape).join(",");
}

export function formatCsv(designs: CsvDesignInput[]): string {
  const metricCols = metricColumns(designs);
  const header = [...CSV_LEADING_COLUMNS, ...metricCols];
  const lines = [header.map(csvEscape).join(",")];
  for (const d of designs) lines.push(formatCsvRow(d, metricCols));
  // Trailing newline: many CLI tools (awk, csvkit) require it.
  return lines.join("\n") + "\n";
}
