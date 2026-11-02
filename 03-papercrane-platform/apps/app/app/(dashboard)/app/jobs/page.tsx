"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowUpDown, Briefcase, Plus } from "lucide-react";
import type { JobSummary } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/empty/EmptyState";
import { PageSkeleton } from "@/components/loading/PageSkeleton";
import { friendlyTrpcError } from "@/lib/errors/friendly";
import { FilterBar } from "@/components/filters/FilterBar";
import { MultiSelectChips } from "@/components/filters/MultiSelectChips";
import { RangeSlider } from "@/components/filters/RangeSlider";
import {
  DateRangePicker,
  resolveDateRange,
} from "@/components/filters/DateRangePicker";
import { codecs, useFilters, type DateRange } from "@/lib/hooks/useFilters";
import {
  STATUS_OPTIONS,
  StatusPill,
  StatusPillRow,
  formatRelative,
  formatRuntime,
  splitToolVersion,
} from "@/components/jobs/JobsListBits";

type SortKey = "submittedAt" | "status" | "toolId" | "completedDesigns";
type SortDir = "asc" | "desc";

const TOOL_OPTIONS = [
  "rfdiffusion",
  "boltzgen",
  "bindcraft",
  "proteinmpnn",
  "ligandmpnn",
  "solublempnn",
  "boltz1",
  "boltz2",
  "alphafold3",
  "chai1",
  "chroma",
  "esm2",
];

const COST_BOUNDS = { min: 0, max: 500 };

interface JobsFilterState extends Record<string, unknown> {
  search: string;
  status: string[];
  tools: string[];
  project: string;
  date: DateRange;
  cost: { min: number; max: number };
}

const JOBS_SCHEMA = {
  search: codecs.string("q"),
  status: codecs.list("status"),
  tools: codecs.list("tool"),
  project: codecs.string("project"),
  date: codecs.dateRange("date"),
  cost: codecs.range("cost_min", "cost_max", COST_BOUNDS),
} as const;

/**
 * Jobs across all projects. Polls every 10s so newly-submitted jobs show
 * up while the user is here. Filters live in the URL so links are shareable.
 */
export default function JobsPage() {
  const { filters, setFilter, applyAll, reset, isDefault } =
    useFilters<JobsFilterState>(JOBS_SCHEMA);
  const jobsQuery = trpc.jobs.list.useQuery(
    { ...(filters.project ? { projectId: filters.project } : {}) },
    { refetchInterval: 10_000, refetchOnWindowFocus: true },
  );
  const projectsQuery = trpc.projects.list.useQuery({ limit: 50 });

  const jobItems = jobsQuery.data?.items;
  const jobs = useMemo(() => (jobItems ?? []) as JobSummary[], [jobItems]);
  const projects = projectsQuery.data?.items ?? [];
  const isLoading = jobsQuery.isLoading;
  const friendlyError = jobsQuery.error
    ? friendlyTrpcError(jobsQuery.error)
    : null;

  const [sortKey, setSortKey] = useState<SortKey>("submittedAt");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [panelOpen, setPanelOpen] = useState(false);

  const filtered = useMemo(() => {
    const dateBounds = resolveDateRange(filters.date);
    const search = filters.search.trim().toLowerCase();
    return jobs.filter((j) => {
      if (filters.status.length > 0 && !filters.status.includes(j.status))
        return false;
      if (filters.tools.length > 0 && !filters.tools.includes(j.toolId))
        return false;
      const projectId = (j as JobSummary & { projectId?: string }).projectId;
      if (filters.project && projectId !== filters.project) return false;
      if (search) {
        const name = (j as JobSummary & { name?: string }).name ?? "";
        const hay = `${j.toolId} ${j.id} ${name}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      if (dateBounds.from || dateBounds.to) {
        const d = new Date(j.submittedAt).getTime();
        if (dateBounds.from && d < dateBounds.from.getTime()) return false;
        if (dateBounds.to && d > dateBounds.to.getTime()) return false;
      }
      const cost = (j as JobSummary & { cost?: number }).cost;
      if (typeof cost === "number") {
        if (cost < filters.cost.min || cost > filters.cost.max) return false;
      }
      return true;
    });
  }, [jobs, filters]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [filtered, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const activeCount =
    (filters.status.length > 0 ? 1 : 0) +
    (filters.tools.length > 0 ? 1 : 0) +
    (filters.project ? 1 : 0) +
    (filters.date.preset !== "all" ? 1 : 0) +
    (filters.cost.min !== COST_BOUNDS.min ||
    filters.cost.max !== COST_BOUNDS.max
      ? 1
      : 0);

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-sans font-medium text-display-md text-ink">Jobs</h1>
        <Link href="/app/jobs/new" className="btn-primary"><Plus className="h-4 w-4" />New job</Link>
      </header>

      <FilterBar<JobsFilterState>
        search={filters.search}
        onSearchChange={(v) => setFilter("search", v)}
        searchPlaceholder="Search by name or job id…"
        panelOpen={panelOpen}
        onTogglePanel={() => setPanelOpen((o) => !o)}
        activeCount={activeCount}
        resultsLabel={
          isLoading ? "loading…" : `${sorted.length} of ${jobs.length} jobs`
        }
        savedViews={{
          pageKey: "jobs",
          current: filters,
          onApply: applyAll,
          canSave: !isDefault,
        }}
        onReset={reset}
      >
        <div className="grid gap-5 md:grid-cols-2">
          <MultiSelectChips
            label="Status"
            options={STATUS_OPTIONS.map((s) => ({
              id: s.id,
              label: s.label,
              count: jobs.filter((j) => j.status === s.id).length,
            }))}
            value={filters.status}
            onChange={(v) => setFilter("status", v)}
          />
          <MultiSelectChips
            label="Tool"
            options={TOOL_OPTIONS.map((id) => ({ id, label: id }))}
            value={filters.tools}
            onChange={(v) => setFilter("tools", v)}
          />
          <div className="space-y-2">
            <div className="font-sans tabular-nums text-[12px] text-graphite-soft">
              Project
            </div>
            <select
              value={filters.project}
              onChange={(e) => setFilter("project", e.target.value)}
              className="w-full rounded-xl border border-lattice bg-paper px-3 py-1.5 font-sans text-[13px] text-ink focus:outline-none focus:border-ink"
            >
              <option value="">All projects</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <DateRangePicker
            label="Submitted"
            value={filters.date}
            onChange={(v) => setFilter("date", v)}
          />
          <RangeSlider
            label="Cost ($)"
            min={COST_BOUNDS.min}
            max={COST_BOUNDS.max}
            step={5}
            value={filters.cost}
            onChange={(v) => setFilter("cost", v)}
            format={(n) => `$${n}`}
            className="md:col-span-2"
          />
        </div>
      </FilterBar>

      {/* Quick status pills: toggleable, mirrors filters.status */}
      <StatusPillRow
        jobs={jobs}
        active={filters.status}
        onToggle={(id) => {
          const next = filters.status.includes(id)
            ? filters.status.filter((s) => s !== id)
            : [...filters.status, id];
          setFilter("status", next);
        }}
      />

      {friendlyError && (
        <div
          role="alert"
          className="rounded-2xl border border-crane/40 bg-crane-glow px-5 py-4 font-sans text-[13px] text-crane-deep"
        >
          Couldn&apos;t load jobs: {friendlyError.message}
        </div>
      )}

      {isLoading ? (
        <PageSkeleton variant="list" count={5} />
      ) : sorted.length === 0 ? (
        <EmptyState
          icon={<Briefcase className="w-5 h-5" />}
          title={
            isDefault
              ? "No jobs yet"
              : "No jobs match these filters"
          }
          description={
            isDefault
              ? "Choose a tool and submit your first run."
              : "Try clearing some filters or adjusting ranges."
          }
          primaryCta={
            isDefault
              ? { label: "Browse projects", href: "/app/projects" }
              : undefined
          }
          testId="e2e-jobs-empty"
        />
      ) : (
        <div
          data-testid="e2e-jobs-queue"
          className="bg-paper overflow-hidden"
        >
          {/* Mobile: stacked cards. Each row becomes a tap-target card. */}
          <ul className="divide-y divide-lattice/70 sm:hidden">
            {sorted.map((job) => {
              const { tool, version } = splitToolVersion(job.toolId);
              const runtime = formatRuntime(job.startedAt, job.finishedAt);
              return (
                <li key={job.id}>
                  <Link
                    href={`/app/jobs/${job.id}`}
                    data-testid={`e2e-jobs-row-${job.id}`}
                    className="flex items-center justify-between gap-3 px-4 py-4 min-h-[64px]"
                  >
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate font-sans tabular-nums text-[13px] text-ink">
                          {tool}
                          {version && (
                            <span className="text-graphite-soft">
                              @{version}
                            </span>
                          )}
                        </span>
                        <StatusPill status={job.status} />
                      </div>
                      <div className="flex items-center gap-3 font-sans tabular-nums text-[12px] text-graphite-soft tabular-nums">
                        <span className="text-graphite">
                          {job.completedDesigns}
                          <span className="text-graphite-soft">
                            /{job.numDesigns}
                          </span>
                        </span>
                        {runtime && (
                          <>
                            <span aria-hidden>·</span>
                            <span>{runtime}</span>
                          </>
                        )}
                        <span aria-hidden>·</span>
                        <span className="uppercase">
                          {formatRelative(job.submittedAt)}
                        </span>
                      </div>
                    </div>
                    <span className="shrink-0 font-sans text-[13px] text-ink">
                      →
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>

          {/* sm+: full sortable table with horizontal scroll if needed. */}
          <div className="hidden sm:block overflow-x-auto max-h-[70vh]">
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10 bg-paper/95 supports-[backdrop-filter]:bg-paper/80">
                <tr className="text-left">
                  <SortHeader
                    label="Tool"
                    active={sortKey === "toolId"}
                    dir={sortDir}
                    onClick={() => toggleSort("toolId")}
                  />
                  <SortHeader
                    label="Status"
                    active={sortKey === "status"}
                    dir={sortDir}
                    onClick={() => toggleSort("status")}
                  />
                  <SortHeader
                    label="Designs"
                    active={sortKey === "completedDesigns"}
                    dir={sortDir}
                    onClick={() => toggleSort("completedDesigns")}
                  />
                  <th className="px-5 py-3 font-sans text-[12px] text-graphite-soft">
                    Runtime
                  </th>
                  <th className="px-5 py-3 font-sans text-[12px] text-graphite-soft">
                    GPU·h
                  </th>
                  <th className="px-5 py-3 font-sans text-[12px] text-graphite-soft">
                    Project
                  </th>
                  <SortHeader
                    label="Submitted"
                    active={sortKey === "submittedAt"}
                    dir={sortDir}
                    onClick={() => toggleSort("submittedAt")}
                  />
                  <th />
                </tr>
              </thead>
              <tbody>
                {sorted.map((job) => {
                  const ext = job as JobSummary & {
                    projectId?: string;
                    projectName?: string;
                    gpuHours?: number;
                  };
                  const project = ext.projectId
                    ? projects.find((p) => p.id === ext.projectId)
                    : undefined;
                  const { tool, version } = splitToolVersion(job.toolId);
                  const runtime = formatRuntime(job.startedAt, job.finishedAt);
                  return (
                    <tr
                      key={job.id}
                      data-testid={`e2e-jobs-row-${job.id}`}

                    >
                      <td className="px-5 py-3 font-sans tabular-nums text-[13px] text-ink">
                        {tool}
                        {version && (
                          <span className="text-graphite-soft">@{version}</span>
                        )}
                      </td>
                      <td className="px-5 py-3">
                        <StatusPill status={job.status} />
                      </td>
                      <td className="px-5 py-3 font-sans tabular-nums text-[13px] text-ink tabular-nums">
                        {job.completedDesigns}
                        <span className="text-graphite-soft">
                          /{job.numDesigns}
                        </span>
                      </td>
                      <td className="px-5 py-3 font-sans tabular-nums text-[13px] text-graphite tabular-nums">
                        {runtime ?? (
                          <span className="text-graphite-soft">N/A</span>
                        )}
                      </td>
                      <td className="px-5 py-3 font-sans tabular-nums text-[13px] text-graphite tabular-nums">
                        {typeof ext.gpuHours === "number" ? (
                          ext.gpuHours.toFixed(2)
                        ) : (
                          <span className="text-graphite-soft">N/A</span>
                        )}
                      </td>
                      <td className="px-5 py-3 font-sans text-[13px]">
                        {ext.projectId ? (
                          <Link
                            href={`/app/projects/${ext.projectId}`}
                            onClick={(e) => e.stopPropagation()}
                            className="text-graphite hover:text-ink underline-offset-2 hover:underline truncate"
                          >
                            {project?.name ?? ext.projectName ?? "Project"}
                          </Link>
                        ) : (
                          <span className="text-graphite-soft">N/A</span>
                        )}
                      </td>
                      <td className="px-5 py-3 font-sans tabular-nums text-[12px] text-graphite-soft tabular-nums">
                        {formatRelative(job.submittedAt)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <Link
                          href={`/app/jobs/${job.id}`}
                          className="font-sans text-[13px] text-ink hover:text-crane-deep transition-colors"
                        >
                          Open →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function SortHeader({
  label,
  active,
  dir,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}) {
  return (
    <th className="px-5 py-3 font-sans text-[12px] text-graphite-soft">
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "inline-flex items-center gap-1 hover:text-ink transition-colors",
          active && "text-ink",
        )}
      >
        {label}
        <ArrowUpDown
          className={cn(
            "w-3 h-3 transition-transform",
            active && dir === "asc" && "rotate-180",
          )}
        />
      </button>
    </th>
  );
}
