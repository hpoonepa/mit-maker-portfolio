"use client";

import { useEffect, useState } from "react";
import { Trash2, X } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import type { KeyRecord } from "@/lib/keys/rotation";

export interface RevokeKeyDialogProps {
  open: boolean;
  target: KeyRecord | null;
  onClose: () => void;
  /** Fired after the mutation succeeds, before `onClose`. */
  onRevoked?: () => void;
}

/**
 * Revoke confirmation with type-to-confirm safety pattern.
 *
 * The operator must type the key's name exactly before the destructive CTA
 * enables. This mirrors the GitHub / Stripe dashboard pattern for irrevocable
 * operations: a typo in a key name can cost a team its CI pipeline, so we
 * lean hard on friction here rather than a plain "Yes, delete" button.
 *
 * Comparison is exact-match, whitespace-trimmed, case-sensitive. The expected
 * value is rendered prominently so the operator can copy/paste it when the
 * name is long or contains unusual characters.
 */
export function RevokeKeyDialog({
  open,
  target,
  onClose,
  onRevoked,
}: RevokeKeyDialogProps) {
  const utils = trpc.useUtils();
  const [typed, setTyped] = useState("");
  const [topError, setTopError] = useState<string | null>(null);

  const revoke = trpc.keys.revoke.useMutation({
    onSuccess: () => {
      void utils.keys.list.invalidate();
      onRevoked?.();
      closeEverything();
    },
    onError: (err) => {
      setTopError(err.message ?? "Could not revoke key");
    },
  });

  const closeEverything = () => {
    setTyped("");
    setTopError(null);
    onClose();
  };

  // Clear the typed confirmation whenever the dialog is re-opened for a new
  // target. Avoids a stale value matching the previous key name accidentally.
  useEffect(() => {
    if (open) setTyped("");
  }, [open, target?.id]);

  if (!open || !target) return null;

  const confirmed = typed.trim() === target.name;
  const busy = revoke.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="revoke-key-title"
    >
      <div className="relative w-full max-w-md rounded-lg border border-crane/40 bg-paper p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-crane/60 bg-crane-glow">
              <Trash2 className="h-5 w-5 text-crane-deep" />
            </div>
            <div>
              <h3 id="revoke-key-title" className="font-display text-[20px] text-ink">
                Revoke this key immediately?
              </h3>
              <p className="mt-1 font-sans text-[13px] text-graphite">
                Requests signed with this key will fail on the next call. There
                is no grace window and no undo: you&apos;ll need to mint a new
                key from scratch.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={closeEverything}
            className="rounded-full p-1 text-graphite hover:text-ink transition-colors"
            aria-label="Cancel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5 px-4 py-3 font-sans text-[13px] text-graphite">
          <div className="flex items-baseline gap-2">
            <span className="font-sans text-[12px] text-graphite-soft">
              Key
            </span>
            <span className="font-mono text-[13px] text-ink">{target.name}</span>
          </div>
          <div className="mt-1 font-mono text-[12px] text-graphite-soft">
            {target.prefix}…
          </div>
        </div>

        <label className="mt-5 flex flex-col gap-1.5">
          <span className="font-sans text-[12px] text-graphite-soft">
            Type <span className="font-mono text-ink">{target.name}</span> to confirm
          </span>
          <input
            type="text"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            aria-invalid={typed.length > 0 && !confirmed}
            className={cn(
              "rounded-xl border bg-paper px-4 py-3 font-mono text-[13px] text-ink placeholder:text-graphite-soft focus:outline-none",
              typed.length > 0 && !confirmed
                ? "border-crane focus:border-crane-deep"
                : "border-lattice-strong focus:border-ink",
            )}
            placeholder={target.name}
          />
        </label>

        {topError && (
          <div
            role="alert"
            className="mt-4 rounded-lg border border-crane/40 bg-crane-glow px-4 py-3 font-sans text-[13px] text-crane-deep"
          >
            {topError}
          </div>
        )}

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={closeEverything}
            className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => revoke.mutate({ id: target.id })}
            disabled={!confirmed || busy}
            className={cn(
              "inline-flex items-center gap-2 rounded-full px-5 py-2.5 font-sans text-[14px] transition-colors",
              confirmed && !busy
                ? "bg-crane-deep text-paper hover:bg-crane"
                : "bg-paper-fold text-graphite-soft cursor-not-allowed",
            )}
          >
            <Trash2 className="h-4 w-4" />
            {busy ? "Revoking…" : "Revoke key"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default RevokeKeyDialog;
