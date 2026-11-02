"use client";

/**
 * Small list-only bits for the Jobs list page: the inline StatusPill,
 * the toggleable StatusPillRow, and the formatting helpers (relative
 * time in mono caps, compact runtime, tool@version splitter).
 *
 * Job detail (`/app/jobs/[id]`) uses the shared `JobStatusBadge` instead.
 */

import type { JobStatus, JobSummary } from "@papercrane/types";
import { cn } from "@/lib/utils";

export const STATUS_OPTIONS: { id: JobStatus; label: string }[] = [
  { id: "queued", label: "Queued" },
  { id: "running", label: "Running" },
  { id: "succeeded", label: "Succeeded" },
  { id: "failed", label: "Failed" },
  { id: "cancelled", label: "Cancelled" },
];

export function StatusPill({ status }: { status: JobStatus }) {
  const isRunning = status === "running" || status === "preparing";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 py-0.5 font-sans text-[12px]",
        statusTone(status),
      )}
    >
      <span
        aria-hidden
        className={cn(
          "inline-block h-1.5 w-1.5 rounded-full",
          dotTone(status),
          isRunning && "animate-pulse",
        )}
      />
      {status}
    </span>
  );
}

export function StatusPillRow({
  jobs,
  active,
  onToggle,
}: {
  jobs: JobSummary[];
  active: string[];
  onToggle: (id: JobStatus) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {STATUS_OPTIONS.map((s) => {
        const count = jobs.filter((j) => j.status === s.id).length;
        const on = active.includes(s.id);
        const isRunning = s.id === "running";
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onToggle(s.id)}
            aria-pressed={on}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-2 font-sans text-[12px] transition-colors",
              on
                ? "bg-paper-fold text-ink"
                : "text-graphite hover:text-ink",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "inline-block h-1.5 w-1.5 rounded-full",
                isRunning ? "bg-crane animate-pulse" : on ? "bg-ink" : "bg-graphite-soft",
              )}
            />
            {s.label}
            <span className={cn("tabular-nums", on ? "text-ink" : "text-graphite-soft")}>
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function statusTone(status: JobStatus): string {
  switch (status) {
    case "succeeded":
      return "text-crane";
    case "failed":
    case "cancelled":
      return "text-graphite";
    case "running":
    case "preparing":
      return "text-ink";
    default:
      return "text-graphite";
  }
}

function dotTone(status: JobStatus): string {
  switch (status) {
    case "succeeded":
      return "bg-ink";
    case "running":
    case "preparing":
      return "bg-crane";
    case "failed":
    case "cancelled":
      return "bg-graphite";
    default:
      return "bg-graphite-soft";
  }
}

/** Mono caps relative time: "12m ago", "3h ago", "2d ago". */
export function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Math.max(0, Date.now() - then);
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  const w = Math.floor(d / 7);
  if (w < 5) return `${w}w ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  const y = Math.floor(d / 365);
  return `${y}y ago`;
}

/** Compact runtime: "12s" / "4m 12s" / "1h 03m". */
export function formatRuntime(startedAt?: string, finishedAt?: string): string | null {
  if (!startedAt) return null;
  const start = new Date(startedAt).getTime();
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now();
  const ms = Math.max(0, end - start);
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, "0")}m`;
}

/** Split "boltz2@1.4.0" -> { tool: "boltz2", version: "1.4.0" }. */
export function splitToolVersion(toolId: string): { tool: string; version?: string } {
  const at = toolId.lastIndexOf("@");
  if (at > 0 && at < toolId.length - 1) {
    return { tool: toolId.slice(0, at), version: toolId.slice(at + 1) };
  }
  return { tool: toolId };
}
