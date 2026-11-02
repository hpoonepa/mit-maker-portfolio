/**
 * Onboarding progress bar: one segment per wizard step, current highlighted.
 *
 * Visual language
 * ---------------
 * Lattice-coloured inactive track (`bg-lattice`), crane-coloured active
 * segment (`bg-crane`). A short label sits under each segment, small enough
 * to not compete with the step's main heading.
 *
 * Why segments (not a filled bar)
 * -------------------------------
 * A filled bar communicates "% done" but hides structure. Segments let the
 * user count "3 more things to do" at a glance, which matters more for a
 * 5-minute-to-value flow than smoothness.
 *
 * Wave 8: segments now come from the canonical wizard `WIZARD_STEPS` set
 * in `lib/onboarding-state.ts`. Older 5-step routes (`first-target`,
 * `first-job`) still resolve to the right segment because they're a subset.
 */
import {
  WIZARD_STEPS,
  type WizardStep,
} from "@/lib/onboarding-state";

const STEP_LABELS: Record<WizardStep, string> = {
  welcome: "Welcome",
  "create-org": "Org",
  "first-target": "Target",
  "first-job": "Job",
  "invite-team": "Team",
  done: "Done",
};

export interface ProgressBarProps {
  current: WizardStep;
}

export function ProgressBar({ current }: ProgressBarProps) {
  const currentIdx = WIZARD_STEPS.indexOf(current);

  const total = WIZARD_STEPS.length;
  const stepNumber = Math.max(1, currentIdx + 1);

  return (
    <nav aria-label="Onboarding progress" className="w-full">
      <div className="mb-2 flex items-baseline justify-between">
        <span
          data-testid="progress-counter"
          className="font-sans text-[0.7rem] text-ink"
        >
          {String(stepNumber).padStart(2, "0")}
          <span className="text-graphite-soft"> / {String(total).padStart(2, "0")}</span>
        </span>
        <span className="font-sans text-[0.62rem] text-graphite-soft">
          {STEP_LABELS[current]}
        </span>
      </div>
      <ol className="flex items-center gap-2 md:gap-3">
        {WIZARD_STEPS.map((step, i) => {
          const completed = i < currentIdx;
          const active = i === currentIdx;
          return (
            <li key={step} className="flex-1">
              <div
                data-testid={`progress-segment-${step}`}
                data-state={completed ? "complete" : active ? "active" : "upcoming"}
                className={[
                  "h-1.5 rounded-full transition-colors",
                  completed ? "bg-crane" : active ? "bg-crane" : "bg-lattice",
                  active ? "" : "",
                ].join(" ")}
              />
              <div
                className={[
                  "mt-2 text-[0.62rem] uppercase tracking-[0.16em] md:text-[0.68rem] md:tracking-[0.18em]",
                  active ? "text-ink" : completed ? "text-graphite" : "text-graphite-soft",
                ].join(" ")}
              >
                <span className="mr-1 font-mono">{String(i + 1).padStart(2, "0")}</span>
                {STEP_LABELS[step]}
              </div>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
