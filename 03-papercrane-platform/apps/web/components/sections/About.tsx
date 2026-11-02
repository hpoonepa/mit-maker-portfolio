"use client";

import { Reveal } from "../Reveal";

export function About() {
  return (
    <section id="about" className="py-section relative">
      <div className="container-edge">
        <Reveal>
          <div className="flex items-baseline gap-4 mb-16">
            <span className="eyebrow">§ 06 — Built by</span>
            <span className="h-px flex-1 bg-lattice" />
          </div>
        </Reveal>

        <div className="grid lg:grid-cols-12 gap-10 lg:gap-16 items-start">
          {/* Left narrative */}
          <div className="lg:col-span-7">
            <Reveal delay={1}>
              <h2 className="font-display text-display-lg balance leading-[0.95]">
                Two high-schoolers who got{" "}
                <em className="italic font-normal text-crane">tired of Conda.</em>
              </h2>
            </Reveal>

            <Reveal delay={2}>
              <div className="mt-12 space-y-6 text-[17px] leading-[1.6] text-ink-soft font-sans max-w-2xl">
                <p>
                  We&rsquo;re{" "}
                  <span className="text-ink font-medium">Harsha Poonepalle</span>{" "}
                  and{" "}
                  <span className="text-ink font-medium">
                    Vedant Kalipatnapu
                  </span>{" "}
                  — iGEM co-captains and international winners at the iGEM
                  Grand Jamboree. We spent a full season running ProteinMPNN,
                  RFdiffusion, and BindCraft against the same target, by hand,
                  one seed at a time. We lost three weekends to environment
                  conflicts before we shipped a single design that worked.
                </p>
                <p>
                  We built Paper Crane because we wanted the tool we
                  couldn&rsquo;t find. {/* TODO confirm permission to name advisors publicly */}
                  Advised by{" "}
                  <span className="text-ink font-medium">Dr. Bryan Bryson</span>{" "}
                  (MIT Biological Engineering),{" "}
                  <span className="text-ink font-medium">Dr. Metzker</span>{" "}
                  (ex-MIT/Harvard, bio founder), plus faculty at{" "}
                  <span className="text-ink font-medium">UCLA</span> and{" "}
                  <span className="text-ink font-medium">UPenn</span>. Our
                  early users include iGEM teams across four continents.
                </p>
                <p>
                  We believe the next generation of therapeutics will be{" "}
                  <em className="italic font-display text-ink">designed</em>,
                  not discovered — and that the platform underneath should be
                  as elegant as the proteins it builds.
                </p>
              </div>
            </Reveal>

            <Reveal delay={3} className="mt-12 flex flex-wrap gap-6 items-center">
              {["MIT", "UCLA", "UPenn"].map((u) => (
                <div
                  key={u}
                  className="flex items-center gap-2 font-mono text-[11px] tracking-[0.2em] uppercase text-graphite"
                >
                  <span className="crane-dot opacity-50" />
                  <span>{u} · faculty advisory</span>
                </div>
              ))}
            </Reveal>
          </div>

          {/* Right: origami card */}
          <Reveal delay={3} className="lg:col-span-5 lg:sticky lg:top-32">
            <div className="relative aspect-[4/5] bg-gradient-to-br from-paper-fold to-paper-deep rounded-sm overflow-hidden hairline-border">
              {/* Will accept founders-hands.jpg later */}
              <div className="absolute inset-0 flex flex-col items-center justify-center p-10 text-center">
                <svg
                  viewBox="0 0 80 80"
                  className="w-16 h-16 text-ink/60 mb-8"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="0.8"
                >
                  <path d="M10 46 L40 18 L70 46 L48 54 L40 68 L32 54 Z" />
                  <path d="M40 18 L40 54" strokeOpacity="0.4" />
                  <circle cx="48" cy="34" r="1.5" fill="#C1272D" stroke="none" />
                </svg>
                <div className="font-display italic text-[22px] leading-[1.3] text-ink/80 balance max-w-xs">
                  &ldquo;Fold enough paper, carefully enough, and one of them
                  will heal something.&rdquo;
                </div>
                <div className="mt-6 font-mono text-[10px] tracking-[0.22em] uppercase text-graphite">
                  — Paper Crane manifesto
                </div>
              </div>

              {/* Corner fold effect */}
              <div
                className="absolute top-0 right-0 w-24 h-24"
                style={{
                  background:
                    "linear-gradient(225deg, rgba(20,17,13,0.15) 0%, transparent 55%)",
                }}
              />
            </div>

            {/* Meta strip */}
            <div className="mt-5 grid grid-cols-3 gap-4 font-mono text-[10px] tracking-[0.18em] uppercase text-graphite">
              <div>
                <div className="text-graphite-soft">Founded</div>
                <div className="mt-1 text-ink">2026</div>
              </div>
              <div>
                <div className="text-graphite-soft">HQ</div>
                <div className="mt-1 text-ink">Atlanta → SF</div>
              </div>
              <div>
                <div className="text-graphite-soft">Batch</div>
                <div className="mt-1 text-crane">YC S26</div>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
