"use client";

import { Send } from "lucide-react";
import { cn } from "@/lib/utils";

export interface TestWebhookButtonProps {
  webhookId: string;
  /** Retained for API compatibility; unused while test delivery is unreleased. */
  disabled?: boolean;
  /** Retained for API compatibility; unused while test delivery is unreleased. */
  onResult?: (msg: { kind: "ok" | "err"; message: string }) => void;
}

/**
 * Test delivery: not available in beta.
 *
 * Firing a synthetic `test.ping` needs `webhooks.test`, which is not on the
 * router. The control stays visible (so the affordance is discoverable) but is
 * permanently disabled and labelled, rather than calling a procedure that
 * fails at runtime.
 */
export function TestWebhookButton(_props: TestWebhookButtonProps) {
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        disabled
        aria-disabled="true"
        title="Test deliveries arrive after the beta"
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border border-lattice bg-paper px-3 py-1.5 font-sans text-[12px] text-graphite",
          "opacity-60 cursor-not-allowed",
        )}
      >
        <Send className="h-3 w-3" aria-hidden="true" />
        Send test
      </button>
      <span className="font-sans text-[12px] text-graphite-soft">
        After beta
      </span>
    </span>
  );
}

export default TestWebhookButton;
