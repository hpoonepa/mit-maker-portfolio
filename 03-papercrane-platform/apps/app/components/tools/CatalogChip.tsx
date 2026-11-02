import { catalogCategoryLabel } from "@papercrane/types";

/**
 * CatalogChip: small monocaps data line.
 *
 * Used inside CatalogCard / DetailMeta to render a label-value pair in the
 * editorial style: tracking-wide all-caps eyebrow on the left, mono value
 * on the right, separated by a hairline rule. No background, no shadow.
 */
type CatalogChipProps = {
  label: string;
  value: string;
};

export function CatalogChip({ label, value }: CatalogChipProps) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <span className="font-sans text-[12px] text-graphite-soft">
        {label}
      </span>
      <span className="font-mono text-[12px] tracking-tight text-ink">
        {value}
      </span>
    </div>
  );
}

/**
 * Map manifest/DB category vocab → human display label. Delegates to the
 * shared `catalogCategoryLabel` taxonomy in `@papercrane/types`, which maps
 * any category vocab into one of the four canonical catalog labels so the
 * catalog and picker stay in sync from a single source of truth.
 */
export function familyLabel(category: string): string {
  return catalogCategoryLabel(category);
}

/**
 * Format `timePerDesignSeconds` from the catalog proc into a humane string
 * without inventing numbers: if the proc returns 0, we say so.
 */
export function formatRuntime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Not reported";
  if (seconds < 60) return `${Math.round(seconds)} s / design`;
  const minutes = seconds / 60;
  if (minutes < 60) {
    return `${minutes < 10 ? minutes.toFixed(1) : Math.round(minutes)} min / design`;
  }
  const hours = minutes / 60;
  return `${hours < 10 ? hours.toFixed(1) : Math.round(hours)} h / design`;
}

/**
 * Format the `gpuType` / `gpuCount` / `minVramGb` triple from the proc
 * compactly: "1× H100 · 80 GB" or "CPU" when no GPU is reported.
 */
export function formatGpuClass(
  gpuType: string,
  gpuCount: number,
  minVramGb: number,
): string {
  if (!gpuType || gpuType === "CPU") return "CPU only";
  const count = gpuCount > 0 ? `${gpuCount}× ` : "";
  const vram = minVramGb > 0 ? ` · ${minVramGb} GB` : "";
  return `${count}${gpuType}${vram}`;
}
