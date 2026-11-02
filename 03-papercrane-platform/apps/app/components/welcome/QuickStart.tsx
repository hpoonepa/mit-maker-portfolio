"use client";

/**
 * 3-step starter widget shown on the dashboard when a user has zero projects.
 * Click any card → routes to the matching action. The "Or start with a sample"
 * link reveals the SampleProjects gallery (rendered as a sibling on the page).
 *
 * Composes `<SampleProjects />` lazily: caller controls layout.
 */

import Link from "next/link";
import { ArrowRight, ListChecks, Target, Wrench } from "lucide-react";
import { Card, CardBody, cn } from "@papercrane/ui";

interface Step {
  num: number;
  icon: React.ReactNode;
  title: string;
  body: string;
  href: string;
  cta: string;
}

const STEPS: Step[] = [
  {
    num: 1,
    icon: <Target className="h-5 w-5" aria-hidden />,
    title: "Pick or upload a target",
    body: "Drop a PDB ID, paste a sequence, or upload your own structure.",
    href: "/targets/new",
    cta: "Add target",
  },
  {
    num: 2,
    icon: <Wrench className="h-5 w-5" aria-hidden />,
    title: "Pick your tools",
    body: "BindCraft, RFdiffusion, Boltz: mix and match, or use a preset.",
    href: "/tools",
    cta: "Browse tools",
  },
  {
    num: 3,
    icon: <ListChecks className="h-5 w-5" aria-hidden />,
    title: "Review the results",
    body: "Track the job and compare scored designs when it finishes.",
    href: "/projects/new",
    cta: "Create job",
  },
];

export interface QuickStartProps {
  /** Optional callback when the user clicks "Or start with a sample". */
  onShowSamples?: () => void;
  className?: string;
}

export function QuickStart({ onShowSamples, className }: QuickStartProps) {
  return (
    <section
      aria-labelledby="quickstart-heading"
      className={cn("flex flex-col gap-4", className)}
    >
      <div className="flex flex-col gap-1">
        <h2
          id="quickstart-heading"
          className="font-display text-lg font-semibold tracking-tight text-ink"
        >
          Set up your first run
        </h2>
        <p className="text-sm text-graphite-soft">
          Add a target, choose a tool, and submit a job.
        </p>
      </div>

      <ol className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {STEPS.map((step) => (
          <li key={step.num}>
            <Link
              href={step.href}
              className="group block h-full rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
            >
              <Card className="h-full transition-colors group-hover:border-lattice-strong">
                <CardBody className="flex h-full flex-col gap-3 p-5">
                  <div className="flex items-center gap-2.5">
                    <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-paper-fold text-xs font-semibold text-graphite">
                      {step.num}
                    </span>
                    <span className="text-crane">{step.icon}</span>
                  </div>
                  <h3 className="font-display text-base font-semibold tracking-tight text-ink">
                    {step.title}
                  </h3>
                  <p className="text-sm text-graphite-soft leading-relaxed">
                    {step.body}
                  </p>
                  <div className="mt-auto flex items-center gap-1 text-sm font-medium text-crane group-hover:gap-1.5 transition-all">
                    {step.cta}
                    <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </div>
                </CardBody>
              </Card>
            </Link>
          </li>
        ))}
      </ol>

      {onShowSamples && (
        <div className="text-sm text-graphite-soft">
          Or{" "}
          <button
            type="button"
            onClick={onShowSamples}
            className="font-medium text-crane underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:ring-offset-2 focus-visible:ring-offset-paper rounded-sm"
          >
            start with a sample project
          </button>
          .
        </div>
      )}
    </section>
  );
}
