"use client";

import { type ReactNode } from "react";
import { ArrowLeft, Check, Loader2 } from "lucide-react";
import { Button } from "@papercrane/ui";
import { cn } from "@/lib/utils";

export interface WizardStep {
  id: string;
  label: string;
}

export interface JobWizardProps {
  steps: WizardStep[];
  currentIndex: number;
  onBack: () => void;
  /** On the last step this is the submit action. */
  onNext: () => void;
  /** Primary button label. Defaults to "Next →"; integration passes "Run" on the last step. */
  nextLabel?: string;
  nextDisabled?: boolean;
  /** Shows a spinner on the primary button. */
  busy?: boolean;
  hideNavigation?: boolean;
  /** The active step body. */
  children: ReactNode;
}

/**
 * Presentational stepper shell for the job-submission wizard.
 *
 * Purely presentational: holds NO wizard state. The parent owns `currentIndex`
 * and the Back/Next handlers. Renders a numbered progress bar (completed steps
 * carry a check, the current step is crane-colored, upcoming steps are muted),
 * the active step body, and a footer with Back (hidden on step 0) plus a primary
 * Next/Run button.
 */
export function JobWizard({
  steps,
  currentIndex,
  onBack,
  onNext,
  nextLabel = "Next →",
  nextDisabled = false,
  busy = false,
  hideNavigation = false,
  children,
}: JobWizardProps): JSX.Element {
  const isFirst = currentIndex <= 0;
  const isLast = currentIndex >= steps.length - 1;

  return (
    <div className="flex flex-col gap-8" data-testid="e2e-job-wizard">
      {/* Progress bar */}
      <nav aria-label="Wizard progress" className="w-full">
        <ol className="flex w-full flex-wrap items-center gap-x-8 gap-y-3">
          {steps.map((step, index) => {
            const isComplete = index < currentIndex;
            const isCurrent = index === currentIndex;

            return (
              <li key={step.id} className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden="true"
                  className={cn(
                    "flex h-7 w-5 shrink-0 items-center justify-center text-sm font-sans transition-colors duration-200",
                    isCurrent && "text-crane",
                    isComplete && "text-crane",
                    !isCurrent && !isComplete && "text-graphite-soft",
                  )}
                >
                  {isComplete ? (
                    <Check className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    index + 1
                  )}
                </span>
                <span
                  className={cn(
                    "truncate font-sans text-sm tracking-tight transition-colors duration-200",
                    isCurrent && "font-medium text-ink",
                    isComplete && "text-graphite",
                    !isCurrent && !isComplete && "text-graphite-soft",
                  )}
                  aria-current={isCurrent ? "step" : undefined}
                >
                  {step.label}
                </span>
              </li>
            );
          })}
        </ol>
      </nav>

      {/* Active step body */}
      <div key={currentIndex} className="relative min-h-[320px] py-5">
        <div
          className={cn(
            "transition-opacity duration-150",
            busy && "pointer-events-none opacity-20",
          )}
          aria-hidden={busy || undefined}
        >
          {children}
        </div>

        {busy && (
          <div
            role="status"
            aria-live="assertive"
            className="absolute inset-0 z-10 flex items-center justify-center bg-paper/90 px-6"
          >
            <div className="w-full max-w-md text-center">
              <span className="relative mx-auto flex h-14 w-14 items-center justify-center rounded-full border border-crane/25 bg-crane-glow text-crane-deep">
                <Loader2
                  className="h-5 w-5 motion-safe:animate-spin"
                  aria-hidden
                />
              </span>
              <p className="mt-5 font-display text-[28px] leading-tight text-ink">
                Submitting your run
              </p>
              <p className="mx-auto mt-2 max-w-sm font-sans text-[13px] leading-relaxed text-graphite">
                Validating the target and reserving compute. Live progress will
                open automatically.
              </p>
              <div className="mx-auto mt-6 h-1.5 max-w-xs overflow-hidden rounded-full bg-lattice-strong">
                <span className="block h-full w-2/3 rounded-full bg-crane motion-safe:animate-pulse" />
              </div>
              <p className="mt-3 font-sans text-[9px] text-graphite-soft">
                Keep this tab open for a few seconds
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      {!hideNavigation && <div className="flex items-center justify-between gap-4">
        <div>
          {!isFirst ? (
            <Button
              variant="ghost"
              onClick={onBack}
              disabled={busy}
              leftIcon={<ArrowLeft className="h-4 w-4" />}
            >
              Back
            </Button>
          ) : null}
        </div>
        <div className="flex items-center gap-4">
          {isLast && (
            <p className="hidden max-w-[190px] text-right font-sans text-[11px] leading-snug text-graphite-soft sm:block">
              {busy
                ? "Creating the job and opening live progress…"
                : "You’ll see live progress as soon as the run is queued."}
            </p>
          )}
          <Button
            variant="primary"
            size={isLast ? "lg" : "md"}
            onClick={onNext}
            disabled={nextDisabled}
            loading={busy}
            className={cn(
              isLast && "min-w-[168px] rounded-xl",
              busy && "disabled:opacity-100",
            )}
          >
            {busy ? "Submitting…" : nextLabel}
          </Button>
        </div>
      </div>}
    </div>
  );
}
