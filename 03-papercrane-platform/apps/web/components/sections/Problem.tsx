"use client";

import { Reveal } from "../Reveal";

const pains = [
  {
    n: "01",
    title: "Every tool claims SOTA.\nNone of them agree.",
    body: "ProteinMPNN wins on one target, RFdiffusion on the next, BindCraft on a third. There's a right tool for your target — but nobody's measured which.",
  },
  {
    n: "02",
    title: "A thousand seeds is a weekend\nof shell scripts.",
    body: "Conda conflicts. CUDA mismatches. Silent failures at seed 847. You came to design proteins, not maintain containers.",
  },
  {
    n: "03",
    title: "Every benchmark is\na different ruler.",
    body: "Each tool reports on its own target with its own scoring. We run every major tool against the same three targets, with one rubric and pre-registered thresholds — and publish the full dataset.",
  },
];

export function Problem() {
  return (
    <section className="py-section relative" id="problem">
      <div className="container-edge">
        <Reveal>
          <div className="flex items-baseline gap-4 mb-16">
            <span className="eyebrow">§ 01 — The Problem</span>
            <span className="h-px flex-1 bg-lattice" />
          </div>
        </Reveal>

        <Reveal delay={1}>
          <h2 className="font-display text-display-lg balance max-w-4xl leading-[0.95]">
            Designing a binder shouldn&rsquo;t feel{" "}
            <em className="italic font-normal text-graphite">like gambling.</em>
          </h2>
        </Reveal>

        <div className="mt-20 grid md:grid-cols-3 gap-px bg-lattice-strong">
          {pains.map((p, i) => (
            <Reveal
              key={p.n}
              delay={(i + 1) as 1 | 2 | 3}
              className="bg-paper p-8 md:p-10 group transition-colors hover:bg-paper-fold"
            >
              <div className="flex items-start justify-between mb-8">
                <span className="font-mono text-[11px] tracking-[0.24em] text-crane">
                  {p.n}
                </span>
                <span className="w-6 h-px bg-ink translate-y-2 group-hover:w-10 transition-all duration-500" />
              </div>
              <h3 className="font-display text-[26px] md:text-[30px] leading-[1.08] tracking-tight whitespace-pre-line">
                {p.title}
              </h3>
              <p className="mt-6 text-[15px] leading-[1.55] text-graphite font-sans">
                {p.body}
              </p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
