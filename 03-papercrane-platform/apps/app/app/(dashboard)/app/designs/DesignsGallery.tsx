"use client";

import { useCallback, useMemo, useState } from "react";
import { ArrowUpDown, Check } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { DesignCard } from "@/components/designs/DesignCard";
import {
  sortDesignRows,
  metricColumns,
  type SortKey,
} from "@/components/designs/DesignsTable";
import { resultMetrics } from "@/lib/results/metrics";
import {
  DEFAULT_FILTERS,
  DesignFilters,
  type DesignFilterState,
} from "@/components/designs/DesignFilters";
import { BatchSelectBar } from "@/components/designs/BatchSelectBar";
import type { ExportableDesign } from "@/components/designs/DesignExport";

interface DesignRow {
  id: string;
  seed: number;
  rank?: number | null;
  tool?: string | null;
  /** 'real' | 'synthetic' | 'stub': passthrough field on designs.listByProject. */
  provenance?: string | null;
  metrics: Record<string, number | string | undefined>;
  createdAt?: string;
}

export interface DesignsGalleryProps {
  projects: Array<{ id: string; name: string }>;
  initialProjectId: string;
}

export function DesignsGallery({
  projects,
  initialProjectId,
}: DesignsGalleryProps) {
  const [projectId, setProjectId] = useState<string>(initialProjectId);
  const [filters, setFilters] = useState<DesignFilterState>(DEFAULT_FILTERS);
  const [sortBy, setSortBy] = useState<SortKey>("created:desc");
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  const query = trpc.designs.listByProject.useQuery({
    projectId,
    limit: 500,
  });

  const designItems = query.data?.items;
  const designs = useMemo(
    () => (designItems as DesignRow[] | undefined) ?? [],
    [designItems],
  );

  const tools = useMemo(() => {
    const set = new Set<string>();
    designs.forEach((d) => {
      if (d.tool) set.add(d.tool);
    });
    return Array.from(set).sort();
  }, [designs]);

  const visible = useMemo(() => {
    const filtered = designs.filter((d) => {
      const m = d.metrics as Record<string, number | undefined>;
      const values = resultMetrics(d.tool, m);
      const ipTM = values.find((x) => x.label === "ipTM")?.value;
      const pAE = values.find((x) => x.label === "PAE")?.value;
      const pDockQ = values.find((x) => x.label === "pDockQ")?.value;
      if (ipTM != null && (filters.ipTM.min !== 0 || filters.ipTM.max !== 1)) {
        if (ipTM < filters.ipTM.min || ipTM > filters.ipTM.max) return false;
      }
      if (pAE != null && (filters.pAE.min !== 0 || filters.pAE.max !== 30)) {
        if (pAE < filters.pAE.min || pAE > filters.pAE.max) return false;
      }
      if (
        pDockQ != null &&
        (filters.pDockQ.min !== 0 || filters.pDockQ.max !== 1)
      ) {
        if (pDockQ < filters.pDockQ.min || pDockQ > filters.pDockQ.max)
          return false;
      }
      if (filters.tool && d.tool !== filters.tool) return false;
      return true;
    });

    return sortDesignRows(filtered, sortBy);
  }, [designs, filters, sortBy]);

  // Resolve selected ids into ExportableDesign payloads. We pull from the
  // full `designs` list (not `visible`) so a user that filters AFTER
  // selecting doesn't lose their selections.
  const selectedDesigns = useMemo<ExportableDesign[]>(() => {
    if (selectedIds.size === 0) return [];
    const out: ExportableDesign[] = [];
    for (const d of designs) {
      if (!selectedIds.has(d.id)) continue;
      const m = d.metrics as Record<string, number | string | undefined>;
      out.push({
        id: d.id,
        seed: d.seed,
        sequence: typeof m.sequence === "string" ? m.sequence : null,
        length: typeof m.length === "number" ? m.length : null,
        tool: d.tool ?? null,
        metrics: numericMetrics(m),
        // structureUrl isn't in listByProject: batch CIF zip will tell the
        // user "no structures available" until trpc is extended. FASTA/CSV/
        // JSON exports work today.
      });
    }
    return out;
  }, [designs, selectedIds]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        {projects.length > 1 && (
          <ProjectSwitcher
            projects={projects}
            value={projectId}
            onChange={setProjectId}
          />
        )}
        <SortControl
          value={sortBy}
          onChange={setSortBy}
          columns={metricColumns(designs)}
        />
        <span className="ml-auto font-mono text-[11px] text-graphite-soft tabular-nums">
          {query.isLoading
            ? "loading…"
            : `${visible.length} of ${designs.length} results${designs.length === 500 ? " (latest 500)" : ""}`}
        </span>
      </div>

      <DesignFilters
        value={filters}
        onChange={setFilters}
        availableTools={tools}
        availableMetrics={metricColumns(designs).map((m) => m.label)}
        matchCount={visible.length}
        totalCount={designs.length}
      />

      {query.isError && (
        <div
          role="alert"
          className="rounded-lg border border-crane/30 bg-crane-glow px-6 py-10 text-center font-sans text-[14px] text-crane-deep"
        >
          Failed to load designs: {query.error?.message ?? "unknown error"}
        </div>
      )}

      {!query.isError && (
        <div>
          <div>
            {query.isLoading ? (
              <ul
                aria-busy="true"
                className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3"
              >
                {Array.from({ length: 6 }).map((_, i) => (
                  <li
                    key={i}
                    className="h-[260px] animate-pulse"
                  />
                ))}
              </ul>
            ) : visible.length === 0 ? (
              <div className="px-6 py-12 text-center">
                <p className="font-sans text-[14px] text-graphite">
                  No designs match these filters.
                </p>
              </div>
            ) : (
              <ul
                className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3"
                role="list"
                aria-label="Designs"
              >
                {visible.map((d) => {
                  const m = d.metrics as Record<
                    string,
                    number | string | undefined
                  >;
                  const isSelected = selectedIds.has(d.id);
                  return (
                    <li key={d.id} className="group/select relative">
                      <SelectCheckbox
                        checked={isSelected}
                        onToggle={() => toggleSelect(d.id)}
                      />
                      <DesignCard
                        design={{
                          id: d.id,
                          seed: d.seed,
                          rank: d.rank ?? null,
                          tool: d.tool ?? null,
                          sequence:
                            typeof m.sequence === "string" ? m.sequence : null,
                          length:
                            typeof m.length === "number" ? m.length : null,
                          provenance: d.provenance ?? null,
                          metrics: numericMetrics(m),
                        }}
                        isHighlighted={hoverId === d.id || isSelected}
                        onMouseEnter={() => setHoverId(d.id)}
                        onMouseLeave={() => setHoverId(null)}
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}

      <BatchSelectBar
        selected={selectedDesigns}
        onClear={clearSelection}
        archiveName={
          projects
            .find((p) => p.id === projectId)
            ?.name?.replace(/\s+/g, "-") ?? "designs"
        }
      />
    </div>
  );
}

function SelectCheckbox({
  checked,
  onToggle,
}: {
  checked: boolean;
  onToggle: () => void;
}) {
  // Reveal on hover or when already checked. Clicking is its own button so
  // the surrounding card link doesn't navigate.
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={checked ? "Deselect design" : "Select design"}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
      className={cn(
        "absolute left-2 top-2 z-10 flex h-6 w-6 items-center justify-center rounded-md border transition-all",
        checked
          ? "border-ink bg-ink text-paper opacity-100"
          : "border-lattice-strong bg-paper/90 text-graphite opacity-0 group-hover/select:opacity-100 focus:opacity-100",
      )}
    >
      {checked && <Check className="h-3.5 w-3.5" />}
    </button>
  );
}

function ProjectSwitcher({
  projects,
  value,
  onChange,
}: {
  projects: Array<{ id: string; name: string }>;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="inline-flex items-center gap-1.5 rounded-xl border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite">
      <span className="sr-only">Project</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-transparent font-sans text-[12px] text-ink focus:outline-none"
      >
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function SortControl({
  value,
  onChange,
  columns,
}: {
  columns: { label: string }[];
  value: SortKey;
  onChange: (v: SortKey) => void;
}) {
  return (
    <label
      className={cn(
        "inline-flex items-center gap-1.5 rounded-xl border border-lattice bg-paper px-3 py-1.5",
        "font-sans text-[12px] text-graphite",
      )}
    >
      <ArrowUpDown className="h-3 w-3" />
      <span className="sr-only">Sort by</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as SortKey)}
        className="bg-transparent text-ink focus:outline-none"
      >
        <option value="created:desc">Newest first</option>
        <option value="created:asc">Oldest first</option>
        <option value="seed:asc">Seed: ascending</option>
        <option value="seed:desc">Seed: descending</option>
        {columns.flatMap((m) => [
          <option key={`${m.label}:asc`} value={`metric:${m.label}:asc`}>
            {m.label}: ascending
          </option>,
          <option key={`${m.label}:desc`} value={`metric:${m.label}:desc`}>
            {m.label}: descending
          </option>,
        ])}
      </select>
    </label>
  );
}

function numericMetrics(
  m: Record<string, number | string | undefined>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(m)) {
    if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
  }
  return out;
}
