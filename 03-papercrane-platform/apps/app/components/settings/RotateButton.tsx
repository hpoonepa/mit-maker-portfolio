"use client";

import { RefreshCw, X } from "lucide-react";
import { useState } from "react";

export interface RotateButtonProps {
  /** Display name of the resource being rotated (key/webhook/etc). */
  resourceName: string;
  /** Called once the user confirms inside the modal. */
  onConfirm: () => Promise<void> | void;
  /** Optional small text override above the action. */
  variant?: "key" | "webhook";
  /** When true, the trigger button is disabled (e.g. resource is rotating). */
  disabled?: boolean;
}

/**
 * Inline rotate trigger + confirm modal with a 24h grace explainer.
 *
 * UX rules (mirrored from `RotateKeyDialog`):
 *   - confirmation modal is non-dismissible by clicking the backdrop
 *   - body explains the 24h grace where both old + new are accepted
 *   - the actual reveal of the new secret is the parent's job: this
 *     component fires `onConfirm()` and lets the parent show its own
 *     {@link SecretReveal} panel
 */
export function RotateButton({
  resourceName,
  onConfirm,
  variant = "key",
  disabled,
}: RotateButtonProps) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);

  const subject = variant === "webhook" ? "webhook secret" : "API key";

  const run = async () => {
    setPending(true);
    try {
      await onConfirm();
      setOpen(false);
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 rounded-full border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-ink hover:border-ink transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <RefreshCw className="h-3 w-3" />
        Rotate
      </button>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="rotate-title"
        >
          <div className="relative w-full max-w-md bg-paper p-6">
            <h3 id="rotate-title" className="font-display text-[20px] text-ink">
              Rotate &ldquo;{resourceName}&rdquo;
            </h3>
            <p className="mt-2 font-sans text-[13px] text-graphite">
              We&apos;ll generate a new {subject} and keep the old one valid for
              <strong className="text-ink"> 24 hours</strong>. Update your
              clients during that window: after the grace period the old{" "}
              {subject} stops working.
            </p>

            <ul className="mt-4 space-y-2 px-4 py-3 font-sans text-[12px] text-graphite">
              <li>Both old and new are accepted for 24h.</li>
              <li>The new {subject} is shown <strong>once</strong>, copy it now.</li>
              <li>You can revoke the old half early from the list.</li>
            </ul>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-full px-4 py-2 font-sans text-[14px] text-graphite hover:text-ink transition-colors"
                disabled={pending}
              >
                <X className="mr-1 inline h-3.5 w-3.5" />
                Cancel
              </button>
              <button
                type="button"
                onClick={run}
                disabled={pending}
                className="btn-primary disabled:opacity-60"
              >
                <RefreshCw className="h-4 w-4" />
                {pending ? "Rotating…" : "Rotate now"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

export default RotateButton;
