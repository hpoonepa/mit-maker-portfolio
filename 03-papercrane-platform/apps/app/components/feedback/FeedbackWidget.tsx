"use client";

import { useEffect, useState } from "react";
import { MessageCircleQuestion } from "lucide-react";
import { installFeedbackDiagnostics } from "@/lib/screenshot";
import { FeedbackForm } from "./FeedbackForm";

interface FeedbackWidgetProps {
  /**
   * Optional caller info merged into every submission's metadata. Lets the
   * admin view show "submitted by X (orgY, pro)" without an extra DB roundtrip.
   */
  userInfo?: {
    userId?: string;
    orgSlug?: string;
    tier?: string;
  };
}

/**
 * Floating "?" button anchored to the bottom-right of the dashboard. On
 * click it mounts the {@link FeedbackForm} modal. The button is small
 * (40px) and uses pointer-events: none on its container so it never
 * eats clicks meant for content; only the button itself is interactive.
 *
 * The widget also installs `installFeedbackDiagnostics()` on mount so that
 * console errors and 4xx/5xx fetches are captured into ringbuffers, ready
 * to be attached to a future submission.
 */
export function FeedbackWidget({ userInfo }: FeedbackWidgetProps = {}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    installFeedbackDiagnostics();
  }, []);

  return (
    <>
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-40 sm:bottom-6 sm:right-6"
        aria-hidden={open ? "true" : undefined}
      >
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Send feedback"
          title="Send feedback"
          data-testid="feedback-widget-button"
          className="pointer-events-auto inline-flex h-10 w-10 items-center justify-center rounded-full border border-lattice bg-paper text-ink shadow-md transition hover:bg-paper-fold/60 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-ink/40"
        >
          <MessageCircleQuestion className="h-4 w-4" aria-hidden />
        </button>
      </div>
      <FeedbackForm
        open={open}
        onClose={() => setOpen(false)}
        {...(userInfo ? { userInfo } : {})}
      />
    </>
  );
}
