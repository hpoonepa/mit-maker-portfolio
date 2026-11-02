"use client";

import Link from "next/link";
import { ArrowUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { StarButton } from "@/components/annotations/StarButton";
import { ProvenanceBadge } from "@/components/designs/ProvenanceBadge";
import {
  resultMetrics,
  formatResultMetric,
  toolLabel,
} from "@/lib/results/metrics";

export type SortKey = string;
export type SortColumn = string;
export interface DesignTableRow {
  id: string;
  seed: number;
  tool?: string | null;
  provenance?: string | null;
  metrics: Record<string, unknown>;
  createdAt?: string;
}
export function metricColumns(rows: DesignTableRow[]) {
  const columns = new Map<
    string,
    { label: string; direction?: "low" | "high" }
  >();
  for (const row of rows)
    for (const metric of resultMetrics(row.tool, row.metrics)) {
      columns.set(metric.label, {
        label: metric.label,
        direction: metric.direction,
      });
    }
  return Array.from(columns.values());
}
export function sortDesignRows<T extends DesignTableRow>(
  rows: T[],
  sort: SortKey,
): T[] {
  const direction = sort.endsWith(":asc") ? 1 : -1;
  const key = sort.replace(/:(asc|desc)$/, "");
  const value = (row: T): number | undefined => {
    if (key === "seed") return row.seed;
    if (key === "created") {
      const n = Date.parse(row.createdAt ?? "");
      return Number.isFinite(n) ? n : undefined;
    }
    return resultMetrics(row.tool, row.metrics).find(
      (m) => `metric:${m.label}` === key,
    )?.value;
  };
  return [...rows].sort((a, b) => {
    const av = value(a),
      bv = value(b);
    if (av == null) return bv == null ? 0 : 1;
    if (bv == null) return -1;
    return (av - bv) * direction;
  });
}
export interface DesignsTableProps {
  rows: DesignTableRow[];
  hoverId: string | null;
  onHover: (id: string | null) => void;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onSelectAll: (ids: string[]) => void;
  onClearAll: () => void;
  starredSet: Set<string>;
  sortBy: SortKey;
  onToggleSort: (col: SortColumn) => void;
}
export function DesignsTable({
  rows,
  hoverId,
  onHover,
  selectedIds,
  onToggleSelect,
  onSelectAll,
  onClearAll,
  starredSet,
  sortBy,
  onToggleSort,
}: DesignsTableProps) {
  const columns = metricColumns(rows);
  const allSelected =
    rows.length > 0 && rows.every((r) => selectedIds.has(r.id));
  const header = (key: string, label: string) => (
    <th
      key={key}
      scope="col"
      aria-sort={
        sortBy === `${key}:asc`
          ? "ascending"
          : sortBy === `${key}:desc`
            ? "descending"
            : "none"
      }
      className="px-4 py-3 text-right text-xs font-medium whitespace-nowrap"
    >
      <button
        className="inline-flex items-center gap-1"
        onClick={() => onToggleSort(key)}
      >
        {label}
        {sortBy.startsWith(`${key}:`) && (
          <ArrowUp
            className={cn("h-3 w-3", sortBy.endsWith(":desc") && "rotate-180")}
          />
        )}
      </button>
    </th>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left font-sans">
        <thead className="text-graphite">
          <tr>
            <th scope="col" className="w-10 px-3 py-3">
              <input
                type="checkbox"
                aria-label={
                  allSelected ? "Clear selection" : "Select all visible"
                }
                checked={allSelected}
                onChange={() =>
                  allSelected
                    ? onClearAll()
                    : onSelectAll(rows.map((r) => r.id))
                }
              />
            </th>
            <th scope="col" className="px-4 py-3 text-xs font-medium">
              Result
            </th>
            {header("seed", "Seed")}
            <th
              scope="col"
              className="px-4 py-3 text-right text-xs font-medium"
            >
              Length
            </th>
            {columns.map((c) => header(`metric:${c.label}`, c.label))}
            <th scope="col" aria-label="Star" className="w-10" />
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => {
            const metrics = resultMetrics(d.tool, d.metrics);
            const length =
              typeof d.metrics.length === "number"
                ? d.metrics.length
                : typeof d.metrics.sequence === "string"
                  ? d.metrics.sequence.replace(/[^A-Za-z]/g, "").length
                  : undefined;
            return (
              <tr
                key={d.id}
                onMouseEnter={() => onHover(d.id)}
                onMouseLeave={() => onHover(null)}
                className={cn(
                  "hover:bg-paper-fold/40",
                  (hoverId === d.id || selectedIds.has(d.id)) &&
                    "bg-paper-fold/60",
                )}
              >
                <td className="px-3 py-4">
                  <input
                    type="checkbox"
                    aria-label={`Select design ${d.seed}`}
                    checked={selectedIds.has(d.id)}
                    onChange={() => onToggleSelect(d.id)}
                  />
                </td>
                <td className="px-4 py-4">
                  <Link
                    href={`/app/designs/${d.id}`}
                    className="block text-sm font-medium text-ink hover:underline"
                  >
                    {toolLabel(d.tool)}{" "}
                    <span className="font-mono text-xs text-graphite-soft">
                      {d.id.slice(0, 8)}
                    </span>
                  </Link>
                  <ProvenanceBadge provenance={d.provenance} />
                </td>
                <td className="px-4 py-4 text-right font-mono text-xs tabular-nums">
                  {d.seed}
                </td>
                <td className="px-4 py-4 text-right font-mono text-xs whitespace-nowrap">
                  {length == null ? "—" : `${length} aa`}
                </td>
                {columns.map((column) => {
                  const metric = metrics.find((m) => m.label === column.label);
                  return (
                    <td
                      key={column.label}
                      title={metric?.description}
                      className="px-4 py-4 text-right font-mono text-sm tabular-nums whitespace-nowrap"
                    >
                      {metric ? formatResultMetric(metric) : "—"}
                    </td>
                  );
                })}
                <td className="px-3">
                  <StarButton
                    designId={d.id}
                    starred={starredSet.has(d.id)}
                    variant="icon"
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
export function DesignsEmptyState({
  hasFilters,
  onReset,
}: {
  hasFilters: boolean;
  onReset: () => void;
}) {
  return (
    <div className="px-6 py-16 text-center">
      <p className="font-display text-xl text-ink">
        {hasFilters ? "No results match these filters." : "No results yet."}
      </p>
      <p className="mt-2 text-sm text-graphite">
        {hasFilters
          ? "Clear the filters to see all results in this project."
          : "Completed jobs will appear here."}
      </p>
      {hasFilters && (
        <button
          onClick={onReset}
          className="mt-5 rounded-lg border border-lattice px-4 py-2 text-sm"
        >
          Reset filters
        </button>
      )}
    </div>
  );
}
