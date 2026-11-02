import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Plus } from "lucide-react";
import { createServerTrpc } from "@/lib/trpc/server";

/**
 * Project home: server-rendered overview at `/projects/[projectId]`.
 *
 * Companion of the (dashboard) project page; lives outside the dashboard
 * group so the hotspot picker route at `/projects/[projectId]/target`
 * shares this layout's <Providers> wrapper without dragging the dashboard
 * chrome along.
 *
 * Information architecture:
 *   header : project name (Fraunces) + slug · created-on (mono)
 *   grid   : Targets (col-span-2)  +  Recent jobs (col-span-3)
 *          : Recent designs (col-span-5, full-width below)
 *
 * Each section caps at 5 items + "View all →". Crane red is reserved for
 * the primary CTA and status dots: every other accent is graphite/ink.
 */

type LoadedProject = {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
  description: string | null;
};

type LoadedTarget = {
  id: string;
  name: string;
  pdbId: string | null;
  chain: string | null;
};

type LoadedJob = {
  id: string;
  toolId: string;
  status: string;
  submittedAt: string;
  numDesigns: number;
  completedDesigns: number;
};

type LoadedDesign = {
  id: string;
  jobId?: string;
  tool?: string;
  length: number;
  rank: number | null;
  createdAt: string;
};

const SECTION_LIMIT = 5;

export default async function ProjectHomePage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const trpc = await createServerTrpc();

  let project: LoadedProject | null = null;
  let targets: LoadedTarget[] = [];
  let jobs: LoadedJob[] = [];
  let designs: LoadedDesign[] = [];

  try {
    const [p, jobsRes, targetsRes, designsRes] = await Promise.all([
      trpc.projects.get.query({ id: projectId }),
      trpc.jobs.list.query({ limit: 25 }).catch(() => ({ items: [] })),
      trpc.targets.list.query({ limit: 50 }).catch(() => ({ items: [] })),
      trpc.designs.listByProject
        .query({ projectId, limit: 25 })
        .catch(() => ({ items: [] })),
    ]);

    project = {
      id: p.id,
      name: p.name,
      slug: p.slug,
      createdAt: toIso(p.createdAt as unknown),
      description: (p.description as string | null) ?? null,
    };

    targets = (targetsRes.items as Array<Record<string, unknown>>)
      .filter((t) => (t.projectId as string | null | undefined) === projectId)
      .slice(0, SECTION_LIMIT)
      .map((t) => ({
        id: String(t.id ?? ""),
        name: String(t.name ?? "Untitled target"),
        pdbId: (t.pdbId as string | null | undefined) ?? null,
        chain: (t.chain as string | null | undefined) ?? null,
      }));

    jobs = jobsRes.items.slice(0, SECTION_LIMIT).map((j) => ({
      id: j.id,
      toolId: j.toolId,
      status: j.status,
      submittedAt: toIso(j.submittedAt as unknown),
      numDesigns: j.numDesigns,
      completedDesigns: j.completedDesigns,
    }));

    designs = designsRes.items.slice(0, SECTION_LIMIT).map((d) => ({
      id: d.id,
      jobId: (d as { jobId?: string }).jobId,
      tool: (d as { tool?: string }).tool,
      length: d.length ?? d.sequence?.length ?? 0,
      rank: (d as { rank?: number | null }).rank ?? null,
      createdAt: toIso(d.createdAt as unknown),
    }));
  } catch (err) {
    if (err && typeof err === "object" && "data" in err) {
      const data = (err as { data?: { code?: string } }).data;
      if (data?.code === "NOT_FOUND") notFound();
    }
    throw err;
  }

  if (!project) notFound();

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-8 sm:px-8 sm:py-12">
      <header className="border-b border-lattice pb-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between sm:gap-10">
          <div className="min-w-0">
            <h1 className="font-display text-[34px] leading-[1.05] tracking-[-0.01em] text-ink sm:text-[44px]">
              {project.name}
            </h1>
            <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[12px] uppercase tracking-[0.08em] text-graphite-soft">
              <span>{project.slug}</span>
              <span aria-hidden="true">·</span>
              <span>created {formatShortDate(project.createdAt)}</span>
            </p>
            {project.description && (
              <p className="mt-4 max-w-xl font-sans text-[14px] leading-[1.55] text-graphite">
                {project.description}
              </p>
            )}
          </div>

          <Link
            href={`/app/projects/${project.id}#submit-job`}
            data-testid="e2e-project-home-submit-cta"
            className="inline-flex shrink-0 items-center gap-2 self-start border border-crane-deep bg-crane-deep px-5 py-3 font-sans text-[13px] uppercase tracking-[0.08em] text-paper transition-colors hover:bg-ink hover:border-ink"
          >
            <Plus className="h-3.5 w-3.5" />
            Submit job
          </Link>
        </div>
      </header>

      <div className="mt-10 grid grid-cols-1 gap-x-10 gap-y-12 lg:grid-cols-5">
        <Section
          className="lg:col-span-2"
          title="Targets"
          allHref={`/projects/${project.id}/target`}
          allLabel="View all"
          empty={
            <EmptyState
              copy="No targets yet: upload one to begin"
              ctaHref={`/projects/${project.id}/target`}
              ctaLabel="Pick a target"
            />
          }
          items={targets}
          renderItem={(t) => (
            <Link
              key={t.id}
              href={`/projects/${project!.id}/target${t.pdbId ? `?pdb=${t.pdbId}${t.chain ? `&chain=${t.chain}` : ""}` : ""}`}
              className="group flex items-center justify-between gap-4 border-b border-lattice/70 py-3 transition-colors last:border-b-0 hover:border-lattice-strong"
            >
              <div className="min-w-0">
                <p className="truncate font-sans text-[14px] text-ink">
                  {t.name}
                </p>
                <p className="mt-0.5 font-mono text-[11px] uppercase tracking-[0.1em] text-graphite-soft">
                  {t.pdbId ?? "N/A"}
                  {t.chain ? ` · chain ${t.chain}` : ""}
                </p>
              </div>
              <ArrowRight className="h-3.5 w-3.5 shrink-0 text-graphite-soft transition-transform group-hover:translate-x-0.5 group-hover:text-ink" />
            </Link>
          )}
        />

        <Section
          className="lg:col-span-3"
          title="Recent jobs"
          allHref="/app/jobs"
          allLabel="View all"
          empty={
            <EmptyState
              copy="No jobs yet: submit one to see them here"
              ctaHref={`/app/projects/${project.id}#submit-job`}
              ctaLabel="Submit job"
            />
          }
          items={jobs}
          renderItem={(job) => (
            <Link
              key={job.id}
              href={`/app/jobs/${job.id}`}
              className="grid grid-cols-[auto_1fr_auto] items-center gap-3 border-b border-lattice/70 py-3 transition-colors last:border-b-0 hover:border-lattice-strong sm:grid-cols-[auto_1fr_auto_auto]"
            >
              <StatusDot status={job.status} />
              <span className="truncate font-sans text-[14px] text-ink">
                {job.toolId}
              </span>
              <span className="hidden font-mono text-[11px] tabular-nums text-graphite sm:inline">
                {job.completedDesigns}/{job.numDesigns}
              </span>
              <span className="font-mono text-[11px] text-graphite-soft tabular-nums">
                {formatShortDate(job.submittedAt)}
              </span>
            </Link>
          )}
        />

        <Section
          className="lg:col-span-5"
          title="Recent designs"
          allHref={`/app/designs?projectId=${project.id}`}
          allLabel="View all"
          empty={
            <EmptyState
              copy="No designs yet: submitted jobs will stream their results here"
              ctaHref={`/app/projects/${project.id}#submit-job`}
              ctaLabel="Submit job"
            />
          }
          items={designs}
          renderItem={(d) => (
            <Link
              key={d.id}
              href={d.jobId ? `/app/jobs/${d.jobId}` : `/app/designs`}
              className="grid grid-cols-[auto_1fr_auto] items-center gap-3 border-b border-lattice/70 py-3 transition-colors last:border-b-0 hover:border-lattice-strong sm:grid-cols-[auto_1fr_auto_auto] sm:gap-4"
            >
              <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-graphite-soft tabular-nums">
                {d.rank != null ? `#${String(d.rank).padStart(3, "0")}` : "N/A"}
              </span>
              <span className="min-w-0 truncate font-sans text-[14px] text-ink">
                {d.tool ?? "design"}
              </span>
              <span className="hidden font-mono text-[11px] tabular-nums text-graphite sm:inline">
                {d.length} aa
              </span>
              <span className="font-mono text-[11px] text-graphite-soft tabular-nums">
                {formatShortDate(d.createdAt)}
              </span>
            </Link>
          )}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Local presentational helpers                                        */
/* ------------------------------------------------------------------ */

function Section<T>({
  title,
  allHref,
  allLabel,
  items,
  renderItem,
  empty,
  className,
}: {
  title: string;
  allHref: string;
  allLabel: string;
  items: T[];
  renderItem: (item: T) => React.ReactNode;
  empty: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      <header className="border-t border-ink pt-3">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink">
            {title}
          </h2>
          <Link
            href={allHref}
            className="font-mono text-[11px] uppercase tracking-[0.1em] text-graphite-soft transition-colors hover:text-ink"
          >
            {allLabel} →
          </Link>
        </div>
      </header>
      <div className="mt-1">
        {items.length === 0 ? empty : <div>{items.map(renderItem)}</div>}
      </div>
    </section>
  );
}

function EmptyState({
  copy,
  ctaHref,
  ctaLabel,
}: {
  copy: string;
  ctaHref: string;
  ctaLabel: string;
}) {
  return (
    <div className="mt-3 border border-dashed border-lattice-strong bg-paper-fold/30 px-5 py-6 text-center">
      <p className="font-sans text-[13px] text-graphite">{copy}</p>
      <Link
        href={ctaHref}
        className="mt-3 inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-[0.1em] text-ink hover:text-crane-deep"
      >
        {ctaLabel} →
      </Link>
    </div>
  );
}

/** Status indicator: Crane red is reserved for active/failed states. */
function StatusDot({ status }: { status: string }) {
  const live = status === "running" || status === "preparing";
  const danger = status === "failed" || status === "cancelling";
  const ok = status === "succeeded";
  const cls = danger
    ? "bg-crane-deep"
    : live
      ? "bg-crane-deep animate-pulse"
      : ok
        ? "bg-ink"
        : "bg-graphite-soft";
  return (
    <span
      aria-hidden="true"
      title={status}
      className={`h-1.5 w-1.5 rounded-full ${cls}`}
    />
  );
}

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "N/A";
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function toIso(v: unknown): string {
  if (v instanceof Date) return v.toISOString();
  if (typeof v === "string") return v;
  if (typeof v === "number") return new Date(v).toISOString();
  return String(v);
}
