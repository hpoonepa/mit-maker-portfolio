"use client";

import { useState } from "react";

/**
 * Small "BETA" pill that lives next to the logo / org switcher in the
 * topbar. Two jobs:
 *
 *   1. Signal to the user that this is a private preview, so unfinished
 *      polish or rough edges read as "beta thing" instead of "broken".
 *   2. Surface a fast path to feedback. Clicking the badge opens the
 *      FeedbackWidget that Wave 15 Agent 7 ships, via a CustomEvent so
 *      we don't introduce a circular import between the two beta
 *      surfaces.
 *
 * Hover tooltip uses the native `title` attribute on a wrapping span so
 * we get screen-reader semantics for free; the absolutely-positioned
 * tooltip is purely decorative.
 *
 * Visually we lean on the existing `crane-deep`/`crane-glow` tokens to
 * stay on-brand instead of introducing a new gold variable.
 */
export function BetaBadge({ className }: { className?: string }) {
  const [showTip, setShowTip] = useState(false);

  function openFeedback() {
    if (typeof window === "undefined") return;
    // Wave 15 Agent 7's FeedbackWidget listens for this event from
    // anywhere in the app. Decoupled so we don't import the widget.
    window.dispatchEvent(new CustomEvent("papercrane:open-feedback"));
  }

  return (
    <div
      className={`relative inline-flex ${className ?? ""}`}
      onMouseEnter={() => setShowTip(true)}
      onMouseLeave={() => setShowTip(false)}
      onFocus={() => setShowTip(true)}
      onBlur={() => setShowTip(false)}
    >
      <button
        type="button"
        onClick={openFeedback}
        aria-label="Paper Crane is in private beta: click to send feedback"
        data-testid="beta-badge"
        className="inline-flex items-center gap-1 rounded-full border border-crane-deep/30 bg-crane-glow px-2 py-0.5 font-sans text-[12px] text-crane-deep transition-colors hover:bg-crane-deep hover:text-paper focus:outline-none focus:ring-2 focus:ring-crane-deep/40"
      >
        <span aria-hidden="true">●</span>
        Beta
      </button>

      {showTip && (
        <div
          role="tooltip"
          className="pointer-events-none absolute left-1/2 top-full z-40 mt-2 w-56 -translate-x-1/2 rounded-xl border border-lattice bg-paper px-3 py-2 font-sans text-[11px] leading-snug text-graphite shadow-md"
        >
          Paper Crane is in private beta. Help us improve: click to send feedback.
        </div>
      )}
    </div>
  );
}
