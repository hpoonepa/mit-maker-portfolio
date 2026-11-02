"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, X } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

export interface LeaveOrgDialogProps {
  orgName: string;
  onClose: () => void;
  /** Where to redirect after successfully leaving. Defaults to `/login`. */
  redirectTo?: string;
}

/**
 * Confirmation dialog for `members.leave`. The confirmation string pattern
 * matches the GitHub/Linear "type the org name to confirm" style so a
 * misclick can't evict you from your workspace.
 */
export function LeaveOrgDialog({
  orgName,
  onClose,
  redirectTo = "/login",
}: LeaveOrgDialogProps) {
  const router = useRouter();
  const [confirmText, setConfirmText] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const leave = trpc.members.leave.useMutation({
    onSuccess: () => {
      router.push(redirectTo);
    },
    onError: (err) => setErrorMessage(err.message),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const canSubmit = confirmText.trim() === orgName;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="leave-org-title"
    >
      <div className="relative w-full max-w-md rounded-lg border border-crane/40 bg-paper p-6">
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-4 top-4 inline-flex h-8 w-8 items-center justify-center rounded-full text-graphite hover:bg-paper-fold"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-crane/40 bg-crane-glow text-crane-deep"
          >
            <AlertTriangle className="h-5 w-5" />
          </span>
          <div>
            <h3
              id="leave-org-title"
              className="font-display text-[20px] text-ink"
            >
              Leave {orgName}?
            </h3>
            <p className="mt-1 font-sans text-[13px] text-graphite">
              You'll lose access to projects, targets, and jobs in this org.
              An owner can re-invite you later.
            </p>
          </div>
        </div>

        {errorMessage && (
          <div
            role="alert"
            className="mt-5 rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
          >
            {errorMessage}
          </div>
        )}

        <label className="mt-5 flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Type{" "}
            <code className="font-mono text-[12px] text-ink">{orgName}</code>{" "}
            to confirm
          </span>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            className="rounded-xl border border-lattice-strong bg-paper px-4 py-3 font-mono text-[14px] text-ink focus:border-crane focus:outline-none"
            autoFocus
          />
        </label>

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canSubmit || leave.isPending}
            onClick={() => leave.mutate()}
            className="inline-flex items-center gap-1.5 rounded-full bg-crane px-5 py-2.5 font-sans text-[14px] text-paper hover:bg-crane-deep disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {leave.isPending ? "Leaving…" : "Leave org"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default LeaveOrgDialog;
