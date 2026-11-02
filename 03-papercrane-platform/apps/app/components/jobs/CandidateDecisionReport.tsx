"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Circle,
  Download,
  FlaskConical,
  Loader2,
  RefreshCw,
  ScanSearch,
  ShieldCheck,
} from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { cn } from "@/lib/utils";

export function CandidateDecisionReport({
  jobId,
  active = false,
}: {
  jobId: string;
  active?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [requested, setRequested] = useState(active);
  const [phaseIndex, setPhaseIndex] = useState(0);
  const query = trpc.designs.decisionReport.useQuery(
    { jobId, limit: 500 },
    {
      enabled: requested,
      staleTime: 0,
      refetchOnWindowFocus: requested,
      refetchInterval: requested && active ? 5_000 : false,
    },
  );
  const report = query.data;

  useEffect(() => {
    if (active) setRequested(true);
  }, [active]);

  useEffect(() => {
    if (!query.isFetching) return;
    setPhaseIndex(0);
    const interval = window.setInterval(() => {
      setPhaseIndex((current) =>
        Math.min(current + 1, SELECTOR_STAGES.length - 1),
      );
    }, 650);
    return () => window.clearInterval(interval);
  }, [query.isFetching]);

  function runSelection() {
    setExpanded(false);
    if (requested) {
      void query.refetch();
    } else {
      setRequested(true);
    }
  }

  if (!requested) {
    return <BinderSelectorLaunch onRun={runSelection} />;
  }

  if ((query.isLoading || query.isFetching) && !report) {
    return <BinderSelectorRunning phaseIndex={phaseIndex} />;
  }
  if (query.isError || !report) {
    return (
      <section className="rounded-lg border border-crane/25 bg-crane-glow/40 p-5">
        <h2 className="font-sans text-[12px] text-graphite">
          Candidate decision report
        </h2>
        <p className="mt-3 font-sans text-[13px] text-graphite-soft">
          Report unavailable: {query.error?.message ?? "no data"}
        </p>
        <button
          type="button"
          onClick={runSelection}
          className="mt-4 rounded-md border border-crane/30 bg-paper px-3 py-1.5 font-sans text-[12px] text-crane-deep hover:border-crane"
        >
          Run again
        </button>
      </section>
    );
  }

  const visibleCandidates = expanded
    ? report.candidates
    : report.candidates.slice(0, 8);
  const topCandidate = report.candidates[0];
  return (
    <section
      aria-busy={query.isFetching}
      className="overflow-hidden bg-paper"
    >
      <div className="grid gap-6 px-5 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_240px]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <ScanSearch className="h-4 w-4 text-crane-deep" aria-hidden />
              <span className="font-sans text-[9px] text-crane-deep">
                Candidate scoring
              </span>
            </div>
            <span
              role="status"
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-sans text-[9px]",
                query.isFetching
                  ? "border-crane/30 bg-crane-glow text-crane-deep"
                  : "border-lattice-strong bg-paper/80 text-graphite",
              )}
            >
              {query.isFetching ? (
                <Loader2
                  className="h-3 w-3 motion-safe:animate-spin"
                  aria-hidden
                />
              ) : (
                <Check className="h-3 w-3" aria-hidden />
              )}
              {query.isFetching ? "Updating selection" : "Selection ready"}
            </span>
          </div>
          <h2 className="mt-2 font-display text-[28px] leading-tight text-ink">
            Binder selection report
          </h2>
          <p className="mt-2 max-w-2xl font-sans text-[13px] leading-relaxed text-graphite">
            A computational shortlist based on available metrics, coverage, and
            provenance. It is not a binding prediction.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <DownloadButton
              label="Report JSON"
              onClick={() =>
                saveFile(
                  `papercrane-${jobId.slice(0, 8)}-decision-report.json`,
                  JSON.stringify(report, null, 2),
                  "application/json",
                )
              }
            />
            <DownloadButton
              label="Candidates CSV"
              onClick={() =>
                saveFile(
                  `papercrane-${jobId.slice(0, 8)}-candidates.csv`,
                  reportCsv(report.candidates),
                  "text/csv;charset=utf-8",
                )
              }
            />
            <button
              type="button"
              onClick={runSelection}
              disabled={query.isFetching}
              className="inline-flex items-center gap-1.5 rounded-md border border-lattice-strong bg-paper px-3 py-1.5 font-sans text-[12px] text-ink transition-colors hover:border-ink hover:bg-paper-fold disabled:cursor-wait disabled:opacity-60"
            >
              <RefreshCw
                className={cn(
                  "h-3 w-3",
                  query.isFetching && "motion-safe:animate-spin",
                )}
                aria-hidden
              />
              {query.isFetching ? "Running" : "Run again"}
            </button>
            <span className="font-mono text-[9px] text-graphite-soft">
              {report.methodology.scorerVersion}
            </span>
          </div>
        </div>

        {topCandidate ? (
          <Link
            href={`/app/designs/${topCandidate.designId}`}
            className="group rounded-lg border border-lattice-strong bg-paper p-4 transition-colors hover:border-ink"
          >
            <div className="flex items-center justify-between font-sans text-[9px] text-graphite-soft">
              <span>Lead candidate</span>
              <ArrowUpRight className="h-3.5 w-3.5" />
            </div>
            <div className="mt-3 flex items-end justify-between gap-3">
              <div>
                <div className="font-display text-[23px] leading-none text-ink">
                  Seed {topCandidate.seed}
                </div>
                <div className="mt-2">
                  <DecisionBadge decision={topCandidate.recommendation} />
                </div>
              </div>
              <div className="text-right">
                <div className="font-display text-[42px] leading-none tabular-nums text-ink">
                  {scorePercent(topCandidate.metaScore.score)}
                </div>
                <div className="mt-1 font-sans text-[8px] text-graphite-soft">
                  Meta / 100
                </div>
              </div>
            </div>
          </Link>
        ) : (
          <div className="p-4 font-sans text-[12px] text-graphite-soft">
            The lead candidate will appear after the first design is persisted.
          </div>
        )}
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-5">
        <SummaryStat
          label={report.summary.truncated ? "Evaluated / total" : "Evaluated"}
          value={
            report.summary.truncated
              ? `${report.summary.candidatesEvaluated}/${report.summary.candidatesAvailable}`
              : report.summary.candidatesEvaluated
          }
        />
        <SummaryStat
          label="Advance"
          value={report.summary.advance}
          tone="good"
        />
        <SummaryStat label="Review" value={report.summary.review} />
        <SummaryStat label="Hold" value={report.summary.hold} />
        <SummaryStat
          label="Missing data"
          value={report.summary.insufficientData}
        />
      </dl>

      {visibleCandidates.length === 0 ? (
        <div className="px-5 py-10 text-center">
          <p className="font-display text-[20px] text-ink">
            No persisted candidates yet.
          </p>
          <p className="mt-1 font-sans text-[13px] text-graphite-soft">
            This report refreshes automatically while the job is active.
          </p>
        </div>
      ) : (
        <>
          <div className="divide-y divide-lattice md:hidden">
            {visibleCandidates.map((candidate) => (
              <article key={candidate.designId} className="px-5 py-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="font-sans text-[9px] text-graphite-soft">
                      Rank {candidate.decisionRank} · {candidate.confidence}{" "}
                      confidence
                    </p>
                    <Link
                      href={`/app/designs/${candidate.designId}`}
                      className="mt-1 inline-flex items-center gap-1 font-display text-[21px] text-ink hover:text-crane-deep"
                    >
                      Seed {candidate.seed}
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </Link>
                    <div className="mt-2">
                      <DecisionBadge decision={candidate.recommendation} />
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-display text-[34px] leading-none tabular-nums text-ink">
                      {scorePercent(candidate.metaScore.score)}
                    </div>
                    <div className="mt-1 font-sans text-[8px] text-graphite-soft">
                      Meta / 100
                    </div>
                  </div>
                </div>
                <CoverageBar coverage={candidate.metaScore.coverage} />
                <p className="mt-3 font-sans text-[12px] leading-relaxed text-graphite">
                  {evidenceLabel(candidate)}
                </p>
              </article>
            ))}
          </div>

          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[760px] border-collapse text-left">
              <thead>
                <tr className="font-sans text-[9px] text-graphite-soft">
                  <th className="px-5 py-2.5 font-normal">Rank</th>
                  <th className="px-3 py-2.5 font-normal">Candidate</th>
                  <th className="px-3 py-2.5 font-normal">Decision</th>
                  <th className="px-3 py-2.5 font-normal">Meta-score</th>
                  <th className="px-3 py-2.5 font-normal">Confidence</th>
                  <th className="px-5 py-2.5 font-normal">Top evidence</th>
                </tr>
              </thead>
              <tbody>
                {visibleCandidates.map((candidate) => (
                  <tr
                    key={candidate.designId}
                    className="transition-colors last: motion-safe:animate-fade-in"
                  >
                    <td className="px-5 py-3 font-mono text-[12px] text-graphite">
                      #{String(candidate.decisionRank).padStart(2, "0")}
                    </td>
                    <td className="px-3 py-3">
                      <Link
                        href={`/app/designs/${candidate.designId}`}
                        className="font-mono text-[12px] text-ink hover:text-crane-deep"
                      >
                        seed {candidate.seed}
                      </Link>
                      <div className="mt-0.5 font-sans text-[8px] text-graphite-soft">
                        {candidate.provenance}
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <DecisionBadge decision={candidate.recommendation} />
                    </td>
                    <td className="w-36 px-3 py-3">
                      <div className="flex items-center justify-between font-mono text-[11px] tabular-nums text-ink">
                        <span>{scorePercent(candidate.metaScore.score)}</span>
                        <span className="text-[9px] text-graphite-soft">
                          {Math.round(candidate.metaScore.coverage * 100)}% cov.
                        </span>
                      </div>
                      <CoverageBar
                        coverage={candidate.metaScore.coverage}
                        compact
                      />
                    </td>
                    <td className="px-3 py-3 font-sans text-[12px] text-graphite">
                      {candidate.confidence}
                    </td>
                    <td className="max-w-xs px-5 py-3 font-sans text-[12px] text-graphite">
                      {evidenceLabel(candidate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {report.candidates.length > 8 && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="flex w-full items-center justify-center gap-2 border-t border-lattice px-5 py-3 font-sans text-[12px] text-graphite hover:bg-paper-fold/35 hover:text-ink"
        >
          {expanded
            ? "Show top 8"
            : `Show all ${report.candidates.length} candidates`}
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 transition-transform",
              expanded && "rotate-180",
            )}
          />
        </button>
      )}

      <div className="grid sm:grid-cols-2">
        <div className="flex gap-3 px-5 py-4 sm: sm:">
          <ShieldCheck
            className="mt-0.5 h-4 w-4 shrink-0 text-ink"
            aria-hidden
          />
          <div>
            <p className="font-sans text-[9px] text-graphite-soft">
              Recommended next step
            </p>
            <p className="mt-1 font-sans text-[12px] leading-relaxed text-graphite">
              {report.summary.nextStep}
            </p>
          </div>
        </div>
        <div className="flex gap-3 px-5 py-4">
          <FlaskConical
            className="mt-0.5 h-4 w-4 shrink-0 text-crane-deep"
            aria-hidden
          />
          <div>
            <p className="font-sans text-[9px] text-graphite-soft">
              Evidence boundary
            </p>
            <p className="mt-1 font-sans text-[12px] leading-relaxed text-graphite">
              No wet-lab evidence. This report does not establish binding,
              specificity, expression, stability, or safety.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

const SELECTOR_STAGES = [
  {
    title: "Reading candidate metrics",
    detail: "Collecting supported interface and developability evidence.",
  },
  {
    title: "Applying the versioned prior",
    detail: "Matching the target prior or the labeled metric fallback.",
  },
  {
    title: "Building the shortlist",
    detail: "Ranking by score, coverage, and output provenance.",
  },
] as const;

function BinderSelectorLaunch({ onRun }: { onRun: () => void }) {
  return (
    <section className="bg-paper px-5 py-6 sm:px-7 sm:py-8">
      <div className="grid items-center gap-7 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="max-w-2xl">
          <div className="flex items-center gap-2 text-crane-deep">
            <ScanSearch className="h-4 w-4" aria-hidden />
            <span className="font-sans text-[9px]">
              Candidate scoring
            </span>
          </div>
          <h2 className="mt-3 font-display text-[30px] leading-tight text-ink sm:text-[34px]">
            Rank this job&apos;s candidates
          </h2>
          <p className="mt-3 max-w-xl font-sans text-[13px] leading-6 text-graphite">
            Score available candidates using the job&apos;s computational
            metrics, evidence coverage, and provenance. The scorer version is
            included in the report.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {[
              "Target-aware scoring",
              "Coverage checked",
              "Provenance guarded",
            ].map((label) => (
              <span
                key={label}
                className="rounded-full border border-lattice bg-paper-fold/55 px-3 py-1.5 font-sans text-[9px] text-graphite"
              >
                {label}
              </span>
            ))}
          </div>
        </div>

        <div className="flex flex-col items-start gap-3 lg:items-end">
          <button
            type="button"
            onClick={onRun}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-ink px-5 font-sans text-[13px] font-medium text-paper transition-colors hover:bg-crane-deep"
          >
            <ScanSearch className="h-4 w-4" aria-hidden />
            Score candidates
          </button>
          <p className="max-w-xs font-sans text-[11px] leading-5 text-graphite-soft lg:text-right">
            Computational triage only. Final candidates still require manual and
            experimental review.
          </p>
        </div>
      </div>
    </section>
  );
}

function BinderSelectorRunning({ phaseIndex }: { phaseIndex: number }) {
  const progress = [28, 62, 88][phaseIndex] ?? 28;
  return (
    <section
      aria-busy="true"
      aria-live="polite"
      aria-label="Binder selector running"
      className="overflow-hidden bg-paper px-5 py-7 sm:px-8 sm:py-9"
    >
      <div className="grid items-center gap-6 md:grid-cols-[80px_minmax(0,1fr)]">
        <div
          className="grid h-16 w-16 place-items-center rounded-md"
          aria-hidden
        >
          <Loader2 className="h-6 w-6 text-crane-deep motion-safe:animate-spin" />
        </div>

        <div className="min-w-0">
          <div className="flex items-center gap-2 text-crane-deep">
            <span className="font-sans text-[9px]">
              Scoring candidates
            </span>
          </div>
          <h2 className="mt-2 font-display text-[28px] text-ink">
            Computing candidate scores
          </h2>
          <p className="mt-2 font-sans text-[13px] leading-5 text-graphite">
            This report uses the candidate metrics saved for this job.
          </p>
          <p className="sr-only">
            Current step: {SELECTOR_STAGES[phaseIndex]?.title}
          </p>

          <div
            role="progressbar"
            aria-label="Binder selection progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
            className="mt-5 h-1.5 overflow-hidden rounded-full bg-lattice"
          >
            <div
              className="h-full rounded-full bg-crane-deep transition-[width] duration-500 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>

          <ol className="mt-5 grid gap-3 sm:grid-cols-3">
            {SELECTOR_STAGES.map((stage, index) => {
              const complete = index < phaseIndex;
              const current = index === phaseIndex;
              return (
                <li
                  key={stage.title}
                  className={cn(
                    "flex gap-2.5",
                    index > phaseIndex && "opacity-45",
                  )}
                >
                  <span className="mt-0.5 shrink-0 text-crane-deep">
                    {complete ? (
                      <Check className="h-3.5 w-3.5" aria-hidden />
                    ) : current ? (
                      <Loader2
                        className="h-3.5 w-3.5 motion-safe:animate-spin"
                        aria-hidden
                      />
                    ) : (
                      <Circle className="h-3.5 w-3.5" aria-hidden />
                    )}
                  </span>
                  <div>
                    <p className="font-sans text-[11px] font-medium leading-4 text-ink">
                      {stage.title}
                    </p>
                    <p className="mt-0.5 hidden font-sans text-[10px] leading-4 text-graphite-soft lg:block">
                      {stage.detail}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}

function SummaryStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "good";
}) {
  return (
    <div className="px-4 py-3 last:col-span-2 sm: sm:last:col-span-1 sm:last:">
      <dt className="font-sans text-[9px] text-graphite-soft">
        {label}
      </dt>
      <dd
        className={cn(
          "mt-1 font-mono text-[18px] text-ink",
          tone === "good" && "text-crane-deep",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

function DecisionBadge({ decision }: { decision: string }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-2 py-0.5 font-sans text-[9px]",
        decision === "advance"
          ? "border-ink bg-ink text-paper"
          : decision === "review"
            ? "border-crane/35 bg-crane-glow text-crane-deep"
            : decision === "insufficient_data"
              ? "border-dashed border-lattice-strong bg-paper text-graphite-soft"
              : "border-lattice-strong bg-paper-fold text-graphite",
      )}
    >
      {decision.replace("_", " ")}
    </span>
  );
}

function CoverageBar({
  coverage,
  compact = false,
}: {
  coverage: number;
  compact?: boolean;
}) {
  const pct = Math.round(coverage * 100);
  return (
    <div className={compact ? "mt-1" : "mt-4"}>
      {!compact && (
        <div className="mb-1.5 flex items-center justify-between font-sans text-[8px] text-graphite-soft">
          <span>Evidence coverage</span>
          <span>{pct}%</span>
        </div>
      )}
      <div
        className={cn(
          "overflow-hidden rounded-full bg-lattice-strong",
          compact ? "h-1" : "h-1.5",
        )}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-700 ease-out",
            pct >= 60 ? "bg-ink" : "bg-crane",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function DownloadButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-md border border-lattice-strong bg-paper px-3 py-1.5 font-sans text-[12px] text-ink transition-colors hover:border-ink hover:bg-paper-fold"
    >
      <Download className="h-3 w-3" />
      {label}
    </button>
  );
}

type Candidate = {
  decisionRank: number;
  designId: string;
  seed: number;
  recommendation: string;
  confidence: string;
  provenance: string;
  reason: string;
  metaScore: {
    score: number | null;
    coverage: number;
    version: string;
    contributions: Array<{ label: string }>;
  };
};

function scorePercent(score: number | null): number | string {
  return score === null ? "N/A" : Math.round(score * 100);
}

function evidenceLabel(candidate: Candidate): string {
  const labels = candidate.metaScore.contributions
    .slice(0, 2)
    .map((item) => item.label);
  return labels.length > 0
    ? labels.join(" · ")
    : "Insufficient supported metrics";
}

function reportCsv(candidates: Candidate[]): string {
  const header = [
    "decision_rank",
    "design_id",
    "seed",
    "recommendation",
    "confidence",
    "meta_score",
    "coverage",
    "scorer_version",
    "provenance",
    "reason",
  ];
  const rows = candidates.map((candidate) => [
    candidate.decisionRank,
    candidate.designId,
    candidate.seed,
    candidate.recommendation,
    candidate.confidence,
    candidate.metaScore.score ?? "",
    candidate.metaScore.coverage,
    candidate.metaScore.version,
    candidate.provenance,
    candidate.reason,
  ]);
  return [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\n");
}

function csvCell(value: unknown): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function saveFile(filename: string, contents: string, type: string) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
