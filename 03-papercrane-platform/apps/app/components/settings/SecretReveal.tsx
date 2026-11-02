"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

export interface SecretRevealProps {
  /** Plaintext secret: shown exactly once, never persisted client-side. */
  secret: string;
  /** Fires once the user ticks the confirmation and presses "I saved it". */
  onDismiss: () => void;
  /** Optional title: defaults match an API key creation flow. */
  title?: string;
  description?: string;
  confirmLabel?: string;
}

/**
 * Inline (non-modal) "show once" secret reveal panel.
 *
 * Differs from {@link ../keys/SecretRevealModal SecretRevealModal} in that
 * it lives inline above the resource list: useful for the settings keys
 * page and for webhook secrets where the page already owns the layout.
 *
 * Contract:
 *   - parent MUST clear the secret from state once `onDismiss` fires so
 *     React cannot re-render it
 *   - the confirm checkbox is required before dismiss is enabled
 *   - the `<code>` block is select-all so users without clipboard
 *     permission can still copy manually
 */
export function SecretReveal({
  secret,
  onDismiss,
  title = "Copy this secret now",
  description = "It won't be shown again. If you lose it, rotate the key to mint a new one.",
  confirmLabel = "I've saved it",
}: SecretRevealProps) {
  const [confirmed, setConfirmed] = useState(false);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  const copy = async () => {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(secret);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }
    } catch {
      // ignore: code block is select-all
    }
  };

  return (
    <div
      role="region"
      aria-label="New secret revealed once"
      className="rounded-lg border border-crane-glow bg-crane-glow/60 p-6"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-[18px] text-ink">{title}</h3>
          <p className="mt-1 max-w-xl font-sans text-[13px] text-crane-deep">
            {description}
          </p>
        </div>
        <span className="font-sans text-[12px] text-crane-deep">
          show once
        </span>
      </div>

      <div className="mt-4 flex items-stretch gap-2">
        <code className="flex-1 select-all break-all rounded-xl bg-paper px-4 py-3 font-mono text-[13px] text-ink">
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

      <label className="mt-4 flex items-start gap-2 cursor-pointer">
        <input
          ref={ref}
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-lattice-strong text-ink focus:ring-ink"
        />
        <span className="font-sans text-[13px] text-ink">
          I&apos;ve saved this somewhere safe.
        </span>
      </label>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={onDismiss}
          disabled={!confirmed}
          className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  );
}

export default SecretReveal;
