"use client";

import { useState } from "react";
import { Ban, Loader2 } from "lucide-react";

import type { JobStatus } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";

/**
 * CancelJobButton: focused cancel control with inline confirm.
 *
 *  - Only renders when status ∈ {queued, preparing, running}.
 *  - Click → swaps in an inline "Cancel job? This stops billing for new seeds."
 *    prompt with Yes / Keep buttons (no modal: keeps layout flow).
 *  - In-flight: button shows spinner + "Cancelling…".
 *  - Success: clears confirm state and calls `onSuccess` so the parent can
 *    invalidate its query cache. We deliberately do NOT invalidate here -
 *    the parent owns the query keys.
 *  - Failure: surfaces an inline error pill underneath the controls.
 *
 * Uses `trpc.jobs.cancel` (POST /jobs/{jobId}/cancel) which transitions the
 * job to status='cancelling' transactionally and publishes a cancel signal
 * to the worker. Final 'cancelled' state is reached asynchronously by the
 * worker.
 */

interface CancelJobButtonProps {
  jobId: string;
  status: JobStatus;
  onSuccess?: () => void;
  className?: string;
}

const CANCELLABLE: JobStatus[] = ["queued", "preparing", "running"];

const ghostBtn =
  "inline-flex items-center gap-1.5 rounded-lg border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite hover:text-ink hover:border-ink disabled:opacity-50 disabled:cursor-not-allowed";

const dangerBtn =
  "inline-flex items-center gap-1.5 rounded-lg border border-crane-deep bg-crane-deep px-3 py-1.5 font-sans text-[12px] text-paper hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed";

export function CancelJobButton({
  jobId,
  status,
  onSuccess,
  className,
}: CancelJobButtonProps) {
  const [confirming, setConfirming] = useState(false);

  const cancel = trpc.jobs.cancel.useMutation({
    onSuccess: () => {
      setConfirming(false);
      onSuccess?.();
    },
  });

  if (!CANCELLABLE.includes(status)) return null;

  const pending = cancel.isPending;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {!confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          disabled={pending}
          className={ghostBtn}
          aria-label="Cancel job"
        >
          <Ban className="w-3 h-3" aria-hidden />
          Cancel
        </button>
      ) : (
        <div
          role="group"
          aria-label="Confirm cancel"
          className="flex flex-wrap items-center gap-2 bg-paper-soft px-3 py-2"
        >
          <span className="font-sans text-[12px] text-graphite leading-snug">
            Cancel job? This stops billing for new seeds.
          </span>
          <div className="flex items-center gap-2 ml-auto">
            <button
              type="button"
              onClick={() => !pending && setConfirming(false)}
              disabled={pending}
              className={ghostBtn}
            >
              Keep
            </button>
            <button
              type="button"
              onClick={() => cancel.mutate({ jobId })}
              disabled={pending}
              className={dangerBtn}
              aria-label="Confirm cancel job"
            >
              {pending ? (
                <>
                  <Loader2 className="w-3 h-3 animate-spin" aria-hidden />
                  Cancelling…
                </>
              ) : (
                <>
                  <Ban className="w-3 h-3" aria-hidden />
                  Yes
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {cancel.error && (
        <span
          role="alert"
          className="inline-flex items-center self-start rounded-md border border-crane-deep/40 bg-crane-glow/40 px-2 py-0.5 font-mono text-[11px] text-crane-deep"
        >
          {cancel.error.message}
        </span>
      )}
    </div>
  );
}

export default CancelJobButton;
