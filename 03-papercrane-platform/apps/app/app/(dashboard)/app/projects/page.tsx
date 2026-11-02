"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Folder, ArrowUpRight } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { EmptyState } from "@/components/empty/EmptyState";
import { ProjectCardMenu } from "@/components/projects/ProjectCardMenu";
import { FilterBar } from "@/components/filters/FilterBar";
import {
  DateRangePicker,
  resolveDateRange,
} from "@/components/filters/DateRangePicker";
import { codecs, useFilters, type DateRange } from "@/lib/hooks/useFilters";

interface ProjectsFilterState extends Record<string, unknown> {
  search: string;
  active: boolean;
  created: DateRange;
}

const PROJECTS_SCHEMA = {
  search: codecs.string("q"),
  active: codecs.bool("active"),
  created: codecs.dateRange("created"),
} as const;

interface ProjectRow {
  id: string;
  name: string;
  description: string | null;
  updatedAt: string;
  createdAt: string;
  hasRunningJobs: boolean;
  slug?: string;
}

/**
 * Projects list: client-rendered so URL-synced filters can drive
 * search, date range, and "active" (has running jobs) toggle.
 */
export default function ProjectsPage() {
  const projectsQuery = trpc.projects.list.useQuery({ limit: 50 });
  const jobsQuery = trpc.jobs.list.useQuery({}, { refetchInterval: 30_000 });

  const { filters, setFilter, applyAll, reset, isDefault } =
    useFilters<ProjectsFilterState>(PROJECTS_SCHEMA);
  const [panelOpen, setPanelOpen] = useState(false);

  const activeProjectIds = useMemo(() => {
    const set = new Set<string>();
    const items = jobsQuery.data?.items ?? [];
    for (const j of items) {
      if (
        j.status === "running" ||
        j.status === "queued" ||
        j.status === "preparing"
      ) {
        const pid = (j as { projectId?: string }).projectId;
        if (pid) set.add(pid);
      }
    }
    return set;
  }, [jobsQuery.data]);

  const projects: ProjectRow[] = useMemo(() => {
    return (projectsQuery.data?.items ?? []).map((p) => ({
      id: p.id,
      name: p.name,
      description: (p as { description?: string | null }).description ?? null,
      updatedAt: toIso((p as { updatedAt?: unknown }).updatedAt),
      createdAt: toIso(
        (p as { createdAt?: unknown }).createdAt ??
          (p as { updatedAt?: unknown }).updatedAt,
      ),
      hasRunningJobs: activeProjectIds.has(p.id),
      slug: (p as { slug?: string }).slug,
    }));
  }, [projectsQuery.data, activeProjectIds]);

  const filtered = useMemo(() => {
    const search = filters.search.trim().toLowerCase();
    const dateBounds = resolveDateRange(filters.created);
    return projects.filter((p) => {
      if (filters.active && !p.hasRunningJobs) return false;
      if (search) {
        const hay = `${p.name} ${p.slug ?? ""}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      if (dateBounds.from || dateBounds.to) {
        const t = new Date(p.createdAt).getTime();
        if (dateBounds.from && t < dateBounds.from.getTime()) return false;
        if (dateBounds.to && t > dateBounds.to.getTime()) return false;
      }
      return true;
    });
  }, [projects, filters]);

  const loadError = projectsQuery.error
    ? friendlyError(projectsQuery.error)
    : null;

  const activeCount =
    (filters.active ? 1 : 0) + (filters.created.preset !== "all" ? 1 : 0);

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-center justify-between gap-6">
        <div>
          <h1 className="font-sans font-normal text-display-md text-ink">
            Projects
          </h1>
        </div>
        <Link href="/app/projects/new" className="btn-primary shrink-0">
          <Plus className="w-4 h-4" />
          New project
        </Link>
      </header>

      <FilterBar<ProjectsFilterState>
        search={filters.search}
        onSearchChange={(v) => setFilter("search", v)}
        searchPlaceholder="Search projects"
        panelOpen={panelOpen}
        onTogglePanel={() => setPanelOpen((o) => !o)}
        activeCount={activeCount}
        resultsLabel={
          projectsQuery.isLoading
            ? "loading…"
            : filters.search || activeCount ? `${filtered.length} of ${projects.length} projects` : `${projects.length} projects`
        }
        savedViews={{
          pageKey: "projects",
          current: filters,
          onApply: applyAll,
          canSave: !isDefault,
        }}
        onReset={reset}
      >
        <div className="grid gap-5 md:grid-cols-2">
          <label className="inline-flex cursor-pointer items-center gap-3 rounded-xl border border-lattice bg-paper px-4 py-3">
            <input
              type="checkbox"
              checked={filters.active}
              onChange={(e) => setFilter("active", e.target.checked)}
              className="h-4 w-4 rounded border-lattice-strong text-ink focus:ring-ink"
            />
            <div>
              <div className="font-sans text-[13px] text-ink">Active only</div>
              <div className="font-sans text-[12px] text-graphite-soft">
                Has at least one queued or running job
              </div>
            </div>
          </label>
          <DateRangePicker
            label="Created"
            value={filters.created}
            onChange={(v) => setFilter("created", v)}
          />
        </div>
      </FilterBar>

      {loadError && (
        <div
          role="alert"
          className="rounded-2xl border border-crane/40 bg-crane-glow px-5 py-4 font-sans text-[13px] text-crane-deep"
        >
          Couldn&apos;t load projects: {loadError}
        </div>
      )}

      {projectsQuery.isLoading ? (
        <p role="status" className="py-12 text-sm text-graphite">Loading projects…</p>
      ) : projects.length === 0 && !loadError ? (
        <EmptyState
          icon={<Folder className="w-5 h-5" />}
          title="No projects yet"
          description="Create a project to organize your runs and results."
          primaryCta={{ label: "Create project", href: "/app/projects/new" }}
          testId="e2e-projects-empty"
        />
      ) : filtered.length === 0 && projects.length > 0 ? (
        <div className="py-12 text-center">
          <p className="font-sans text-[14px] text-graphite">
            No projects match these filters.
          </p>
        </div>
      ) : (
        <ul className="project-list grid gap-x-14 sm:grid-cols-2">
          {filtered.map((project) => (
            <li key={project.id} className="group relative min-w-0 py-7">
              <Link href={`/app/projects/${project.id}`} className="block pr-12">
                <div className="mb-4 flex items-center gap-3 text-crane">
                  <Folder className="h-5 w-5" strokeWidth={1.3} />
                  {project.hasRunningJobs && (
                    <span className="inline-flex items-center gap-2 text-[12px]">
                      <span className="h-1.5 w-1.5 rounded-full bg-crane" />
                      Running
                    </span>
                  )}
                </div>
                <h2 className="flex items-start gap-3 text-[23px] leading-tight tracking-[-0.03em] text-ink transition-colors group-hover:text-crane">
                  <span className="break-words">{project.name}</span>
                  <ArrowUpRight className="mt-1 h-4 w-4 shrink-0 text-graphite opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100" />
                </h2>
                {project.description && (
                  <p className="mt-2 line-clamp-2 max-w-sm text-[14px] leading-relaxed text-graphite">
                    {project.description}
                  </p>
                )}
                <p className="mt-4 text-[12px] text-graphite-soft">
                  Updated {relativeTime(project.updatedAt)}
                </p>
              </Link>
              <ProjectCardMenu projectId={project.id} projectName={project.name} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function toIso(v: unknown): string {
  if (v instanceof Date) return v.toISOString();
  if (typeof v === "string") return v;
  if (typeof v === "number") return new Date(v).toISOString();
  return new Date().toISOString();
}

function friendlyError(err: unknown): string {
  const raw = err instanceof Error ? err.message : "Failed to load projects.";
  if (/Unexpected token '?<'?/.test(raw)) {
    return "Backend unreachable. Try again or contact support.";
  }
  return raw;
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const delta = Math.max(0, now - then);
  const mins = Math.floor(delta / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
