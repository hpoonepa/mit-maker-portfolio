"use client";

import { Check } from "lucide-react";
import type { WebhookEventType } from "@papercrane/types";
import { cn } from "@/lib/utils";

/**
 * Multi-select for the webhook event catalog.
 *
 * `value` is typed as `WebhookEventType`: the same enum `webhooks.create`
 * validates against: so an event the router would reject is a compile error
 * here rather than a 400 at submit time.
 */
export const WEBHOOK_EVENTS = [
  {
    value: "job.status",
    label: "Job status changed",
    description: "Fires on every job state transition.",
  },
  {
    value: "job.succeeded",
    label: "Job succeeded",
    description: "Fires when a design job completes successfully.",
  },
  {
    value: "job.failed",
    label: "Job failed",
    description: "Fires when a job ends in failed or cancelled.",
  },
  {
    value: "design.created",
    label: "Design created",
    description: "Fires when a new design is written to your project.",
  },
] as const satisfies readonly {
  value: WebhookEventType;
  label: string;
  description: string;
}[];

export type WebhookEvent = WebhookEventType;

export interface EventPickerProps {
  value: WebhookEvent[];
  onChange: (next: WebhookEvent[]) => void;
  ariaInvalid?: boolean;
  describedBy?: string;
}

export function EventPicker({
  value,
  onChange,
  ariaInvalid,
  describedBy,
}: EventPickerProps) {
  const toggle = (event: WebhookEvent) => {
    if (value.includes(event)) {
      onChange(value.filter((v) => v !== event));
    } else {
      onChange([...value, event]);
    }
  };

  return (
    <fieldset
      aria-invalid={ariaInvalid || undefined}
      aria-describedby={describedBy}
      className="space-y-2"
    >
      <legend className="sr-only">Events to subscribe to</legend>
      <ul role="list" className="space-y-2">
        {WEBHOOK_EVENTS.map((ev) => {
          const selected = value.includes(ev.value);
          return (
            <li key={ev.value}>
              <button
                type="button"
                role="checkbox"
                aria-checked={selected}
                onClick={() => toggle(ev.value)}
                onKeyDown={(e) => {
                  if (e.key === " " || e.key === "Enter") {
                    e.preventDefault();
                    toggle(ev.value);
                  }
                }}
                className={cn(
                  "flex w-full items-start gap-3 rounded-lg border bg-paper px-4 py-3 text-left transition-colors",
                  selected
                    ? "border-ink"
                    : "border-lattice hover:border-lattice-strong",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "mt-0.5 inline-flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border transition-colors",
                    selected
                      ? "border-ink bg-ink text-paper"
                      : "border-lattice-strong bg-paper",
                  )}
                >
                  {selected && <Check className="h-3 w-3" />}
                </span>
                <span className="flex-1">
                  <span className="block font-sans text-[12px] text-ink">
                    {ev.value}
                  </span>
                  <span className="mt-0.5 block font-sans text-[13px] text-graphite">
                    {ev.description}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

export default EventPicker;
