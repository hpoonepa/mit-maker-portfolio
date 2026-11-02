"use client";

import { useMemo, useState } from "react";
import { trpc } from "@/lib/trpc/client";
import { DesignScatterPlot } from "@/components/designs/DesignScatterPlot";
import { BatchSelectBar } from "@/components/designs/BatchSelectBar";
import {
  DesignsEmptyState,
  DesignsTable,
  sortDesignRows,
  metricColumns,
  type SortColumn,
  type SortKey,
} from "@/components/designs/DesignsTable";
import { resultMetrics } from "@/lib/results/metrics";
import { DesignsFilterPanel } from "@/components/designs/DesignsFilterPanel";
import { FilterBar } from "@/components/filters/FilterBar";
import { codecs, useFilters } from "@/lib/hooks/useFilters";

interface DesignRow {
  id: string;
  seed: number;
  rank?: number | null;
  tool?: string | null;
  jobId?: string | null;
  /** 'real' | 'synthetic' | 'stub': passthrough field on designs.listByProject. */
  provenance?: string | null;
  metrics: Record<string, number | string | undefined>;
  createdAt?: string;
}

const IPTM_BOUNDS = { min: 0, max: 1 };
const PAE_BOUNDS = { min: 0, max: 30 };
const PDOCKQ_BOUNDS = { min: 0, max: 1 };
const LENGTH_BOUNDS = { min: 0, max: 10000 };

interface DesignsFilterState extends Record<string, unknown> {
  search: string;
  tools: string[];
  iptm: { min: number; max: number };
  pae: { min: number; max: number };
  pdockq: { min: number; max: number };
  length: { min: number; max: number };
  project: string;
  job: string;
  starredOnly: string;
}

const DESIGNS_SCHEMA = {
  search: codecs.string("q"),
  tools: codecs.list("tool"),
  iptm: codecs.range("iptm_min", "iptm_max", IPTM_BOUNDS),
  pae: codecs.range("pae_min", "pae_max", PAE_BOUNDS),
  pdockq: codecs.range("pdockq_min", "pdockq_max", PDOCKQ_BOUNDS),
  length: codecs.range("len_min", "len_max", LENGTH_BOUNDS),
  project: codecs.string("project"),
  job: codecs.string("job"),
  starredOnly: codecs.string("starred"),
} as const;

/**
 * Designs gallery: top-level browse view across all projects in the org.
 * URL-synced filters drive sequence search, metric thresholds, and
 * project/job scoping.
 */
export default function DesignsListPage() {
  const projectsQuery = trpc.projects.list.useQuery({ limit: 50 });
  const projects = (projectsQuery.data?.items ?? []).map((p) => ({
    id: p.id,
    name: p.name,
  }));

  const { filters, setFilter, applyAll, reset, isDefault } =
    useFilters<DesignsFilterState>(DESIGNS_SCHEMA);

  const [sortBy, setSortBy] = useState<SortKey>("created:desc");
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSortColumn(col: SortColumn) {
    const asc = sortBy === `${col}:asc`;
    const desc = sortBy === `${col}:desc`;
    const metric = metricColumns(designs).find(
      (m) => `metric:${m.label}` === col,
    );
    setSortBy(
      `${col}:${asc ? "desc" : desc ? "asc" : metric?.direction === "low" || col === "seed" ? "asc" : "desc"}`,
    );
  }

  // Resolve effective project: explicit filter, else first available.
  const activeProjectId = filters.project || projects[0]?.id || "";

  const designsQuery = trpc.designs.listByProject.useQuery(
    { projectId: activeProjectId, limit: 500 },
    { enabled: !!activeProjectId },
  );
  const designs = useMemo(
    () => (designsQuery.data?.items as DesignRow[] | undefined) ?? [],
    [designsQuery.data?.items],
  );

  // Stars are scoped to the signed-in organization.
  const starredQuery = trpc.annotations.starredIds.useQuery();
  const starredSet = useMemo(
    () => new Set(starredQuery.data?.ids ?? []),
    [starredQuery.data],
  );

  const tools = useMemo(() => {
    const set = new Set<string>();
    designs.forEach((d) => {
      if (d.tool) set.add(d.tool);
    });
    return Array.from(set).sort();
  }, [designs]);

  const jobsForProject = useMemo(() => {
    const map = new Map<string, number>();
    designs.forEach((d) => {
      if (d.jobId) map.set(d.jobId, (map.get(d.jobId) ?? 0) + 1);
    });
    return Array.from(map.entries()).map(([id, count]) => ({ id, count }));
  }, [designs]);

  const visible = useMemo(() => {
    const search = filters.search.trim().toUpperCase();
    const filtered = designs.filter((d) => {
      const m = d.metrics as Record<string, number | string | undefined>;
      const values = resultMetrics(d.tool, m);
      const ipTM = values.find((x) => x.label === "ipTM")?.value;
      const pAE = values.find((x) => x.label === "PAE")?.value;
      const pDockQ = values.find((x) => x.label === "pDockQ")?.value;
      const len = typeof m.length === "number" ? m.length : undefined;

      if (
        filters.tools.length > 0 &&
        !(d.tool && filters.tools.includes(d.tool))
      )
        return false;
      if (
        ipTM != null &&
        (filters.iptm.min !== IPTM_BOUNDS.min ||
          filters.iptm.max !== IPTM_BOUNDS.max)
      ) {
        if (ipTM < filters.iptm.min || ipTM > filters.iptm.max) return false;
      }
      if (
        pAE != null &&
        (filters.pae.min !== PAE_BOUNDS.min ||
          filters.pae.max !== PAE_BOUNDS.max)
      ) {
        if (pAE < filters.pae.min || pAE > filters.pae.max) return false;
      }
      if (
        pDockQ != null &&
        (filters.pdockq.min !== PDOCKQ_BOUNDS.min ||
          filters.pdockq.max !== PDOCKQ_BOUNDS.max)
      ) {
        if (pDockQ < filters.pdockq.min || pDockQ > filters.pdockq.max)
          return false;
      }
      if (
        len != null &&
        (filters.length.min !== LENGTH_BOUNDS.min ||
          filters.length.max !== LENGTH_BOUNDS.max)
      ) {
        if (
          filters.length.min !== LENGTH_BOUNDS.min &&
          len < filters.length.min
        )
          return false;
        if (
          filters.length.max !== LENGTH_BOUNDS.max &&
          len > filters.length.max
        )
          return false;
      }
      if (filters.job && d.jobId !== filters.job) return false;
      if (filters.starredOnly === "1" && !starredSet.has(d.id)) return false;
      if (search) {
        const seq =
          typeof m.sequence === "string" ? m.sequence.toUpperCase() : "";
        if (!seq.includes(search)) return false;
      }
      return true;
    });

    return sortDesignRows(filtered, sortBy);
  }, [designs, filters, sortBy, starredSet]);

  const scatterData = useMemo(
    () =>
      visible
        .map((d) => {
          const m = d.metrics as Record<string, number | undefined>;
          const measurements = resultMetrics(d.tool, m);
          const ipTM = measurements.find((metric) => metric.label === "ipTM")?.value;
          const pAE = measurements.find((metric) => metric.label === "PAE")?.value;
          if (ipTM == null || pAE == null) return null;
          return {
            id: d.id,
            ipTM,
            pAE,
            tool: d.tool ?? undefined,
          };
        })
        .filter((x): x is NonNullable<typeof x> => x !== null),
    [visible],
  );

  const activeCount =
    (filters.tools.length > 0 ? 1 : 0) +
    (filters.iptm.min !== IPTM_BOUNDS.min ||
    filters.iptm.max !== IPTM_BOUNDS.max
      ? 1
      : 0) +
    (filters.pae.min !== PAE_BOUNDS.min || filters.pae.max !== PAE_BOUNDS.max
      ? 1
      : 0) +
    (filters.pdockq.min !== PDOCKQ_BOUNDS.min ||
    filters.pdockq.max !== PDOCKQ_BOUNDS.max
      ? 1
      : 0) +
    (filters.length.min !== LENGTH_BOUNDS.min ||
    filters.length.max !== LENGTH_BOUNDS.max
      ? 1
      : 0) +
    (filters.project ? 1 : 0) +
    (filters.job ? 1 : 0) +
    (filters.starredOnly === "1" ? 1 : 0);

  return (
    <div className="space-y-8">
      <header>
        <h1 className="font-display text-display-md text-ink">Designs</h1>
      </header>

      {projects.length > 0 && (
        <label className="flex items-center gap-3 text-sm text-graphite">
          Project
          <select
            aria-label="Results project"
            value={activeProjectId}
            onChange={(e) => {
              setFilter("project", e.target.value);
              setFilter("job", "");
            }}
            className="min-w-0 max-w-full rounded-lg border-0 bg-paper-fold px-3 py-2 text-ink"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <FilterBar<DesignsFilterState>
        search={filters.search}
        onSearchChange={(v) => setFilter("search", v)}
        searchPlaceholder="Search sequence substring (e.g. RKE)…"
        panelOpen={panelOpen}
        onTogglePanel={() => setPanelOpen((o) => !o)}
        activeCount={activeCount}
        resultsLabel={
          designsQuery.isLoading
            ? "loading…"
            : `${visible.length} of ${designs.length} results${designs.length === 500 ? " (latest 500)" : ""}`
        }
        savedViews={{
          pageKey: "designs",
          current: filters,
          onApply: applyAll,
          canSave: !isDefault,
        }}
        onReset={reset}
      >
        <DesignsFilterPanel
          filters={filters}
          bounds={{
            iptm: IPTM_BOUNDS,
            pae: PAE_BOUNDS,
            pdockq: PDOCKQ_BOUNDS,
            length: LENGTH_BOUNDS,
          }}
          tools={tools}
          projects={projects}
          jobsForProject={jobsForProject}
          availableMetrics={metricColumns(
            designs.filter(
              (d) =>
                !filters.tools.length ||
                (d.tool && filters.tools.includes(d.tool)),
            ),
          ).map((m) => m.label)}
          setFilter={setFilter}
        />
      </FilterBar>

      {projects.length === 0 && !projectsQuery.isLoading && (
        <div className="px-6 py-12 text-center">
          <p className="font-sans text-[14px] text-graphite">
            No projects yet. Submit a job from a project to see designs here.
          </p>
        </div>
      )}

      {designsQuery.isError && (
        <div
          role="alert"
          className="rounded-lg border border-crane/30 bg-crane-glow px-6 py-10 text-center font-sans text-[14px] text-crane-deep"
        >
          Failed to load designs:{" "}
          {designsQuery.error?.message ?? "unknown error"}
        </div>
      )}

      {!designsQuery.isError && activeProjectId && (
        <div className="space-y-6">
          {scatterData.length > 1 && (
            <details className="rounded-lg border border-lattice p-4">
              <summary className="cursor-pointer text-sm text-graphite">
                Plot interface confidence against predicted aligned error
              </summary>
              <div className="mt-4 max-w-xl">
                <DesignScatterPlot
                  data={scatterData}
                  highlightId={hoverId}
                  onHover={setHoverId}
                  onClick={(id) => {
                    window.location.href = `/app/designs/${id}`;
                  }}
                />
              </div>
            </details>
          )}
          <div className="flex items-center gap-3 text-sm text-graphite">
            <label htmlFor="design-sort">Sort by</label>
            <select
              id="design-sort"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="rounded-lg border border-lattice bg-paper px-3 py-2"
            >
              <option value="created:desc">Newest first</option>
              <option value="created:asc">Oldest first</option>
              <option value="seed:asc">Seed: ascending</option>
              <option value="seed:desc">Seed: descending</option>
              {metricColumns(designs).flatMap((m) => [
                <option key={`${m.label}:asc`} value={`metric:${m.label}:asc`}>
                  {m.label}: ascending
                </option>,
                <option
                  key={`${m.label}:desc`}
                  value={`metric:${m.label}:desc`}
                >
                  {m.label}: descending
                </option>,
              ])}
            </select>
          </div>
          <div>
            {designsQuery.isLoading ? (
              <div
                aria-busy="true"
                role="status"
                className="divide-y divide-lattice"
              >
                {Array.from({ length: 8 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-[44px] animate-pulse bg-paper-fold/40"
                  />
                ))}
              </div>
            ) : visible.length === 0 ? (
              <DesignsEmptyState
                hasFilters={activeCount > 0 || !!filters.search}
                onReset={reset}
              />
            ) : (
              <DesignsTable
                rows={visible}
                hoverId={hoverId}
                onHover={setHoverId}
                selectedIds={selectedIds}
                onToggleSelect={toggleSelect}
                onSelectAll={(ids) => setSelectedIds(new Set(ids))}
                onClearAll={() => setSelectedIds(new Set())}
                starredSet={starredSet}
                sortBy={sortBy}
                onToggleSort={toggleSortColumn}
              />
            )}
          </div>
        </div>
      )}

      <BatchSelectBar
        selected={designs
          .filter((d) => selectedIds.has(d.id))
          .map((d) => {
            const m = d.metrics as Record<string, number | string | undefined>;
            return {
              id: d.id,
              seed: d.seed,
              sequence: typeof m.sequence === "string" ? m.sequence : null,
              length: typeof m.length === "number" ? m.length : null,
              tool: d.tool ?? null,
              metrics: numericMetrics(m),
            };
          })}
        onClear={() => setSelectedIds(new Set())}
      />
    </div>
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
