"use client";

import { useState } from "react";
import { RefreshCw, X } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import type { KeyRecord } from "@/lib/keys/rotation";
import { SecretRevealModal } from "./SecretRevealModal";

export interface RotateKeyDialogProps {
  open: boolean;
  target: KeyRecord | null;
  onClose: () => void;
}

/**
 * Rotation confirmation → secret-reveal flow.
 *
 * The spec calls for a single click-through dialog that explains the 24h
 * grace window before letting the operator commit. After the mutation
 * resolves we dismount the confirm view and mount `SecretRevealModal` to
 * surface the new plaintext: same pattern as create.
 *
 * We deliberately do not `invalidate` until the reveal modal closes. That
 * way the list re-renders only once, right as the user dismisses the secret,
 * rather than flashing the "rotating" pill before they've copied the key.
 */
export function RotateKeyDialog({ open, target, onClose }: RotateKeyDialogProps) {
  const utils = trpc.useUtils();
  const [revealed, setRevealed] = useState<string | null>(null);
  const [topError, setTopError] = useState<string | null>(null);

  const rotate = trpc.keys.rotate.useMutation({
    onSuccess: (result) => {
      setRevealed(result.secret);
    },
    onError: (err) => {
      setTopError(err.message ?? "Could not rotate key");
    },
  });

  const closeEverything = () => {
    setRevealed(null);
    setTopError(null);
    // Invalidate once, on final dismiss, so the list picks up the new +
    // rotating rows in the same render pass.
    void utils.keys.list.invalidate();
    onClose();
  };

  const closeConfirm = () => {
    setTopError(null);
    onClose();
  };

  if (!open || !target) return null;

  if (revealed) {
    return (
      <SecretRevealModal
        secret={revealed}
        title="Your new API key"
        description={`"${target.name}" is rotated. The old key keeps working for 24 hours: swap it in your systems before then.`}
        onClose={closeEverything}
      />
    );
  }

  const busy = rotate.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rotate-key-title"
    >
      <div className="relative w-full max-w-md bg-paper p-6">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-crane/60 bg-crane-glow">
              <RefreshCw className="h-5 w-5 text-crane-deep" />
            </div>
            <div>
              <h3 id="rotate-key-title" className="font-display text-[20px] text-ink">
                Rotate {target.name}?
              </h3>
              <p className="mt-1 font-sans text-[13px] text-graphite">
                We&apos;ll mint a new secret and keep the old one working for
                24 hours so you can swap it in without downtime. After that,
                the old key is revoked automatically.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={closeConfirm}
            className="rounded-full p-1 text-graphite hover:text-ink transition-colors"
            aria-label="Cancel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5 px-4 py-3 font-sans text-[13px] text-graphite">
          <div className="font-mono text-[12px] text-ink">{target.prefix}…</div>
          <div className="mt-0.5">
            The new key will inherit the same scopes and expiration.
          </div>
        </div>

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
            onClick={closeConfirm}
            className="rounded-full px-5 py-2.5 font-sans text-[14px] text-graphite hover:text-ink transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => rotate.mutate({ id: target.id })}
            disabled={busy}
            className="btn-primary disabled:opacity-60"
          >
            <RefreshCw className="h-4 w-4" />
            {busy ? "Rotating…" : "Rotate & reveal new key"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default RotateKeyDialog;
