"use client";

import { useMemo } from "react";
import { CheckCircle2, Circle, Loader2, AlertTriangle } from "lucide-react";

import type { JobStatus } from "@papercrane/types";
import { cn } from "@/lib/utils";

/** Job lifecycle from recorded timestamps and explicit audit events. */

export interface TimelineEventInput {
  /** Stable id; used as React key. */
  id: string;
  /** Display label, e.g. 'Queued', 'Running', 'Tool: rfdiffusion'. */
  label: string;
  /** ISO timestamp when this event happened. */
  at?: string | null;
  /** Whether this step is currently active. */
  active?: boolean;
  /** Whether this step has completed. */
  done?: boolean;
  /** Whether this step terminated in failure. */
  failed?: boolean;
}

interface JobTimelineProps {
  status: JobStatus;
  submittedAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  toolChain?: string[];
  /** Optional extra events from the audit table; merged into the chain. */
  extraEvents?: TimelineEventInput[];
  className?: string;
}

export function JobTimeline({
  status,
  submittedAt,
  startedAt,
  finishedAt,
  toolChain = [],
  extraEvents = [],
  className,
}: JobTimelineProps) {
  const events = useMemo(
    () => buildEvents({ status, submittedAt, startedAt, finishedAt, toolChain, extraEvents }),
    [status, submittedAt, startedAt, finishedAt, toolChain, extraEvents],
  );

  return (
    <section aria-label="Job timeline" className={cn("space-y-4", className)}>
      <h2 className="font-sans text-[12px] text-graphite-soft">
        Timeline
      </h2>
      <ol
        role="list"
        className="grid items-start gap-2 overflow-x-auto pb-1"
        style={{ gridTemplateColumns: `repeat(${events.length}, minmax(96px, 1fr))` }}
      >
        {events.map((e, i) => {
          const next = events[i + 1];
          const dur = e.at && next?.at ? durationBetween(e.at, next.at) : null;
          const isLast = i === events.length - 1;
          return (
            <li key={e.id} className="relative flex flex-col gap-2 min-w-0">
              {/* Hairline connector to next step */}
              {!isLast && (
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-[9px] left-1/2 right-[-50%] h-px",
                    e.done && !e.failed ? "bg-ink/60" : "bg-lattice",
                  )}
                />
              )}
              {/* Step marker */}
              <span
                className={cn(
                  "relative z-10 mx-auto inline-flex h-[18px] w-[18px] items-center justify-center rounded-full border bg-paper",
                  e.failed
                    ? "border-crane-deep text-crane-deep"
                    : e.done
                      ? "border-ink text-ink"
                      : e.active
                        ? "border-crane bg-crane-glow text-crane-deep"
                        : "border-lattice text-graphite-soft",
                )}
              >
                {e.failed ? (
                  <AlertTriangle className="w-2.5 h-2.5" />
                ) : e.done ? (
                  <CheckCircle2 className="w-2.5 h-2.5" />
                ) : e.active ? (
                  <Loader2 className="w-2.5 h-2.5 animate-spin" />
                ) : (
                  <Circle className="w-2 h-2" />
                )}
              </span>
              <div className="text-center space-y-0.5 px-1 min-w-0">
                <p
                  className={cn(
                    "font-sans text-[12px] truncate",
                    e.failed
                      ? "text-crane-deep"
                      : e.done || e.active
                        ? "text-ink"
                        : "text-graphite-soft",
                  )}
                  title={e.label}
                >
                  {e.label}
                </p>
                <p className="font-mono text-[10px] text-graphite-soft tabular-nums">
                  {e.at ? fmtTime(e.at) : e.active ? "In progress" : ""}
                </p>
                {dur && (
                  <p className="font-mono text-[10px] text-graphite tabular-nums">
                    +{dur}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

interface BuildEventsArgs {
  status: JobStatus;
  submittedAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  toolChain: string[];
  extraEvents: TimelineEventInput[];
}

function buildEvents(args: BuildEventsArgs): TimelineEventInput[] {
  const { status, submittedAt, startedAt, finishedAt, extraEvents } = args;
  const terminalLabels: Partial<Record<JobStatus, string>> = {
    succeeded: "Completed", partial: "Partially completed", failed: "Failed",
    cancelled: "Cancelled", purged: "Purged",
  };
  const terminal = terminalLabels[status];
  const out: TimelineEventInput[] = [{ id: "submitted", label: "Submitted", at: submittedAt, done: true }];

  if (startedAt) {
    out.push({ id: "started", label: "Started", at: startedAt, done: true });
  }
  // Only show tool stages that were actually recorded. A successful job does
  // not supply the timestamps or status of each individual workflow stage.
  out.push(...extraEvents.filter((event) => event.at || event.active));

  if (terminal) {
    out.push({ id: "terminal", label: terminal, at: finishedAt, done: true, failed: status === "failed" });
  } else {
    const labels: Partial<Record<JobStatus, string>> = {
      queued: "Queued", preparing: "Preparing", running: "Running", cancelling: "Cancelling",
    };
    out.push({ id: "current", label: labels[status] ?? status, active: true });
  }
  return out;
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (!Number.isFinite(d.getTime())) return "";
    return d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}

function durationBetween(a: string, b: string): string | null {
  const ms = new Date(b).getTime() - new Date(a).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return rs ? `${m}m${rs}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h}h${rm}m` : `${h}h`;
}
