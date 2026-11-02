"use client";

/**
 * Export Center: single page for batch FASTA/CIF/JSON/CSV downloads.
 *
 * Three sections:
 *   A. By project: pick a project, choose formats, hit "Download bundle".
 *   B. By job    : paste a job id, choose formats, download.
 *   C. Recent    : last 10 exports kept in client memory only. There is no
 *      backend `exports` table or proc yet, so this is local state. Logged
 *      as "feature TBD" so it's obvious from the console.
 *
 * The page deliberately uses the existing `/api/designs/[id]/export/[format]`
 * route handler (Wave-A A5). No new tRPC procs, no new deps.
 */

import { useEffect, useState } from "react";
import { trpc } from "@/lib/trpc/client";
import { ExportPanel } from "@/components/exports/ExportPanel";

interface RecentExport {
  at: string;
  scope: "project" | "job";
  targetId: string;
  count: number;
}

export default function ExportCenterPage() {
  const projectsQuery = trpc.projects.list.useQuery({ limit: 50 });
  const projects = projectsQuery.data?.items ?? [];

  const [projectId, setProjectId] = useState<string>("");
  const [jobIdInput, setJobIdInput] = useState<string>("");
  const [recent, setRecent] = useState<RecentExport[]>([]);

  useEffect(() => {
    // No persistence layer for exports yet: surface that to anyone poking
    // around the console rather than silently swallowing it.
    console.info("[exports] recent exports persistence: feature TBD");
  }, []);

  function logExport(scope: "project" | "job", targetId: string, count: number) {
    setRecent((prev) =>
      [{ at: new Date().toISOString(), scope, targetId, count }, ...prev].slice(0, 10),
    );
  }

  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-display text-display-md text-ink">Export center</h1>
        <p className="mt-2 max-w-2xl font-sans text-[15px] text-graphite">
          Pull every design from a project or job in the formats you need -
          FASTA for sequence work, CIF for structures, JSON for raw metrics,
          CSV for spreadsheet pipelines.
        </p>
      </header>

      {/* Section A: by project */}
      <section className="bg-paper p-6 space-y-4">
        <div>
          <h2 className="font-display text-[20px] text-ink">By project</h2>
          <p className="mt-1 font-sans text-[13px] text-graphite-soft">
            Bundles every design that landed in a project across all jobs.
          </p>
        </div>
        <label className="block">
          <span className="font-sans text-[12px] text-graphite-soft">
            Project
          </span>
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            disabled={projectsQuery.isLoading}
            className="mt-1 w-full max-w-md rounded-xl border border-lattice-strong bg-paper px-3 py-2 font-sans text-[14px] text-ink focus:outline-none focus:ring-2 focus:ring-crane/30"
          >
            <option value="">- select a project -</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <ExportPanel
          mode="project"
          targetId={projectId}
          label={projects.find((p) => p.id === projectId)?.name ?? "project"}
          onDone={(n) => logExport("project", projectId, n)}
        />
      </section>

      {/* Section B: by job */}
      <section className="bg-paper p-6 space-y-4">
        <div>
          <h2 className="font-display text-[20px] text-ink">By job</h2>
          <p className="mt-1 font-sans text-[13px] text-graphite-soft">
            Scoped to one batch. Paste a job id from the jobs page.
          </p>
        </div>
        <label className="block">
          <span className="font-sans text-[12px] text-graphite-soft">
            Job id
          </span>
          <input
            type="text"
            value={jobIdInput}
            onChange={(e) => setJobIdInput(e.target.value.trim())}
            placeholder="job_abc123…"
            className="mt-1 w-full max-w-md rounded-xl border border-lattice-strong bg-paper px-3 py-2 font-mono text-[13px] text-ink focus:outline-none focus:ring-2 focus:ring-crane/30"
          />
        </label>
        <ExportPanel
          mode="job"
          targetId={jobIdInput}
          label="job"
          onDone={(n) => logExport("job", jobIdInput, n)}
        />
      </section>

      {/* Section C: recent exports (client-only memory) */}
      <section className="bg-paper p-6 space-y-4">
        <div>
          <h2 className="font-display text-[20px] text-ink">Recent exports</h2>
          <p className="mt-1 font-sans text-[13px] text-graphite-soft">
            Local to this tab: server-side history is a future addition.
          </p>
        </div>
        {recent.length === 0 ? (
          <p className="font-sans text-[13px] text-graphite-soft">
            Nothing yet. Trigger an export above to see it here.
          </p>
        ) : (
          <ul className="divide-y divide-lattice">
            {recent.map((r, i) => (
              <li
                key={i}
                className="flex items-center justify-between py-3 font-sans text-[13px] text-ink"
              >
                <span className="font-mono text-[12px] text-graphite">
                  {r.scope}:{r.targetId.slice(0, 12)}…
                </span>
                <span className="text-graphite-soft">
                  {r.count} design{r.count === 1 ? "" : "s"}
                </span>
                <span className="text-graphite-soft text-[12px]">
                  {new Date(r.at).toLocaleTimeString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
