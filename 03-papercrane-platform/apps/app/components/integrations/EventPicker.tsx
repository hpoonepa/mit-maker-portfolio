"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Multi-select for chat-integration events.
 *
 * The catalog here is a *superset* of the public webhook event picker -
 * billing/member/usage events aren't part of the signed-webhooks API,
 * but they make sense for Slack/Discord. Default toggles encode the
 * "noisy vs not" trade-off: design.created and member.invited are off
 * by default, everything else on.
 *
 * Mirror the registry on the server in
 * `packages/trpc/src/routers/integrations.ts` and the formatter switches
 * in `apps/worker/src/integrations/{slack,discord}.ts`.
 */
export const INTEGRATION_EVENTS = [
  {
    value: "job.completed",
    label: "Job completed",
    description: "A design job finished successfully.",
    defaultOn: true,
  },
  {
    value: "job.failed",
    label: "Job failed",
    description: "A job ended in failed or cancelled.",
    defaultOn: true,
  },
  {
    value: "design.created",
    label: "Design created",
    description: "Each new design surfaced: high volume, off by default.",
    defaultOn: false,
  },
  {
    value: "billing.upgraded",
    label: "Plan upgraded",
    description: "Org subscription moved to a new tier.",
    defaultOn: true,
  },
  {
    value: "member.invited",
    label: "Member invited",
    description: "A teammate was invited to the workspace.",
    defaultOn: false,
  },
  {
    value: "usage.cap_warning",
    label: "Usage approaching cap",
    description: "Seeds used crossed the configured threshold (default 80%).",
    defaultOn: true,
  },
  {
    value: "usage.cap_reached",
    label: "Usage cap reached",
    description: "Monthly seed cap hit; new jobs blocked until upgrade.",
    defaultOn: true,
  },
] as const;

export type IntegrationEvent = (typeof INTEGRATION_EVENTS)[number]["value"];

export const DEFAULT_INTEGRATION_EVENTS: IntegrationEvent[] = INTEGRATION_EVENTS
  .filter((e) => e.defaultOn)
  .map((e) => e.value as IntegrationEvent);

export interface EventPickerProps {
  value: IntegrationEvent[];
  onChange: (next: IntegrationEvent[]) => void;
  disabled?: boolean;
  ariaInvalid?: boolean;
  describedBy?: string;
}

export function EventPicker({
  value,
  onChange,
  disabled,
  ariaInvalid,
  describedBy,
}: EventPickerProps) {
  const toggle = (event: IntegrationEvent) => {
    if (disabled) return;
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
      disabled={disabled || undefined}
      className={cn("space-y-2", disabled && "opacity-60")}
    >
      <legend className="sr-only">Events to forward</legend>
      <ul role="list" className="space-y-2">
        {INTEGRATION_EVENTS.map((ev) => {
          const selected = value.includes(ev.value as IntegrationEvent);
          return (
            <li key={ev.value}>
              <button
                type="button"
                role="checkbox"
                aria-checked={selected}
                onClick={() => toggle(ev.value as IntegrationEvent)}
                onKeyDown={(e) => {
                  if (e.key === " " || e.key === "Enter") {
                    e.preventDefault();
                    toggle(ev.value as IntegrationEvent);
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
