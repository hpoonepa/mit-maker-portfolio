"use client";

import { CheckCircle2 } from "lucide-react";

/**
 * Confirmation card shown briefly inside the feedback modal after a
 * successful submission. The widget auto-dismisses the modal a moment
 * later; we still render the card so the user gets a visual ack even
 * on slow displays where the toast would appear and disappear too fast.
 */
export function FeedbackThanks({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="flex flex-col items-center gap-3 px-6 py-10 text-center"
      role="status"
      aria-live="polite"
      data-testid="feedback-thanks"
    >
      <CheckCircle2 className="h-10 w-10 text-emerald-600" aria-hidden />
      <h3 className="font-sans text-[15px] font-medium text-ink">
        Thanks. We&apos;ll be in touch.
      </h3>
      <p className="max-w-xs font-sans text-[12.5px] text-ink/70">
        Your note is in our inbox. We read every one and the team often
        replies within a day or two during the beta.
      </p>
      <button
        type="button"
        onClick={onClose}
        className="mt-2 rounded-full border border-lattice px-4 py-1.5 font-sans text-[12.5px] text-ink hover:bg-paper-fold/50"
      >
        Close
      </button>
    </div>
  );
}
