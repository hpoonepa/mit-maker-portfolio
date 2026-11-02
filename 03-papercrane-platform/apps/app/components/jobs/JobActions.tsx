"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Ban, RotateCcw, Copy as CopyIcon, Download, Loader2 } from "lucide-react";

import type { JobStatus } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { ExportPanel } from "@/components/exports/ExportPanel";

/**
 * Operator action bar for a job: Cancel / Retry / Clone.
 *
 *  - Cancel: only when status ∈ {queued, preparing, running}. Opens a
 *    confirm dialog; on confirm, calls `trpc.jobs.cancel`. The server
 *    transitions to `cancelling`; the worker tears down asynchronously.
 *  - Retry: only when status === 'failed'. Routes to the submit page
 *    with `?retryOf=<id>` so the form pre-fills using the original params.
 *  - Clone: always available. Routes to submit with `?cloneOf=<id>`.
 *
 * The submit page is responsible for hydrating the form from those query
 * params; this component only owns the action and navigation.
 */

interface JobActionsProps {
  jobId: string;
  toolId: string;
  status: JobStatus;
  /** Retained for callers; inputs are loaded by ID after authenticated navigation. */
  params?: Record<string, unknown> | null;
  className?: string;
  onCancelled?: () => void;
}

const CANCELLABLE: JobStatus[] = ["queued", "preparing", "running"];

export function JobActions({
  jobId,
  toolId,
  status,
  className,
  onCancelled,
}: JobActionsProps) {
  const router = useRouter();
  const utils = trpc.useUtils();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  const cancelMutation = trpc.jobs.cancel.useMutation({
    onSuccess: async () => {
      await utils.jobs.get.invalidate({ id: jobId });
      await utils.jobs.list.invalidate();
      setConfirmOpen(false);
      onCancelled?.();
    },
  });

  const canCancel = CANCELLABLE.includes(status);
  const canRetry = status === "failed";
  const canDownload = status === "succeeded" || status === "partial";

  const submitHref = (qs: string) =>
    `/app/jobs/new?tool=${encodeURIComponent(toolId)}&${qs}`;

  // Keep research inputs out of URLs, browser history, and referrer headers.
  const duplicateHref = () => {
    const qs = new URLSearchParams({ cloneOf: jobId, preset: "1" });
    return `/app/jobs/new?tool=${encodeURIComponent(toolId)}&${qs.toString()}`;
  };



  return (
    <>
      <div
        className={cn("flex flex-wrap items-center gap-2", className)}
        role="toolbar"
        aria-label="Job actions"
      >
        {canCancel && (
          <button
            type="button"
            onClick={() => setConfirmOpen(true)}
            disabled={cancelMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-crane-deep bg-paper px-3 py-1.5 font-sans text-[12px] text-crane-deep hover:bg-crane-glow disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {cancelMutation.isPending ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Ban className="w-3 h-3" />
            )}
            Cancel
          </button>
        )}

        {canRetry && (
          <button
            type="button"
            onClick={() => router.push(submitHref(`retryOf=${jobId}`))}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ink bg-ink px-3 py-1.5 font-sans text-[12px] text-paper hover:opacity-90"
          >
            <RotateCcw className="w-3 h-3" />
            Retry
          </button>
        )}

        <button
          type="button"
          onClick={() => router.push(duplicateHref())}
          className="inline-flex items-center gap-1.5 rounded-lg border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite hover:text-ink hover:border-ink"
          title="Open the submit form preselected with this job's params"
        >
          <CopyIcon className="w-3 h-3" />
          Duplicate job
        </button>

        {canDownload && (
          <button
            type="button"
            onClick={() => setExportOpen((open) => !open)}
            aria-expanded={exportOpen}
            aria-controls="job-export-panel"
            className="inline-flex items-center gap-1.5 rounded-lg border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite hover:text-ink hover:border-ink"
            title="Download all results and scores"
          >
            <Download className="w-3 h-3" />
            Download all
          </button>
        )}

        {cancelMutation.error && (
          <span className="font-sans text-[12px] text-crane-deep">
            {cancelMutation.error.message}
          </span>
        )}
      </div>

      {exportOpen && canDownload && (
        <section id="job-export-panel" aria-label="Download job results" className="basis-full w-full bg-paper p-5">
          <div className="mb-4 flex items-center justify-between gap-4">
            <h2 className="text-base font-medium text-ink">Download results</h2>
            <button type="button" onClick={() => setExportOpen(false)} className="text-sm text-graphite hover:text-ink">Close</button>
          </div>
          <ExportPanel mode="job" targetId={jobId} label={toolId} />
        </section>
      )}

      {confirmOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="cancel-dialog-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40"
          onClick={() => !cancelMutation.isPending && setConfirmOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="rounded-lg border border-lattice bg-paper p-6 max-w-md w-[90vw] shadow-xl space-y-4"
          >
            <h3
              id="cancel-dialog-title"
              className="font-display text-display-sm text-ink"
            >
              Cancel this job?
            </h3>
            <p className="font-sans text-[13px] text-graphite leading-relaxed">
              Saved results will be kept. Work already in progress may finish
              before cancellation takes effect.
            </p>
            <p className="font-mono text-[11px] text-graphite-soft">{jobId}</p>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                disabled={cancelMutation.isPending}
                className="rounded-lg border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite hover:text-ink"
              >
                Keep running
              </button>
              <button
                type="button"
                onClick={() => cancelMutation.mutate({ jobId })}
                disabled={cancelMutation.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg border border-crane-deep bg-crane-deep px-3 py-1.5 font-sans text-[12px] text-paper hover:opacity-90 disabled:opacity-60"
              >
                {cancelMutation.isPending && (
                  <Loader2 className="w-3 h-3 animate-spin" />
                )}
                Confirm cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
