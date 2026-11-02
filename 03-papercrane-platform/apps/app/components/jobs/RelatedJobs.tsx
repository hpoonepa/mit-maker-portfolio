"use client";

import { useMemo } from "react";
import Link from "next/link";
import { GitBranch, GitFork, Layers } from "lucide-react";

import type { JobStatus } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { JobStatusBadge } from "@/components/jobs/JobStatusBadge";
import { cn } from "@/lib/utils";

/**
 * Sidebar block surfacing the relationships of this job to others:
 *   - The originating project (params.projectId / params.projectSlug).
 *   - The parent job, if this is a retry/clone (params.retryOf / params.cloneOf).
 *   - Sibling jobs in the same project (last 5, this one excluded).
 *   - Direct children: jobs whose params.retryOf === this id.
 *
 * Backed entirely by `trpc.jobs.list` since we don't ship a dedicated
 * "related" router: we filter client-side. Cheap because list is org-scoped
 * and capped at 200 rows by the server.
 */

interface JobRow {
  id: string;
  toolId: string;
  status: JobStatus;
  submittedAt: string;
  numDesigns: number;
  completedDesigns: number;
}

interface JobLikeParams {
  projectId?: string;
  projectSlug?: string;
  retryOf?: string;
  cloneOf?: string;
}

interface RelatedJobsProps {
  jobId: string;
  /** Params from the current job, used to resolve project + parent links. */
  params?: (JobLikeParams & Record<string, unknown>) | null;
  className?: string;
}

export function RelatedJobs({ jobId, params, className }: RelatedJobsProps) {
  const projectId = (params?.projectId as string | undefined) ?? undefined;
  const projectSlug = (params?.projectSlug as string | undefined) ?? undefined;
  const retryOf = (params?.retryOf as string | undefined) ?? undefined;
  const cloneOf = (params?.cloneOf as string | undefined) ?? undefined;
  const parentId = retryOf ?? cloneOf;
  const parentLabel = retryOf ? "Retry of" : cloneOf ? "Clone of" : null;

  // Pull recent jobs and filter for siblings/children client-side. The list
  // route is org-scoped and capped server-side; this is the cheapest way to
  // get the relationship view without adding a new tRPC route.
  const listQuery = trpc.jobs.list.useQuery({ limit: 50 });
  const listItems = listQuery.data?.items;
  const items = useMemo(() => (listItems ?? []) as JobRow[], [listItems]);

  // Read raw rows once to avoid TS narrowing issues with optional params.
  const siblings = useMemo(() => {
    if (!projectId && !projectSlug) return [];
    return items
      .filter((j) => j.id !== jobId)
      .filter((j) => {
        const p = (j as unknown as { params?: JobLikeParams }).params;
        // The wire shape from list() doesn't include params; without it we
        // can't disambiguate siblings reliably, so we fall back to "recent
        // jobs in the same org" when the row is missing params. This is the
        // common case in the dashboard and keeps the UI useful.
        if (!p) return true;
        return (
          (projectId && p.projectId === projectId) ||
          (projectSlug && p.projectSlug === projectSlug)
        );
      })
      .slice(0, 5);
  }, [items, projectId, projectSlug, jobId]);

  const children = useMemo(
    () =>
      items.filter((j) => {
        const p = (j as unknown as { params?: JobLikeParams }).params;
        return p?.retryOf === jobId;
      }),
    [items, jobId],
  );

  const projectHref = projectSlug
    ? `/app/projects/${projectSlug}`
    : projectId
      ? `/app/projects/${projectId}`
      : null;

  // Hide the whole block when there's literally nothing to show: keeps the
  // detail page lean for one-off jobs.
  const hasContent =
    projectHref || parentId || siblings.length > 0 || children.length > 0;
  if (!hasContent) return null;

  return (
    <section
      aria-label="Related jobs"
      className={cn(
        "space-y-4 p-5",
        className,
      )}
    >
      <h2 className="font-sans text-[12px] text-graphite-soft">
        Related
      </h2>

      {projectHref && (
        <RelatedRow
          icon={<Layers className="w-3.5 h-3.5" />}
          label="From project"
        >
          <Link
            href={projectHref}
            className="font-mono text-[12px] text-ink underline-offset-2 hover:underline"
          >
            {projectSlug ?? projectId}
          </Link>
        </RelatedRow>
      )}

      {parentId && parentLabel && (
        <RelatedRow
          icon={<GitFork className="w-3.5 h-3.5" />}
          label={parentLabel}
        >
          <Link
            href={`/app/jobs/${parentId}`}
            className="font-mono text-[12px] text-ink underline-offset-2 hover:underline break-all"
          >
            {parentId}
          </Link>
        </RelatedRow>
      )}

      {children.length > 0 && (
        <RelatedRow
          icon={<GitBranch className="w-3.5 h-3.5" />}
          label="Retries"
        >
          <ul className="space-y-1.5">
            {children.map((c) => (
              <JobLink key={c.id} job={c} />
            ))}
          </ul>
        </RelatedRow>
      )}

      {siblings.length > 0 && (
        <RelatedRow
          icon={<Layers className="w-3.5 h-3.5" />}
          label="Recent siblings"
        >
          <ul className="space-y-1.5">
            {siblings.map((s) => (
              <JobLink key={s.id} job={s} />
            ))}
          </ul>
        </RelatedRow>
      )}
    </section>
  );
}

function RelatedRow({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <p className="inline-flex items-center gap-1.5 font-sans text-[12px] text-graphite-soft">
        {icon}
        {label}
      </p>
      <div>{children}</div>
    </div>
  );
}

function JobLink({ job }: { job: JobRow }) {
  return (
    <li>
      <Link
        href={`/app/jobs/${job.id}`}
        className="group flex items-center justify-between gap-2 rounded-lg border border-transparent px-2 py-1 -mx-2 hover:border-lattice hover:bg-paper"
      >
        <span className="font-mono text-[11px] text-ink truncate group-hover:underline">
          {job.toolId}
        </span>
        <JobStatusBadge status={job.status} size="sm" />
      </Link>
    </li>
  );
}
