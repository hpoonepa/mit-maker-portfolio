"use client";

import { Loader2, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import { EXAMPLE_JOB, exampleHotspotLabel } from "@/lib/jobs/exampleJob";

export interface ExampleRunCardProps {
  /** False while the catalog is still loading, or if the tool isn't runnable. */
  ready: boolean;
  /** True while the tool catalog is in flight. */
  loadingCatalog?: boolean;
  /** Honest reason the button is unavailable: required whenever !ready. */
  unavailableReason?: string;
  /**
   * A failed submit attempt, already rewritten in plain language. Rendered
   * whether or not the button is still enabled, so a retryable failure is
   * never silent.
   */
  errorMessage?: string | null;
  /** Dollar estimate from `jobs.previewCost`, when it resolved. */
  costUsd?: number;
  capUsd?: number;
  remainingUsd?: number;
  wouldExceed?: boolean;
  /** True while the cost estimate is in flight. */
  costLoading?: boolean;
  /** Rough runtime, already formatted (e.g. "12m"). */
  etaLabel?: string;
  /** True while the demo job is being submitted. */
  busy?: boolean;
  onRun: () => void;
  /** Secondary path: jump into manual configuration. */
  onConfigureManually?: () => void;
}

function usd(n: number): string {
  return `$${n.toFixed(2)}`;
}

/**
 * The primary action on an otherwise-blank New Job wizard.
 *
 * A first-time viewer should never have to decide what a "target" is before
 * seeing the product work. This card submits a complete, known-good job -
 * BindCraft against PD-L1 (5O45): in a single click, and says up front
 * exactly what will run, roughly how long it takes, and what it costs against
 * the GPU spend cap. Manual configuration stays available underneath.
 */
export function ExampleRunCard({
  ready,
  loadingCatalog = false,
  unavailableReason,
  errorMessage,
  costUsd,
  capUsd,
  remainingUsd,
  wouldExceed = false,
  costLoading = false,
  etaLabel,
  busy = false,
  onRun,
  onConfigureManually,
}: ExampleRunCardProps) {
  const blocked = !ready || wouldExceed;
  const blockedReason = wouldExceed
    ? `This would push you past your ${capUsd !== undefined ? usd(capUsd) : "GPU"} spend cap${
        remainingUsd !== undefined ? `: ${usd(remainingUsd)} left` : ""
      }.`
    : unavailableReason;

  return (
    <section
      data-testid="e2e-example-run-card"
      className="bg-paper p-6 sm:p-7"
    >
      <p className="font-sans text-[12px] text-graphite-soft">
        Preset job
      </p>

      <h2 className="mt-3 font-display text-[26px] leading-tight tracking-tight text-ink sm:text-[30px]">
        Run the example
      </h2>
      <p className="mt-2 max-w-xl font-sans text-[14px] leading-relaxed text-graphite">
        Submit a preset {EXAMPLE_JOB.toolName} job with {EXAMPLE_JOB.numDesigns}{" "}
        designs against {EXAMPLE_JOB.targetName}. {EXAMPLE_JOB.targetBlurb}
      </p>

      <dl className="mt-5 grid gap-x-8 gap-y-2 sm:grid-cols-2">
        <Row label="Tool" value={EXAMPLE_JOB.toolName} />
        <Row
          label="Target"
          value={`${EXAMPLE_JOB.targetName} · ${EXAMPLE_JOB.targetPdb} chain ${EXAMPLE_JOB.targetChain}`}
        />
        <Row label="Hotspots" value={exampleHotspotLabel()} />
        <Row
          label="Designs"
          value={`${EXAMPLE_JOB.numDesigns} binders${etaLabel ? ` · ~${etaLabel}` : ""}`}
        />
      </dl>

      <p
        data-testid="e2e-example-cost"
        className="mt-4 font-sans text-[13px] leading-relaxed text-graphite"
      >
        {costLoading ? (
          "Checking cost against your GPU spend cap…"
        ) : costUsd !== undefined && capUsd !== undefined ? (
          <>
            Estimated GPU cost{" "}
            <span className="font-medium text-ink">{usd(costUsd)}</span>, drawn
            from your {usd(capUsd)} cap
            {remainingUsd !== undefined ? ` (${usd(remainingUsd)} left)` : ""}.
            The job will not start if it would exceed the cap.
          </>
        ) : (
          "Cost estimate unavailable right now. The run is still capped by your GPU spend limit."
        )}
      </p>

      <div className="mt-6 flex flex-wrap items-center gap-4">
        <button
          type="button"
          onClick={onRun}
          disabled={blocked || busy || loadingCatalog}
          data-testid="e2e-example-run-button"
          className={cn(
            "inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md bg-crane-deep px-5",
            "font-sans text-[14px] font-medium text-paper transition-colors",
            "hover:bg-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Play className="h-4 w-4" aria-hidden="true" />
          )}
          {busy ? "Submitting…" : "Run the example"}
        </button>

        {onConfigureManually && (
          <button
            type="button"
            onClick={onConfigureManually}
            disabled={busy}
            data-testid="e2e-example-configure-manually"
            className="font-sans text-[13px] text-graphite underline underline-offset-4 transition-colors hover:text-ink disabled:opacity-50"
          >
            Or set up my own job
          </button>
        )}
      </div>

      {errorMessage && (
        <p
          role="alert"
          data-testid="e2e-example-error"
          className="mt-3 font-sans text-[12.5px] leading-relaxed text-crane-deep"
        >
          {errorMessage} You can try again, or set up a job yourself below.
        </p>
      )}
      {loadingCatalog && (
        <p className="mt-3 font-sans text-[12.5px] text-graphite-soft">
          Loading the tool catalog…
        </p>
      )}
      {!loadingCatalog && blocked && blockedReason && (
        <p
          role="status"
          data-testid="e2e-example-blocked"
          className="mt-3 font-sans text-[12.5px] text-crane-deep"
        >
          {blockedReason}
        </p>
      )}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-3 py-1.5">
      <dt className="w-[86px] shrink-0 font-sans text-[12px] text-graphite-soft">
        {label}
      </dt>
      <dd className="min-w-0 font-sans text-[13px] text-ink">{value}</dd>
    </div>
  );
}
