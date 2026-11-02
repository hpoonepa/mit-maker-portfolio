"use client";

import type { JobStatus } from "@papercrane/types";
import { cn } from "@/lib/utils";

/**
 * Animated status pill, reusable across the jobs list, job detail, and
 * notifications. The dot pulses for in-flight states (queued, preparing,
 * running, cancelling) and stays solid for terminal states.
 *
 * The local list page in `app/(dashboard)/app/jobs/page.tsx` defines its
 * own `StatusPill` for now; new code should import this one instead so
 * we eventually consolidate. The visual contract is identical.
 */
export interface JobStatusBadgeProps {
  status: JobStatus;
  /** Optional label override: defaults to the status string in caps. */
  label?: string;
  className?: string;
  size?: "sm" | "md";
}

export function JobStatusBadge({
  status,
  label,
  className,
  size = "md",
}: JobStatusBadgeProps) {
  const tone = statusTone(status);
  const dot = dotTone(status);
  const isPending = isInFlight(status);
  const text = label ?? status;
  return (
    <span
      data-testid={`job-status-${status}`}
      aria-live={isPending ? "polite" : undefined}
      className={cn(
        "inline-flex items-center gap-1.5 font-sans",
        size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-0.5 text-[12px]",
        tone,
        className
      )}
    >
      <span
        aria-hidden
        className={cn(
          "inline-block rounded-full",
          size === "sm" ? "h-1 w-1" : "h-1.5 w-1.5",
          dot,
          isPending && "animate-pulse"
        )}
      />
      {text}
    </span>
  );
}

function isInFlight(status: JobStatus): boolean {
  return (
    status === "queued" ||
    status === "preparing" ||
    status === "running" ||
    status === "cancelling"
  );
}

function statusTone(status: JobStatus): string {
  switch (status) {
    case "succeeded":
      return "text-crane";
    case "failed":
    case "cancelled":
      return "text-rose-300";
    case "running":
    case "preparing":
    case "cancelling":
      return "text-ink";
    case "partial":
      return "text-graphite";
    case "purged":
      return "text-graphite-soft";
    default:
      return "text-graphite";
  }
}

function dotTone(status: JobStatus): string {
  switch (status) {
    case "succeeded":
      return "bg-ink";
    case "failed":
    case "cancelled":
      return "bg-crane";
    case "running":
    case "preparing":
    case "cancelling":
      return "bg-crane";
    default:
      return "bg-graphite-soft";
  }
}

export default JobStatusBadge;
