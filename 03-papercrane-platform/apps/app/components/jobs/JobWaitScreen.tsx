"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { JobStatus } from "@papercrane/types";
import { jobInputKind } from "@papercrane/types";
import { cn } from "@/lib/utils";
import {
  formatResultMetric,
  resultMetrics,
  toolLabel,
} from "@/lib/results/metrics";
import { trpc } from "@/lib/trpc/client";
import { JobActions } from "./JobActions";
import { JobProgressBar } from "./JobProgressBar";
import { JobAlertToggle } from "./JobCompletionAlerts";
import { submittedRunDetails } from "./submittedRunDetails";

interface JobWaitScreenProps {
  jobId: string;
  toolId: string;
  status: JobStatus;
  numDesigns: number;
  completedDesigns: number;
  submittedAt: string;
  startedAt?: string | null;
  targetLabel?: string | null;
  params?: Record<string, unknown> | null;
  estSecondsPerDesign?: number | null;
  initialEtaSeconds?: number | null;
  syncDelayed?: boolean;
  className?: string;
}

const ACTIVE_STATUSES: ReadonlySet<JobStatus> = new Set([
  "queued",
  "preparing",
  "running",
  "cancelling",
]);
const HEADLINES: Partial<Record<JobStatus, string>> = {
  queued: "Queued",
  preparing: "Preparing",
  running: "Running",
  cancelling: "Cancelling",
};

export function JobWaitScreen({
  jobId,
  toolId,
  status,
  numDesigns,
  completedDesigns,
  submittedAt,
  startedAt,
  targetLabel,
  params,
  estSecondsPerDesign,
  initialEtaSeconds,
  syncDelayed,
  className,
}: JobWaitScreenProps) {
  const name = toolLabel(toolId);
  const countLabel =
    jobInputKind(toolId.split("+")) === "complex" ? "predictions" : "designs";
  const details = submittedRunDetails(params, targetLabel);

  return (
    <section
      aria-label={`Job ${jobId.slice(0, 8)}`}
      className={cn("space-y-10", className)}
    >
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <div className="mb-4 flex flex-wrap items-baseline gap-3">
            <span className="text-lg text-ink">{name}</span>
            <span className="font-mono text-xs text-graphite" title={jobId}>
              {jobId.slice(0, 8)}
            </span>
          </div>
          <h1
            aria-live="polite"
            className="text-[42px] leading-tight tracking-[-0.035em] text-ink sm:text-[52px]"
          >
            {HEADLINES[status] ?? status}
          </h1>
        </div>
        <JobActions
          jobId={jobId}
          toolId={toolId}
          status={status}
          params={params}
        />
      </header>

      {syncDelayed && (
        <p role="status" className="text-sm text-graphite">
          Connection interrupted. Reconnecting…
        </p>
      )}

      <div className="grid gap-12 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:gap-20">
        <div className="space-y-8">
          {status === "running" && (
            <JobProgressBar
              completed={completedDesigns}
              total={numDesigns}
              label={`${completedDesigns} of ${numDesigns} ${countLabel} complete`}
            />
          )}
          <RunTiming
            status={status}
            submittedAt={submittedAt}
            startedAt={startedAt}
            completed={completedDesigns}
            total={numDesigns}
            estimatedTotal={initialEtaSeconds}
            estimatedPerDesign={estSecondsPerDesign}
          />
          <JobAlertToggle jobId={jobId} toolName={name} />
          <AvailableResults
            jobId={jobId}
            toolId={toolId}
            enabled={status === "running" || completedDesigns > 0}
          />
        </div>

        <aside aria-label="Submitted inputs" className="space-y-6">
          <h2 className="text-lg text-ink">Submitted inputs</h2>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-5">
            {details.map((detail) => (
              <div
                key={detail.label}
                className={detail.wide ? "col-span-2" : undefined}
              >
                <dt className="text-sm text-graphite">{detail.label}</dt>
                <dd
                  className={cn(
                    "mt-1.5 break-words text-base text-ink",
                    detail.mono && "font-mono text-sm",
                  )}
                >
                  {detail.value}
                </dd>
              </div>
            ))}
            <div>
              <dt className="text-sm capitalize text-graphite">{countLabel}</dt>
              <dd className="mt-1.5 text-base tabular-nums text-ink">
                {numDesigns}
              </dd>
            </div>
            <div>
              <dt
                className="text-sm text-graphite"
                title="Usage credits, separate from random seeds"
              >
                Seeds spent
              </dt>
              <dd className="mt-1.5 text-base tabular-nums text-ink">
                {completedDesigns}
              </dd>
            </div>
          </dl>
          <Link
            href={`/app/tools/${toolId.split("+")[0]}`}
            className="inline-block text-sm text-graphite hover:text-ink"
          >
            About {name}
          </Link>
        </aside>
      </div>
    </section>
  );
}

function RunTiming({
  status,
  submittedAt,
  startedAt,
  completed,
  total,
  estimatedTotal,
  estimatedPerDesign,
}: {
  status: JobStatus;
  submittedAt: string;
  startedAt?: string | null;
  completed: number;
  total: number;
  estimatedTotal?: number | null;
  estimatedPerDesign?: number | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const elapsed = Math.max(
    0,
    Math.floor((now - Date.parse(startedAt ?? submittedAt)) / 1000),
  );
  const remaining =
    status !== "running"
      ? null
      : completed > 0 && startedAt
        ? Math.round((elapsed / completed) * Math.max(0, total - completed))
        : estimatedTotal != null && startedAt
          ? estimatedTotal - elapsed
          : estimatedPerDesign != null
            ? total * estimatedPerDesign - elapsed
            : null;

  return (
    <dl className="flex flex-wrap gap-x-12 gap-y-5">
      <div>
        <dt className="text-sm text-graphite">
          {startedAt ? "Runtime" : "Elapsed"}
        </dt>
        <dd className="mt-2 text-2xl tabular-nums text-ink">
          {formatElapsed(elapsed)}
        </dd>
      </div>
      {remaining !== null && remaining > 0 && (
        <div>
          <dt className="text-sm text-graphite">Est. remaining</dt>
          <dd className="mt-2 text-2xl tabular-nums text-ink">
            {formatElapsed(remaining)}
          </dd>
        </div>
      )}
    </dl>
  );
}

function formatElapsed(seconds: number) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function AvailableResults({
  jobId,
  toolId,
  enabled,
}: {
  jobId: string;
  toolId: string;
  enabled: boolean;
}) {
  const query = trpc.designs.listByJob.useQuery(
    { jobId, limit: 5 },
    { enabled, refetchInterval: enabled ? 5_000 : false },
  );
  const designs = query.data?.items ?? [];
  if (!designs.length) return null;
  return (
    <section aria-label="Available results" className="space-y-3">
      <h2 className="text-sm text-graphite">Available results</h2>
      <ul className="space-y-3">
        {designs.map((design) => {
          const metric = resultMetrics(toolId, design.metrics ?? {})[0];
          return (
            <li key={design.id}>
              <Link
                href={`/app/designs/${design.id}`}
                className="flex flex-wrap items-center justify-between gap-2 text-sm hover:text-crane"
              >
                <span className="text-ink">
                  Result <span className="font-mono">{design.seed}</span>
                </span>
                <span className="text-graphite">
                  {metric
                    ? `${metric.label} ${formatResultMetric(metric)}`
                    : "View result"}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function shouldShowWaitScreen({
  status,
}: {
  status: JobStatus;
  estimatedTotalSeconds: number | null | undefined;
}) {
  return ACTIVE_STATUSES.has(status);
}

export default JobWaitScreen;
