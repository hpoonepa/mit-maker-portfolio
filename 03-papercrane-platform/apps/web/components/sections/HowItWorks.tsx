"use client";

import { Reveal } from "../Reveal";

const steps = [
  {
    n: "I",
    title: "Upload your target.",
    body: "Drop a PDB, specify a hotspot — or let us infer one. We parse topology, surface, and interface class in under a second.",
    meta: "Input · PDB/CIF",
  },
  {
    n: "II",
    title: "We allocate the seeds.",
    body: "Our routing algorithm reads your target — helical bundle, β-sheet, disordered loop — and distributes budget across the tools most likely to bind your geometry.",
    meta: "Allocator v1 · validated ipSAE AUC 0.806",
  },
  {
    n: "III",
    title: "Everything runs in parallel.",
    body: "BYO compute on Free. Managed GPUs on Pro. Dedicated cluster on Frontier. No Conda. No CUDA. No seed 847.",
    meta: "Modal · Vast.ai · your VPC",
  },
  {
    n: "IV",
    title: "Ranked candidates, order-ready.",
    body: "Every design scored by ipSAE, DockQ, pTMEnergy. Download the top 10, export to Twist, or push straight to a wet-lab partner.",
    meta: "Output · Scored PDB/FASTA",
  },
];

export function HowItWorks() {
  return (
    <section id="how" className="py-section bg-ink text-paper relative overflow-hidden">
      {/* Subtle grain on dark */}
      <div
        className="absolute inset-0 pointer-events-none opacity-[0.07] mix-blend-screen"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 400 400' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.5 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
        }}
      />

      <div className="container-edge relative">
        <Reveal>
          <div className="flex items-baseline gap-4 mb-16">
            <span className="eyebrow text-paper/50">§ 02 — How it works</span>
            <span className="h-px flex-1 bg-paper/12" />
          </div>
        </Reveal>

        <Reveal delay={1}>
          <h2 className="font-display text-display-lg balance max-w-4xl leading-[0.95]">
            Four folds, then{" "}
            <em className="italic font-normal text-paper/55">a crane takes shape.</em>
          </h2>
          <p className="mt-6 max-w-xl text-[16px] leading-[1.55] text-paper/65 font-sans">
            From PDB to ranked candidates in a single run &mdash; no Conda, no orphaned
            shell scripts, no silent failures at seed 847.
          </p>
        </Reveal>

        <div className="mt-24 grid md:grid-cols-2 gap-x-16 gap-y-20">
          {steps.map((s, i) => (
            <Reveal
              key={s.n}
              delay={((i % 3) + 1) as 1 | 2 | 3}
              className={
                "relative " + (i % 2 === 1 ? "md:mt-24" : "")
              }
            >
              <div className="flex items-start gap-6">
                {/* Roman numeral */}
                <div className="flex-shrink-0">
                  <div className="font-display text-[56px] md:text-[68px] leading-none text-crane italic font-light">
                    {s.n}
                  </div>
                  <div className="mt-3 w-10 h-px bg-paper/30" />
                </div>
                <div className="pt-2">
                  <h3 className="font-display text-[30px] md:text-[36px] leading-[1.05] tracking-tight max-w-md">
                    {s.title}
                  </h3>
                  <p className="mt-5 text-[16px] leading-[1.55] text-paper/70 max-w-md font-sans">
                    {s.body}
                  </p>
                  <div className="mt-6 font-mono text-[10px] tracking-[0.24em] uppercase text-paper/40">
                    {s.meta}
                  </div>
                </div>
              </div>
            </Reveal>
          ))}
        </div>

        {/* Data flow diagram visualized */}
        <Reveal delay={3} className="mt-32">
          <div className="fold-line w-full opacity-50" />
          <div className="grid grid-cols-5 items-center gap-4 mt-8 font-mono text-[10px] tracking-[0.2em] uppercase text-paper/50">
            <span className="text-paper">PDB</span>
            <span className="text-center">→ Allocator</span>
            <span className="text-center">→ GPU cluster</span>
            <span className="text-center">→ Boltz-2 scorer</span>
            <span className="text-right text-crane">Ranked binders</span>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
