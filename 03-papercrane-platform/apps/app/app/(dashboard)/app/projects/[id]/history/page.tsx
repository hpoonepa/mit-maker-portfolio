import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Clock } from "lucide-react";
import { createServerTrpc } from "@/lib/trpc/server";
import { VersionHistory } from "@/components/projects/VersionHistory";
import { ForkButton } from "@/components/projects/ForkButton";

/**
 * Project version history page: server-rendered shell.
 *
 * Loads the live project + its first target (so the diff has a "right side"
 * to compare against), then hands off to the client `<VersionHistory>` for
 * the interactive sidebar/diff. The server component is intentionally thin:
 * we don't pre-fetch the version list here because it's the bulk of what
 * scrolls and we'd rather stream it after auth resolves.
 */
export default async function ProjectHistoryPage({
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
  } | null = null;
  let currentHotspots: unknown = null;
  let loadError: string | null = null;

  try {
    const [p, targetsRes] = await Promise.all([
      trpc.projects.get.query({ id }),
      trpc.targets.list.query({ limit: 5 }).catch(() => ({ items: [] })),
    ]);
    project = {
      id: p.id,
      name: p.name,
      description: (p.description as string | null) ?? null,
    };
    const t = targetsRes.items.find(
      (row) => (row as { projectId?: string }).projectId === id,
    ) as { hotspots?: unknown } | undefined;
    currentHotspots = t?.hotspots ?? null;
  } catch (err) {
    if (err && typeof err === "object" && "data" in err) {
      const code = (err as { data?: { code?: string } }).data?.code;
      if (code === "NOT_FOUND") notFound();
    }
    loadError = err instanceof Error ? err.message : "Failed to load project.";
  }

  if (!project && !loadError) notFound();

  // Build the "current state" snapshot the client uses as the diff anchor.
  const currentState = project
    ? {
        name: project.name,
        description: project.description,
        hotspots: currentHotspots,
        // We don't read default params here because the source of truth for
        // them lives on the job submission form. The client component falls
        // back to `{}` when comparing, which is correct for projects whose
        // history predates the defaults feature.
        defaultParams: {} as Record<string, unknown>,
      }
    : null;

  return (
    <div className="space-y-10">
      <div>
        <Link
          href={`/app/projects/${id}`}
          className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back to project
        </Link>

        <div className="mt-5 flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="font-sans text-[12px] text-graphite-soft">
              <Clock className="mr-1.5 inline h-3 w-3" />
              Version history
            </p>
            <h1 className="font-display text-display-md text-ink break-words">
              {project?.name ?? "Project history"}
            </h1>
            <p className="mt-2 max-w-2xl font-sans text-[15px] text-graphite">
              Every saved snapshot of this project: name, description,
              hotspots, and default parameters. Revert to roll the live
              project back, or fork to spin up a new project pinned to this
              point in time.
            </p>
          </div>

          {project && (
            <ForkButton
              projectId={project.id}
              projectName={project.name}
              variant="primary"
            />
          )}
        </div>
      </div>

      {loadError && (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-5 py-4 font-sans text-[13px] text-crane-deep"
        >
          Couldn&apos;t load project: {loadError}
        </div>
      )}

      {project && currentState && (
        <VersionHistory projectId={project.id} currentState={currentState} />
      )}
    </div>
  );
}
