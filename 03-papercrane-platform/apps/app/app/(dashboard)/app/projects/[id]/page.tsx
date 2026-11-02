import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ExternalLink,
  Play,
  Settings as SettingsIcon,
  Target as TargetIcon,
} from "lucide-react";
import { createServerTrpc } from "@/lib/trpc/server";
import { ProjectDeletePaletteAction } from "@/components/projects/ProjectDeletePaletteAction";
import { ProjectShareToggle } from "@/components/projects/ProjectShareToggle";

/**
 * Project detail view: server-rendered.
 *
 * Loads the project, its target (if any), and recent jobs. The hotspot
 * picker lives at `/projects/[id]/target` (outside the (dashboard) group
 * because it owns its own full-bleed layout for the Mol* viewer).
 */
export default async function ProjectDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  const trpc = await createServerTrpc();

  let project: {
    id: string;
    name: string;
    description: string | null;
    isPublic: boolean;
    publicId: string | null;
  } | null = null;
  let target: { id?: string; pdbId: string | null; chain?: string | null } | null = null;
  let jobs: Array<{
    id: string;
    toolId: string;
    status: string;
    submittedAt: string;
    numDesigns: number;
    completedDesigns: number;
  }> = [];
  let loadError: string | null = null;

  try {
    const [p, jobsRes, targetsRes] = await Promise.all([
      trpc.projects.get.query({ id }),
      trpc.jobs.list.query({ limit: 25, projectId: id }),
      trpc.targets.list.query({ limit: 50, projectId: id }).catch(() => ({ items: [] })),
    ]);
    project = {
      id: p.id,
      name: p.name,
      description: (p.description as string | null) ?? null,
      isPublic: p.isPublic,
      publicId: p.publicId ?? null,
    };
    jobs = jobsRes.items.map((j) => ({
      id: j.id,
      toolId: j.toolId,
      status: j.status,
      submittedAt: toIso(j.submittedAt as unknown),
      numDesigns: j.numDesigns,
      completedDesigns: j.completedDesigns,
    }));
    // Only this project's targets can be preselected for a new run.
    const targetItems = targetsRes.items as Array<{
      id?: string;
      pdbId?: string | null;
      chain?: string | null;
      projectId?: string | null;
    }>;
    const t =
      targetItems.find((x) => x.projectId === id);
    if (t) {
      target = { id: t.id, pdbId: t.pdbId ?? null, chain: t.chain ?? null };
    }
  } catch (err) {
    if (err && typeof err === "object" && "data" in err) {
      const data = (err as { data?: { code?: string } }).data;
      if (data?.code === "NOT_FOUND") notFound();
    }
    loadError =
      err instanceof Error ? err.message : "Failed to load project.";
  }

  if (!project && !loadError) notFound();

  return (
    <div className="space-y-10">
      <div>
        <Link
          href="/app/projects"
          className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          All projects
        </Link>

        <div className="mt-5 flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="font-mono text-[11px] text-graphite-soft truncate">{id}</p>
            <h1 className="font-display text-display-md text-ink break-words">
              {project?.name ?? "Project"}
            </h1>
            {project?.description && (
              <p className="mt-2 max-w-2xl font-sans text-[15px] text-graphite">
                {project.description}
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 md:shrink-0">
            {target?.pdbId && (
              <Link
                href={`/projects/${id}/target?pdb=${target.pdbId}${target.chain ? `&chain=${target.chain}` : ""}`}
                className="inline-flex items-center gap-2 rounded-full border border-lattice-strong bg-paper px-4 py-2 min-h-[44px] sm:min-h-0 font-sans text-[13px] text-ink hover:bg-paper-fold transition-colors"
              >
                <TargetIcon className="w-3.5 h-3.5" />
                View target {target.pdbId}
                <ExternalLink className="w-3 h-3 text-graphite-soft" />
              </Link>
            )}
            <Link
              href={`/app/projects/${id}/settings`}
              data-testid="e2e-project-settings-link"
              className="inline-flex items-center gap-2 rounded-full border border-lattice bg-paper px-4 py-2 min-h-[44px] sm:min-h-0 font-sans text-[13px] text-graphite hover:border-lattice-strong hover:text-ink transition-colors"
            >
              <SettingsIcon className="w-3.5 h-3.5" />
              Settings
            </Link>
          </div>
        </div>
      </div>

      {loadError && (
        <div className="rounded-lg border border-crane/40 bg-crane-glow px-5 py-4 font-sans text-[13px] text-crane-deep">
          Couldn&apos;t fully load project: {loadError}
        </div>
      )}

      {project && (
        <ProjectShareToggle
          projectId={project.id}
          isPublic={project.isPublic}
          publicId={project.publicId}
        />
      )}

      <section>
        <h2 className="font-display text-[22px] text-ink flex items-center gap-2">
          <Play className="w-4 h-4" />
          Submit a job
        </h2>
        <p className="mt-1 font-sans text-[14px] text-graphite">
          Choose a tool and set up its input. Results will be saved here.
        </p>
        <div className="mt-5">
          <Link
            href={`/app/jobs/new?projectId=${id}${target?.id ? `&target=${target.id}` : ""}`}
            data-testid="e2e-project-new-job"
            className="btn-primary inline-flex items-center gap-2"
          >
            <Play className="w-3.5 h-3.5" />
            New job
          </Link>
        </div>
      </section>

      <section>
        <div className="flex items-end justify-between">
          <h2 className="font-display text-[22px] text-ink">Recent jobs</h2>
          <Link
            href={`/app/jobs?project=${id}`}
            className="font-sans text-[13px] text-graphite hover:text-ink transition-colors"
          >
            All jobs →
          </Link>
        </div>

        {jobs.length === 0 ? (
          <div
            data-testid="e2e-project-jobs-empty"
            className="mt-5 px-6 py-10 text-center font-sans text-[14px] text-graphite"
          >
            No jobs yet. Submit one above to get started.
          </div>
        ) : (
          <ul data-testid="e2e-project-jobs-list" className="mt-5 space-y-2">
            {jobs.map((job) => (
              <li key={job.id} data-testid={`e2e-project-job-${job.id}`}>
                <Link
                  href={`/app/jobs/${job.id}`}
                  className="flex flex-col gap-2 px-4 py-3 sm:px-5 sm:grid sm:grid-cols-[1fr_auto_auto_auto] sm:items-center sm:gap-4 transition-colors hover:border-lattice-strong min-h-[44px]"
                >
                  <span className="font-sans text-[14px] text-ink truncate">
                    {job.toolId}
                  </span>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 sm:contents">
                    <span className="font-mono text-[12px] text-graphite-soft tabular-nums">
                      {job.completedDesigns}/{job.numDesigns}
                    </span>
                    <span className="font-sans text-[12px] text-graphite">
                      {job.status}
                    </span>
                    <span className="font-mono text-[11px] text-graphite-soft">
                      {formatDate(job.submittedAt)}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {project && (
        <ProjectDeletePaletteAction
          projectId={project.id}
          projectName={project.name}
        />
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function toIso(v: unknown): string {
  if (v instanceof Date) return v.toISOString();
  if (typeof v === "string") return v;
  if (typeof v === "number") return new Date(v).toISOString();
  return String(v);
}
