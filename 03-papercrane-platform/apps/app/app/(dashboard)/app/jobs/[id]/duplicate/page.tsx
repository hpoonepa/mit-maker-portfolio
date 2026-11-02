import { redirect } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { createServerTrpc } from "@/lib/trpc/server";

/**
 * Job duplicate landing page: `/app/jobs/[id]/duplicate`.
 *
 * Server component. Fetches the source job via `jobs.get`, then 307-redirects
 * to the existing submit form (`/app/jobs/new`) with query params that the
 * form already knows how to hydrate from (`cloneOf=<id>&tool=<toolId>`: see
 * `JobActions.tsx`). This makes the duplicate flow a single, bookmarkable
 * URL even though no extra tRPC procs were added.
 *
 * Project context (when available) is forwarded as `projectId` so the
 * submit form's project selector pre-fills. If `jobs.get` fails or the
 * source job is missing, we render an inline error with a link back to
 * the job detail page rather than 404'ing: operators almost always
 * arrived from the detail page and want a clear way back.
 */

interface DuplicatePageProps {
  params: Promise<{ id: string }>;
}

interface SourceJob {
  id: string;
  toolId: string;
  params?:
    | (Record<string, unknown> & {
        projectId?: string | null;
        request?: { projectId?: string | null } | null;
      })
    | null;
}

function buildRedirectHref(job: SourceJob): string {
  const tool = encodeURIComponent(job.toolId);
  const cloneOf = encodeURIComponent(job.id);
  const projectId =
    (job.params?.projectId as string | null | undefined) ??
    (job.params?.request?.projectId as string | null | undefined) ??
    null;

  // Spec: also surface as `from=<id>` so a future `/app/jobs/new` reading
  // either key continues to work without a server change.
  const qs = new URLSearchParams({
    tool,
    cloneOf,
    from: cloneOf,
  });
  if (projectId) qs.set("projectId", projectId);

  return `/app/jobs/new?${qs.toString()}`;
}

export default async function DuplicateJobPage({ params }: DuplicatePageProps) {
  const { id } = await params;

  let job: SourceJob | null = null;
  let errorMessage: string | null = null;

  try {
    const trpc = await createServerTrpc();
    // `jobs.get` is the same proc the detail page polls.
    const fetched = (await trpc.jobs.get.query({ id })) as SourceJob | null;
    job = fetched ?? null;
  } catch (err) {
    errorMessage =
      err instanceof Error ? err.message : "Could not load source job.";
  }

  if (job) {
    redirect(buildRedirectHref(job));
  }

  // Fallback UI: only renders when the fetch failed.
  return (
    <div className="space-y-6">
      <Link
        href={`/app/jobs/${id}`}
        className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to job
      </Link>

      <div className="rounded-lg border border-crane/30 bg-crane-glow px-5 py-4 space-y-2">
        <h1 className="font-display text-display-sm text-ink">
          Couldn&rsquo;t duplicate this job
        </h1>
        <p className="font-sans text-[13px] text-crane-deep">
          {errorMessage ??
            "The source job could not be found. It may have been purged."}
        </p>
        <p className="font-mono text-[11px] text-graphite-soft">{id}</p>
      </div>
    </div>
  );
}
