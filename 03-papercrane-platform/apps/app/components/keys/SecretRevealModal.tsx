"use client";

import { Check, Copy, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface SecretRevealModalProps {
  /** Plaintext secret: never stored anywhere client-side. */
  secret: string;
  /** Called after the user confirms they've saved the secret. */
  onClose: () => void;
  /** Title line (reused for both create and rotate). */
  title?: string;
  /** Body line under the title. */
  description?: string;
}

/**
 * Reveal-once modal. Shared between `CreateKeyModal` and `RotateKeyDialog`.
 *
 * Contract:
 *   - there is no close [x], no backdrop dismissal, no Escape handler
 *   - the only path out is the confirmation checkbox → "Close" button
 *   - once dismissed the parent MUST clear the secret from component state
 *     so React cannot re-render it (browser devtools / screenshots are the
 *     user's responsibility at that point)
 *
 * Copy button uses `navigator.clipboard` under the hood with a graceful
 * fallback: the `<code>` block is `select-all`, so a user without clipboard
 * permission can still triple-click and copy manually.
 */
export function SecretRevealModal({
  secret,
  onClose,
  title = "Save this key now",
  description = "You won't be able to see this secret again. If you lose it, rotate the key to generate a new one.",
}: SecretRevealModalProps) {
  const [confirmed, setConfirmed] = useState(false);
  const [copied, setCopied] = useState(false);
  const checkboxRef = useRef<HTMLInputElement | null>(null);

  // Focus the checkbox on mount so a keyboard user lands where they need to be.
  useEffect(() => {
    checkboxRef.current?.focus();
  }, []);

  const copy = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(secret);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }
    } catch {
      // Silent: the <code> is still selectable.
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="secret-reveal-title"
      aria-describedby="secret-reveal-desc"
    >
      <div className="relative w-full max-w-lg rounded-lg border border-crane-glow bg-paper p-6">
        <div>
          <h3
            id="secret-reveal-title"
            className="font-display text-[20px] text-ink"
          >
            {title}
          </h3>
          <p
            id="secret-reveal-desc"
            className="mt-1 font-sans text-[13px] text-graphite"
          >
            {description}
          </p>
        </div>

        <div className="mt-5 flex items-stretch gap-2">
          <code className="flex-1 rounded-xl bg-paper-fold px-4 py-3 font-mono text-[13px] text-ink break-all select-all">
            {secret}
          </code>
          <button
            type="button"
            onClick={copy}
            className="inline-flex items-center gap-1.5 rounded-xl border border-lattice bg-paper px-3 font-sans text-[12px] text-ink hover:border-ink transition-colors"
            aria-label="Copy secret to clipboard"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>

        <label className="mt-5 flex items-start gap-2 cursor-pointer">
          <input
            ref={checkboxRef}
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-lattice-strong text-ink focus:ring-ink"
          />
          <span className="font-sans text-[13px] text-ink">
            I&apos;ve saved this key in a safe place.
          </span>
        </label>

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={!confirmed}
            className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <X className="h-4 w-4" />
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

export default SecretRevealModal;
