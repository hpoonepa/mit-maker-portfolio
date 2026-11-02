"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Clock, RotateCcw, GitBranch, Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { useToast } from "@/components/toasts/useToast";
import { VersionDiff } from "./VersionDiff";

/**
 * Version history sidebar for a project.
 *
 * Layout: a two-column shell: left rail lists every snapshot newest-first,
 * right pane shows the diff between the selected version and the live
 * project state (or the version immediately after it, if you've drilled in).
 *
 * Interactions:
 *   - Click a row → `selectedVersion` updates, diff renders.
 *   - "Revert to this version" → tRPC `revert`, then refresh the page so the
 *     project detail picks up the new live state. We don't optimistically
 *     mutate the project row here because the snapshot/project relationship
 *     is the caller's responsibility (see router comment on `revert`).
 *   - "Fork from here" → handled by `<ForkButton>`, which we render in the
 *     diff pane so the action is always tied to whichever version is open.
 */
export interface VersionHistoryProps {
  projectId: string;
  /** Live current state: used as the "right side" of the diff for the
   *  newest entry, and as a comparison anchor when nothing is selected. */
  currentState: {
    name: string;
    description: string | null;
    hotspots: unknown;
    defaultParams: Record<string, unknown>;
  };
}

interface VersionRow {
  id: string;
  version: number;
  authorId: string;
  description: string | null;
  createdAt: string | Date;
  snapshot: {
    name: string;
    description: string | null;
    hotspots: unknown;
    defaultParams: Record<string, unknown>;
    metadata?: Record<string, unknown>;
  };
}

export function VersionHistory({
  projectId,
  currentState,
}: VersionHistoryProps) {
  const router = useRouter();
  const utils = trpc.useUtils();
  const { toast } = useToast();
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);

  const { data, isLoading, error } = trpc.projects.versions.list.useQuery({
    projectId,
    limit: 100,
  });

  const revert = trpc.projects.revert.useMutation({
    onSuccess: (created) => {
      toast({
        title: "Reverted",
        description: `Project state restored. New snapshot v${created.version} written.`,
        variant: "success",
      });
      void utils.projects.versions.list.invalidate({ projectId });
      void utils.projects.get.invalidate({ id: projectId });
      router.refresh();
    },
    onError: (err) => {
      toast({
        title: "Revert failed",
        description: err.message ?? "Could not revert.",
        variant: "error",
      });
    },
  });

  const versions = (data?.items ?? []) as VersionRow[];
  // Snap to the latest version on first render.
  const activeVersion =
    selectedVersion ??
    versions.at(0)?.version ??
    null;
  const activeRow = versions.find((v) => v.version === activeVersion) ?? null;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
      {/* ── Left rail: chronological list ─────────────────────────────── */}
      <aside className="space-y-2">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-graphite" />
          <h2 className="font-display text-[18px] text-ink">History</h2>
        </div>

        {isLoading && (
          <div
            className="flex items-center gap-2 font-sans text-[13px] text-graphite-soft"
            role="status"
          >
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading versions…
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-lg border border-crane/40 bg-crane-glow px-3 py-2 font-sans text-[12px] text-crane-deep"
          >
            {error.message}
          </div>
        )}

        {!isLoading && !error && versions.length === 0 && (
          <div className="px-3 py-4 font-sans text-[12px] text-graphite">
            No snapshots yet. The first save will appear here.
          </div>
        )}

        <ul className="space-y-1.5">
          {versions.map((v) => {
            const isActive = v.version === activeVersion;
            return (
              <li key={v.id}>
                <button
                  type="button"
                  onClick={() => setSelectedVersion(v.version)}
                  className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
                    isActive
                      ? "border-lattice-strong bg-paper"
                      : "border-lattice bg-paper-fold/40 hover:border-lattice-strong"
                  }`}
                  data-testid={`e2e-version-row-${v.version}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[12px] text-ink tabular-nums">
                      v{v.version}
                    </span>
                    <span className="font-mono text-[10px] text-graphite-soft">
                      {formatDate(v.createdAt)}
                    </span>
                  </div>
                  {v.description && (
                    <p className="mt-1 line-clamp-2 font-sans text-[12px] text-graphite">
                      {v.description}
                    </p>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      {/* ── Right pane: diff + actions ────────────────────────────────── */}
      <main className="min-w-0">
        {activeRow ? (
          <div className="space-y-5">
            <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-sans text-[12px] text-graphite-soft">
                  Snapshot v{activeRow.version}
                </p>
                <h3 className="mt-1 font-display text-[20px] text-ink">
                  {activeRow.description ?? "No description"}
                </h3>
                <p className="mt-1 font-mono text-[11px] text-graphite-soft">
                  {formatDate(activeRow.createdAt)}
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={revert.isPending}
                  onClick={() =>
                    revert.mutate({
                      projectId,
                      version: activeRow.version,
                    })
                  }
                  className="inline-flex items-center gap-2 rounded-full border border-lattice-strong bg-paper px-4 py-2 min-h-[44px] sm:min-h-0 font-sans text-[13px] text-ink hover:bg-paper-fold transition-colors disabled:opacity-40"
                  data-testid="e2e-version-revert"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  {revert.isPending ? "Reverting…" : "Revert to this version"}
                </button>

                <a
                  href={`#fork-v${activeRow.version}`}
                  onClick={(e) => {
                    e.preventDefault();
                    document
                      .getElementById(`fork-${activeRow.version}`)
                      ?.scrollIntoView({ behavior: "smooth" });
                  }}
                  className="inline-flex items-center gap-2 rounded-full border border-lattice bg-paper-fold/40 px-4 py-2 min-h-[44px] sm:min-h-0 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
                >
                  <GitBranch className="h-3.5 w-3.5" />
                  Fork from here
                </a>
              </div>
            </header>

            <VersionDiff before={activeRow.snapshot} after={currentState} />
          </div>
        ) : (
          !isLoading && (
            <div className="px-6 py-12 text-center font-sans text-[14px] text-graphite">
              Select a version on the left to see what changed.
            </div>
          )
        )}
      </main>
    </div>
  );
}

function formatDate(v: string | Date): string {
  const d = v instanceof Date ? v : new Date(v);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default VersionHistory;
