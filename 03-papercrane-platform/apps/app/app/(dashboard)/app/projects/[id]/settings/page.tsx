import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { createServerTrpc } from "@/lib/trpc/server";
import { ProjectSettingsForm } from "@/components/projects/ProjectSettingsForm";
import { ProjectDangerZone } from "@/components/projects/ProjectDangerZone";

/**
 * Project settings: server-rendered shell wrapping the client-only
 * `ProjectSettingsForm` (rename / edit description) and `ProjectDangerZone`
 * (destructive delete). Loading the project on the server gives us a fast
 * first paint and lets `notFound()` handle 404s before we ship any client
 * JS.
 */
export default async function ProjectSettingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const trpc = await createServerTrpc();

  let project: {
    id: string;
    name: string;
    description: string;
  } | null = null;
  let loadError: string | null = null;

  try {
    const p = await trpc.projects.get.query({ id });
    project = {
      id: p.id,
      name: p.name,
      description: ((p.description as string | null) ?? "") as string,
    };
  } catch (err) {
    if (err && typeof err === "object" && "data" in err) {
      const data = (err as { data?: { code?: string } }).data;
      if (data?.code === "NOT_FOUND") notFound();
    }
    loadError = err instanceof Error ? err.message : "Failed to load project.";
  }

  if (!project && !loadError) notFound();

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

        <div className="mt-5">
          <h1 className="font-display text-display-md text-ink">
            {project?.name ?? "Project settings"}
          </h1>
          <p className="mt-2 max-w-lg font-sans text-[15px] text-graphite">
            Rename this project or update its description. Destructive actions
            live below in the danger zone.
          </p>
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

      {project && (
        <>
          <section>
            <h2 className="font-display text-[20px] text-ink">Details</h2>
            <p className="mt-1 font-sans text-[13px] text-graphite">
              Name and description are visible to everyone in your org.
            </p>
            <div className="mt-5">
              <ProjectSettingsForm
                projectId={project.id}
                initialName={project.name}
                initialDescription={project.description}
              />
            </div>
          </section>

          <ProjectDangerZone
            projectId={project.id}
            projectName={project.name}
          />
        </>
      )}
    </div>
  );
}
