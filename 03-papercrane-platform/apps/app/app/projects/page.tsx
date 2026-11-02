import Link from "next/link";
import { createServerTrpc } from "@/lib/trpc/server";

export const dynamic = "force-dynamic";

type ProjectRow = {
  id: string;
  name: string;
  slug?: string;
  description?: string | null;
  createdAt: unknown;
  updatedAt: unknown;
};

type TargetRow = {
  id: string;
  projectId?: string | null;
  createdAt?: unknown;
  updatedAt?: unknown;
};

type JobRow = {
  id: string;
  projectId?: string | null;
  createdAt?: unknown;
  updatedAt?: unknown;
};

/**
 * /projects: org-scoped index page.
 *
 * Server component using `createServerTrpc()` so the initial render is
 * fully populated (no client-side flash). Targets and jobs are fetched in
 * parallel and grouped by `projectId` to derive per-project counts and
 * last-activity timestamps without adding new procedures.
 */
export default async function ProjectsIndexPage() {
  const trpc = await createServerTrpc();

  const [projectsRes, targetsRes, jobsRes] = await Promise.all([
    trpc.projects.list.query({ limit: 100 }),
    trpc.targets.list.query({ limit: 200 }).catch(() => ({ items: [] })),
    trpc.jobs.list.query({ limit: 200 }).catch(() => ({ items: [] })),
  ]);

  const projects = (projectsRes.items as ProjectRow[]) ?? [];
  const targets = (targetsRes.items as TargetRow[]) ?? [];
  const jobs = (jobsRes.items as JobRow[]) ?? [];

  const targetsByProject = new Map<string, number>();
  for (const t of targets) {
    if (!t.projectId) continue;
    targetsByProject.set(
      t.projectId,
      (targetsByProject.get(t.projectId) ?? 0) + 1,
    );
  }

  const lastJobByProject = new Map<string, number>();
  for (const j of jobs) {
    if (!j.projectId) continue;
    const t = toMillis(j.updatedAt ?? j.createdAt);
    if (!t) continue;
    const prev = lastJobByProject.get(j.projectId);
    if (!prev || t > prev) lastJobByProject.set(j.projectId, t);
  }

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-16">
        <header className="flex flex-col items-start gap-4 sm:flex-row sm:items-end sm:justify-between sm:gap-6">
          <div>
            <p className="font-sans text-[11px] uppercase tracking-[0.18em] text-graphite-soft">
              Workspace
            </p>
            <h1 className="mt-2 font-display text-display-md text-ink tracking-[-0.01em]">
              Projects
            </h1>
            <p className="mt-2 max-w-lg font-sans text-[15px] text-graphite">
              Group related targets, hotspots, and jobs.
            </p>
          </div>
          <Link
            href="/app/projects/new"
            className="inline-flex shrink-0 items-center gap-2 rounded-md bg-crane px-5 py-2.5 font-sans text-[13px] font-medium text-paper transition-colors hover:bg-crane-deep"
          >
            New project
          </Link>
        </header>

        {projects.length === 0 ? (
          <EmptyProjects />
        ) : (
          <section className="mt-12 overflow-x-auto rounded-lg border border-lattice bg-paper-fold/40">
            <div className="grid min-w-[480px] grid-cols-[1fr_auto_auto_auto] items-center gap-4 border-b border-lattice px-4 py-3 font-sans text-[11px] uppercase tracking-[0.16em] text-graphite-soft sm:gap-6 sm:px-6">
              <div>Project</div>
              <div className="text-right">Targets</div>
              <div className="text-right">Last activity</div>
              <div className="sr-only">Open</div>
            </div>
            <ul>
              {projects.map((p) => {
                const tCount = targetsByProject.get(p.id) ?? 0;
                const lastJob = lastJobByProject.get(p.id);
                const updated = toMillis(p.updatedAt) ?? toMillis(p.createdAt);
                const lastActivity = Math.max(lastJob ?? 0, updated ?? 0);
                return (
                  <li
                    key={p.id}
                    className="border-b border-lattice last:border-b-0"
                  >
                    <Link
                      href={`/projects/${p.id}`}
                      className="grid min-w-[480px] grid-cols-[1fr_auto_auto_auto] items-center gap-4 px-4 py-4 transition-colors hover:bg-paper-fold sm:gap-6 sm:px-6 sm:py-5"
                    >
                      <div className="min-w-0">
                        <div className="truncate font-display text-[18px] font-semibold text-ink tracking-[-0.005em]">
                          {p.name}
                        </div>
                        {p.description ? (
                          <div className="mt-1 line-clamp-1 font-sans text-[13px] text-graphite">
                            {p.description}
                          </div>
                        ) : p.slug ? (
                          <div className="mt-1 font-mono text-[11px] text-graphite-soft">
                            {p.slug}
                          </div>
                        ) : null}
                      </div>
                      <div className="text-right font-mono text-[13px] tabular-nums text-ink">
                        {tCount}
                      </div>
                      <div className="text-right font-sans text-[12px] text-graphite-soft">
                        {lastActivity ? relativeTime(lastActivity) : "N/A"}
                      </div>
                      <div
                        aria-hidden
                        className="font-sans text-[13px] text-graphite-soft transition-colors group-hover:text-ink"
                      >
                        Open →
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

function EmptyProjects() {
  return (
    <section className="mt-12 rounded-lg border border-dashed border-lattice-strong bg-paper-fold/30 px-8 py-16 text-center">
      <h2 className="font-display text-[24px] text-ink tracking-[-0.01em]">
        No projects yet.
      </h2>
      <p className="mt-2 font-sans text-[14px] text-graphite">
        Start with a target.
      </p>
      <div className="mt-6">
        <Link
          href="/app/projects/new"
          className="inline-flex items-center gap-2 rounded-full bg-crane px-5 py-2.5 font-sans text-[13px] font-medium text-paper transition-colors hover:bg-crane-deep"
        >
          Create project
        </Link>
      </div>
    </section>
  );
}

function toMillis(v: unknown): number | null {
  if (!v) return null;
  if (v instanceof Date) return v.getTime();
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const t = Date.parse(v);
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

function relativeTime(t: number): string {
  const delta = Math.max(0, Date.now() - t);
  const mins = Math.floor(delta / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(days / 365);
  return `${years}y ago`;
}
