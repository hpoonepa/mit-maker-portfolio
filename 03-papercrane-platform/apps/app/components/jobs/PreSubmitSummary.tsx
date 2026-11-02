"use client";

import { AlertTriangle, Wallet } from "lucide-react";

export interface PreSubmitCost {
  loading: boolean;
  /** True when the estimate could not be fetched: say so, don't guess. */
  unavailable: boolean;
  estimatedUsd?: number;
  capUsd?: number;
  remainingUsd?: number;
  wouldExceed?: boolean;
  /** Which tool the dollar figure covers (relevant for multi-tool runs). */
  forToolName?: string;
  /** True when more tools will run than the estimate covers. */
  partial?: boolean;
}

export interface PreSubmitSummaryProps {
  /** "designs" | "predictions" | "runs": the user-facing noun. */
  runNoun: string;
  cost: PreSubmitCost;
}

function usd(n: number): string {
  return `$${n.toFixed(2)}`;
}

/**
 * "Here's exactly what happens when you press Run."
 *
 * Sits directly above the submit button so nobody launches GPU work without
 * knowing which tools run, roughly how long it takes, what it costs, and where
 * the spend cap sits. The cap is stated even when the run is comfortably under
 * it: a cap rejection should never be the first time a user hears the cap
 * exists.
 */
export function PreSubmitSummary({
  runNoun,
  cost,
}: PreSubmitSummaryProps) {
  return (
    <section
      data-testid="e2e-pre-submit-summary"
      className="py-5"
    >
      <h3 className="font-display text-[16px] tracking-tight text-ink">
        GPU cost
      </h3>

      <ul className="mt-3 space-y-3">
        <Line icon={<Wallet className="h-3.5 w-3.5" />}>
          {cost.loading ? (
            <>Checking the cost against your GPU spend cap…</>
          ) : cost.unavailable ||
            cost.estimatedUsd === undefined ||
            cost.capUsd === undefined ? (
            <>
              Cost estimate unavailable. Your GPU spend cap still applies.
            </>
          ) : (
            <>
              Estimated GPU cost{" "}
              <span className="font-medium text-ink">
                {usd(cost.estimatedUsd)}
              </span>
              {cost.partial && cost.forToolName ? (
                <> for {cost.forToolName} alone (the other tools add to it)</>
              ) : null}
              , against a {usd(cost.capUsd)} cap
              {cost.remainingUsd !== undefined ? (
                <> with {usd(cost.remainingUsd)} left</>
              ) : null}
              . Runs over your cap are blocked.
            </>
          )}
        </Line>
      </ul>

      {cost.wouldExceed && (
        <p
          role="alert"
          data-testid="e2e-pre-submit-cap-block"
          className="mt-4 flex items-start gap-2 rounded-xl bg-crane-glow px-4 py-3 font-sans text-[13px] leading-relaxed text-crane-deep"
        >
          <AlertTriangle
            className="mt-[2px] h-3.5 w-3.5 shrink-0"
            aria-hidden="true"
          />
          <span>
            This run would cross your GPU spend cap, so we can&apos;t submit it.
            Lower the number of {runNoun}, or ask us to raise the cap.
          </span>
        </p>
      )}
    </section>
  );
}

function Line({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <li className="flex items-start gap-2.5 font-sans text-[13px] leading-relaxed text-graphite">
      <span
        aria-hidden="true"
        className="mt-[2px] inline-flex h-6 w-6 shrink-0 items-center justify-center text-graphite-soft"
      >
        {icon}
      </span>
      <span className="min-w-0">{children}</span>
    </li>
  );
}
