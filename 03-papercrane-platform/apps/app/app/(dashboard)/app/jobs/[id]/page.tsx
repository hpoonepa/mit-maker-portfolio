"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Check, ChevronDown, Copy } from "lucide-react";

import type { JobStatus } from "@papercrane/types";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";
import { JobStatusBadge } from "@/components/jobs/JobStatusBadge";
import { JobLogStream } from "@/components/jobs/JobLogStream";
import { JobParamsTable } from "@/components/jobs/JobParamsTable";
import { JobActions } from "@/components/jobs/JobActions";
import { JobTimeline } from "@/components/jobs/JobTimeline";
import { RelatedJobs } from "@/components/jobs/RelatedJobs";
import { toolLabel } from "@/lib/results/metrics";
import {
  JobWaitScreen,
  shouldShowWaitScreen,
} from "@/components/jobs/JobWaitScreen";
import { DesignGrid } from "./DesignGrid";

/**
 * Job detail page: operator-grade UI for a single design job.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────┬──────────────────┐
 *   │ Header: id · tool · status · actions        │                  │
 *   │ Timeline (queued → running → … → terminal)  │ RelatedJobs      │
 *   │ Params table                                │ (parent / sibs / │
 *   │ Live log stream                             │  retries)        │
 *   │ Design grid                                 │                  │
 *   └─────────────────────────────────────────────┴──────────────────┘
 *
 * Data path:
 *   - 2s polling on `jobs.get` (stops on terminal status). This is the
 *     existing fallback and is preserved verbatim so behaviour matches the
 *     previous implementation.
 *   - Supabase Realtime push subscriptions (inside the log + status badge
 *     children) overlay sub-second updates on top of the polling baseline.
 */

interface JobRecord {
  id: string;
  toolId: string;
  toolVersion?: string | null;
  /** Adapter version resolved from the Tool catalog at submit time. */
  adapterVersion?: string | null;
  /** Container image digest (e.g. "sha256:…") the run pinned to. */
  imageDigest?: string | null;
  status: JobStatus;
  numDesigns: number;
  completedDesigns: number;
  submittedAt: string;
  startedAt?: string;
  finishedAt?: string;
  errorMessage?: string;
  errorCode?: string;
  errorRetryable?: boolean;
  errorCompletedSeeds?: number;
  attempt: number;
  heartbeatAt?: string | null;
  gpuHours?: number | null;
  // `params` is not in JobSummarySchema today, but the server may surface
  // it on this endpoint in a follow-up. Treat as best-effort.
  params?: Record<string, unknown> | null;
  /** Optional per-tool ETA hint emitted by the scheduler. */
  etaSeconds?: number | null;
  /** Optional estimated seconds-per-design from the tool compute profile. */
  estSecondsPerDesign?: number | null;
}

/** Pull a best-effort target label out of a job's params blob. */
function extractTargetLabel(
  params: Record<string, unknown> | null | undefined,
): string | null {
  if (!params || typeof params !== "object") return null;
  const request = (params.request ?? params) as { targetPdb?: unknown };
  const target = request?.targetPdb;
  if (typeof target === "string" && target.length > 0) {
    // Trim S3 noise so the wait screen shows "1abc" not the full URI.
    if (target.startsWith("s3://")) {
      const last = target.split("/").pop();
      return last ?? target;
    }
    return target;
  }
  return null;
}

function fmtAbsTime(iso?: string | null): string {
  if (!iso) return "Not recorded";
  try {
    return new Date(iso).toLocaleString([], {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "Not recorded";
  }
}

function fmtRuntime(startISO?: string | null, endISO?: string | null): string {
  if (!startISO) return "Not recorded";
  const start = new Date(startISO).getTime();
  const end = endISO ? new Date(endISO).getTime() : Date.now();
  const ms = end - start;
  if (!Number.isFinite(ms) || ms < 0) return "Not recorded";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rs = s % 60;
  if (m < 60) return rs ? `${m}m${rs}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm ? `${h}h${rm}m` : `${h}h`;
}

export default function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const jobQuery = trpc.jobs.get.useQuery(
    { id },
    {
      // Existing 2s polling fallback: preserved.
      refetchInterval: (query) => {
        const status = (query.state.data as { status?: JobStatus } | undefined)
          ?.status;
        if (!status) return 2_000;
        return isTerminal(status) ? false : 2_000;
      },
      refetchOnWindowFocus: true,
    },
  );

  const job = jobQuery.data as JobRecord | undefined;

  const toolChain: string[] = useMemo(() => {
    if (!job) return [];
    const fromParams = (job.params as { request?: { toolChain?: string[] } } | null | undefined)
      ?.request?.toolChain;
    if (fromParams && fromParams.length > 0) return fromParams;
    // Fall back to splitting composite tool ids ("rfdiffusion+proteinmpnn+boltz2").
    if (job.toolId.includes("+")) return job.toolId.split("+").map((s) => s.trim());
    return [job.toolId];
  }, [job]);

  /**
   * Every in-flight job uses the live run screen. The parent owns polling
   * and swaps to the results/detail view as soon as the status is terminal.
   */
  const targetLabel = useMemo(
    () => (job ? extractTargetLabel(job.params) : null),
    [job],
  );
  const estimatedTotalSeconds = useMemo<number | null>(() => {
    if (!job) return null;
    if (typeof job.etaSeconds === "number") return job.etaSeconds;
    const per = job.estSecondsPerDesign;
    if (typeof per === "number" && per > 0) {
      return Math.round(per * Math.max(1, job.numDesigns));
    }
    // Without any hint, assume worst-case so the wait screen shows on
    // anything in-flight (the gate downgrades to "show" when null).
    return null;
  }, [job]);
  const showWaitScreen = job
    ? shouldShowWaitScreen({
        status: job.status,
        estimatedTotalSeconds,
      })
    : false;
  const progressPct = job
    ? Math.min(100, Math.round((job.completedDesigns / Math.max(1, job.numDesigns)) * 100))
    : 0;

  return (
    <div className="space-y-10">
      <div>
        <Link
          href="/app/jobs"
          className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          All jobs
        </Link>

        {jobQuery.isLoading && !job ? (
          <JobDetailLoading />
        ) : job && showWaitScreen ? null : job ? (
          <div className="mt-5 space-y-4">
            <div className="flex items-start justify-between gap-6 flex-wrap">
              <div className="space-y-2 min-w-0">
                <p className="text-xs text-graphite-soft" title={job.id}>Run {job.id.slice(0, 8)}</p>
                <h1 className="font-display text-display-md text-ink flex items-baseline gap-2 flex-wrap">
                  <span className="font-display text-[32px] text-ink">{toolLabel(job.toolId)}</span>
                  {job.toolVersion && (
                    <span className="font-mono text-[12px] text-graphite-soft">
                      v{job.toolVersion}
                    </span>
                  )}
                </h1>
                <div className="flex flex-wrap items-center gap-3">
                  <JobStatusBadge status={job.status} />
                  <span className="font-sans text-[13px] text-graphite">
                    <span className="font-mono text-ink">{job.completedDesigns}</span>{" "}
                    of {job.numDesigns} designs
                  </span>
                  {job.attempt > 1 && (
                    <span className="font-sans text-[12px] text-graphite-soft">
                      attempt {job.attempt}
                    </span>
                  )}
                  {targetLabel && (
                    <span className="font-sans text-[12px] text-graphite-soft">
                      target {targetLabel}
                    </span>
                  )}
                </div>
              </div>
              <JobActions
                jobId={job.id}
                toolId={job.toolId}
                status={job.status}
                params={job.params ?? null}
              />
            </div>

            {!showWaitScreen && (
              <>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 pt-4 sm:grid-cols-3">
                  <Stat label="Submitted" value={fmtAbsTime(job.submittedAt)} />
                  <Stat label="Started" value={fmtAbsTime(job.startedAt)} />
                  <Stat
                    label="Runtime"
                    value={fmtRuntime(job.startedAt, job.finishedAt)}
                  />

                </dl>

                {!isTerminal(job.status) && <div>
                  <div className="mb-1.5 flex items-center justify-between font-sans text-[9px] text-graphite-soft">
                    <span>Design progress</span>
                    <span>{progressPct}%</span>
                  </div>
                  <div
                    className="h-1.5 overflow-hidden rounded-full bg-lattice-strong"
                    role="progressbar"
                    aria-label="Design progress"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={progressPct}
                  >
                    <div
                      className={cn(
                        "h-full rounded-full transition-[width] duration-500",
                        job.status === "failed" || job.status === "cancelled"
                          ? "bg-crane"
                          : "bg-ink",
                      )}
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>}
              </>
            )}

            {(job.status === "failed" || job.status === "cancelled") && job.errorMessage && (
              <div
                role="alert"
                className="rounded-lg border border-crane/30 bg-crane-glow/60"
              >
                <div className="flex items-center justify-between border-b border-crane/20 px-4 py-2">
                  <span className="font-sans text-[12px] text-crane-deep">
                    {job.status === "cancelled" ? "Cancelled" : "Failed"}: {job.errorCode ?? "last error"}
                    {job.errorRetryable !== undefined
                      ? job.errorRetryable
                        ? " · retryable"
                        : " · terminal"
                      : ""}
                  </span>
                </div>
                <div className="px-4 py-3">
                  <p className="font-sans text-[13px] leading-relaxed text-crane-deep">
                    {job.errorMessage}
                  </p>
                  {job.errorRetryable !== undefined && (
                    <p className="mt-2 font-sans text-[12px] text-crane-deep/80">
                      {job.errorRetryable
                        ? "Infrastructure failure · retrying is safe"
                        : "Input or runtime failure · review parameters before retrying"}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="mt-5 rounded-lg border border-crane/30 bg-crane-glow px-5 py-4 font-sans text-[13px] text-crane-deep">
            Could not load job: {jobQuery.error?.message ?? "unknown error"}
          </div>
        )}
      </div>

      {job && showWaitScreen && (
        <JobWaitScreen
          jobId={job.id}
          toolId={job.toolId}
          status={job.status}
          numDesigns={job.numDesigns}
          completedDesigns={job.completedDesigns}
          submittedAt={job.submittedAt}
          startedAt={job.startedAt ?? null}
          targetLabel={targetLabel}
          params={job.params}
          syncDelayed={jobQuery.isError}
          estSecondsPerDesign={job.estSecondsPerDesign ?? null}
          initialEtaSeconds={estimatedTotalSeconds}
        />
      )}

      {job && !showWaitScreen && (
        <div className="space-y-8">
          <div className="space-y-10 min-w-0">
            <DesignGrid
              key={`${id}:${job.completedDesigns}:${job.status}`}
              jobId={id}
              toolId={job.toolId}
              total={job.completedDesigns}
              active={!isTerminal(job.status)}
            />

            <details
              className="group overflow-hidden rounded-lg border border-lattice bg-paper-fold/25"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4 marker:hidden hover:bg-paper-fold/45">
                <div>
                  <h2 className="font-display text-[20px] text-ink">Run details & logs</h2>
                  <p className="mt-0.5 font-sans text-[12px] text-graphite-soft">
                    Inputs, software versions, timing, and logs.
                  </p>
                </div>
                <ChevronDown className="h-4 w-4 shrink-0 text-graphite transition-transform group-open:rotate-180" />
              </summary>
              <div className="space-y-8 p-5">
            <JobTimeline
              status={job.status}
              submittedAt={job.submittedAt}
              startedAt={job.startedAt ?? null}
              finishedAt={job.finishedAt ?? null}
              toolChain={toolChain}
            />
                <ProvenanceCard
                  toolId={job.toolId}
                  toolVersion={job.toolVersion ?? null}
                  adapterVersion={job.adapterVersion ?? null}
                  imageDigest={job.imageDigest && !/^sha256:0+$/.test(job.imageDigest) ? job.imageDigest : null}
                />

                <JobParamsTable
                  params={job.params ?? null}
                  toolChainFallback={toolChain}
                />

                <JobLogStream jobId={job.id} />
              </div>
            </details>
          </div>

          <aside className="space-y-6">
            <RelatedJobs jobId={job.id} params={job.params ?? null} />
          </aside>
        </div>
      )}
    </div>
  );
}

function JobDetailLoading() {
  return (
    <div
      className="mt-5 space-y-5 bg-paper/70 p-5 sm:p-7"
      role="status"
      aria-label="Loading run status"
    >
      <div className="flex items-center gap-3 font-sans text-[12px] text-graphite-soft">
        <span
          className="h-2 w-2 rounded-full bg-crane motion-safe:animate-pulse"
          aria-hidden
        />
        Connecting to your run…
      </div>
      <div className="h-10 w-64 max-w-full animate-pulse rounded-xl bg-paper-fold" />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <div
            key={index}
            className="h-12 animate-pulse"
          />
        ))}
      </div>
    </div>
  );
}

function isTerminal(status: JobStatus): boolean {
  return (
    status === "succeeded" ||
    status === "partial" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "purged"
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <dt className="font-sans text-[12px] text-graphite-soft">
        {label}
      </dt>
      <dd className="font-mono text-[12px] text-ink">{value}</dd>
    </div>
  );
}

/** Show the leading 12 chars of an image digest's hash, keeping the algo prefix. */
function shortDigest(digest: string): string {
  const [algo, hash] = digest.includes(":")
    ? (digest.split(":") as [string, string])
    : ["", digest];
  const head = (hash ?? "").slice(0, 12);
  return algo ? `${algo}:${head}…` : `${head}…`;
}

/**
 * Reproducibility provenance: the exact tool version, adapter version, and
 * container image digest a result was produced with. A PI cannot publish or
 * reproduce a design without these, so they are surfaced verbatim (full
 * digest on hover + one-click copy).
 */
function ProvenanceCard({
  toolId,
  toolVersion,
  adapterVersion,
  imageDigest,
}: {
  toolId: string;
  toolVersion: string | null;
  adapterVersion: string | null;
  imageDigest: string | null;
}) {
  const [copied, setCopied] = useState(false);

  function copyDigest() {
    if (!imageDigest) return;
    void navigator.clipboard?.writeText(imageDigest).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <section className="p-5">
      <h2 className="font-sans text-[12px] text-graphite">
        Provenance
      </h2>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 font-sans text-[13px]">
        <dt className="text-graphite-soft">Tool</dt>
        <dd className="font-mono text-ink truncate" title={toolId}>
          {toolId}
        </dd>

        <dt className="text-graphite-soft">Model version</dt>
        <dd className="font-mono text-ink tabular-nums">
          {toolVersion ?? "Not recorded"}
        </dd>

        <dt className="text-graphite-soft">Adapter version</dt>
        <dd className="font-mono text-ink tabular-nums">
          {adapterVersion ?? "Not recorded"}
        </dd>

        <dt className="text-graphite-soft">Image digest</dt>
        <dd className="font-mono text-ink min-w-0">
          {imageDigest ? (
            <button
              type="button"
              onClick={copyDigest}
              title={imageDigest}
              aria-label="Copy full image digest"
              className="inline-flex items-center gap-1.5 max-w-full text-ink hover:text-crane-deep transition-colors"
            >
              <span className="truncate">{shortDigest(imageDigest)}</span>
              {copied ? (
                <Check className="w-3 h-3 shrink-0 text-crane-deep" />
              ) : (
                <Copy className="w-3 h-3 shrink-0 text-graphite-soft" />
              )}
            </button>
          ) : (
            "Not recorded"
          )}
        </dd>
      </dl>
    </section>
  );
}
