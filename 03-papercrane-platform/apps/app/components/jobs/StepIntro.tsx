"use client";

import { Info } from "lucide-react";

/**
 * Plain-language glossary. Every scientific noun the wizard uses gets ONE
 * sentence a non-scientist can read, surfaced at the point of first use rather
 * than buried in docs.
 */
export const GLOSSARY = {
  target: "Target: the protein you want to stick something onto.",
  hotspot:
    "Hotspot: the exact patch on the target you want the new protein to grab; picking one aims the design instead of letting it land anywhere.",
  binder:
    "Binder: the small new protein we design to latch onto your target. That's the output of the run.",
  seed: "Seed: one independent attempt with a different random starting point, so more seeds means more different candidate designs.",
  tool: "Tool: the AI model that does the designing. Different tools use different approaches.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;

export interface StepIntroProps {
  /** Short step title. */
  title: string;
  /** One or two sentences: what this step is and why it matters. */
  sub: string;
  /** What happens if the user skips or leaves this at its default. */
  ifSkipped?: string;
  /** Terms defined here, at their point of first use. */
  defines?: GlossaryKey[];
}

/**
 * Header for one wizard step: what it is, why it matters, what a default does,
 * and definitions for any jargon it introduces.
 *
 * Replaces the old bare title+subtitle pair so that no step can present an
 * undefined term to a first-time viewer.
 */
export function StepIntro({ title, sub, ifSkipped, defines }: StepIntroProps) {
  const terms = defines ?? [];
  return (
    <div className="space-y-2" data-testid="e2e-step-intro">
      <h2 className="font-display text-[20px] tracking-tight text-ink">
        {title}
      </h2>
      <p className="max-w-2xl font-sans text-[13px] leading-relaxed text-graphite">
        {sub}
      </p>
      {(ifSkipped || terms.length > 0) && (
        <details className="pt-1">
          <summary className="cursor-pointer text-[12px] text-graphite hover:text-ink">
            About these inputs
          </summary>
          {ifSkipped && (
            <p className="max-w-2xl font-sans text-[12.5px] leading-relaxed text-graphite-soft">
              {ifSkipped}
            </p>
          )}
          {terms.length > 0 && (
            <dl className="mt-3 max-w-2xl space-y-1.5 bg-paper px-4 py-3">
              {terms.map((key) => {
                const [term, ...rest] = GLOSSARY[key].split(": ");
                return (
                  <div key={key} className="flex items-start gap-2">
                    <Info
                      className="mt-[3px] h-3 w-3 shrink-0 text-graphite-soft"
                      aria-hidden="true"
                    />
                    <div className="min-w-0">
                      <dt className="inline font-sans text-[12.5px] font-medium text-ink">
                        {term}
                      </dt>
                      <dd className="inline font-sans text-[12.5px] leading-relaxed text-graphite">
                        {" "}
                        : {rest.join(": ")}
                      </dd>
                    </div>
                  </div>
                );
              })}
            </dl>
          )}
        </details>
      )}
    </div>
  );
}
