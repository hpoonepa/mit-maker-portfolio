"use client";

import dynamic from "next/dynamic";
import { HeroCopy } from "@/components/hero/HeroCopy";
import { MetricRail } from "@/components/hero/MetricRail";

/**
 * The real tool catalog, grouped by the four functional categories used
 * throughout the product. Hardcoded intentionally — this masthead is a
 * marketing surface and does not read from the API.
 */
const ROSTER: { label: string; tools: string[] }[] = [
  {
    label: "Binder design",
    tools: [
      "RFdiffusion",
      "RFdiffusionAA",
      "Chroma",
      "BoltzGen",
      "BindCraft",
      "Germinal",
    ],
  },
  {
    label: "Sequence design",
    tools: ["ProteinMPNN", "LigandMPNN", "SolubleMPNN"],
  },
  {
    label: "Structure prediction",
    tools: ["Boltz-2", "Boltz-1", "Chai-1", "AlphaFold 3"],
  },
  {
    label: "Embeddings & scoring",
    tools: ["ESM-2", "ESM-C"],
  },
];

/**
 * Lazy-load the Mol* spinner. Mol* is ~2 MB gzipped; keeping it behind
 * `next/dynamic({ ssr: false })` ensures the landing page's initial
 * JavaScript payload stays light and the heavy chunk only loads in the
 * browser, after first paint, alongside the structure download.
 */
const ProteinSpinner = dynamic(
  () =>
    import("@/components/hero/ProteinSpinner").then((m) => m.ProteinSpinner),
  {
    ssr: false,
    loading: () => (
      <div
        aria-hidden="true"
        className="aspect-square w-full rounded-[28px] border border-lattice bg-paper-fold/40 flex items-center justify-center"
      >
        <div className="flex flex-col items-center gap-3">
          <div className="h-12 w-12 animate-spin rounded-full border-2 border-crane/25 border-t-crane" />
          <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-graphite-soft">
            Folding 6X1A…
          </span>
        </div>
      </div>
    ),
  },
);

export function Hero() {
  return (
    <section className="relative pt-28 md:pt-32 pb-16 md:pb-20 overflow-hidden">
      {/* Soft paper-tinted background — replaces the looping video so the
          spinner is the only kinetic element above the fold. */}
      <div
        aria-hidden="true"
        className="absolute inset-0 pointer-events-none select-none bg-radial-warm"
      />

      {/* Top meta strip */}
      <div className="container-edge relative z-10">
        <div className="flex items-center gap-3 mb-10 md:mb-14 animate-fade-in">
          <span className="crane-dot-pulse" />
          <span className="font-mono text-[11px] tracking-[0.22em] uppercase text-graphite">
            Private beta · YC S26
          </span>
          <span className="h-px flex-1 bg-lattice max-w-[240px]" />
          <span className="font-mono text-[11px] tracking-[0.22em] uppercase text-graphite hidden md:inline">
            Est. 2026 · Senbazuru
          </span>
        </div>
      </div>

      <div className="container-edge relative z-10">
        <div className="grid gap-10 lg:gap-16 lg:grid-cols-[1.05fr_0.95fr] items-center">
          {/* Copy column */}
          <HeroCopy />

          {/* Spinner column */}
          <div
            className="relative animate-fade-in"
            style={{ animationDelay: "240ms" }}
          >
            <div className="relative max-w-[520px] mx-auto lg:ml-auto lg:mr-0">
              <ProteinSpinner pdbId="6X1A" />
              {/* Decorative crane glow ring (paint-only) */}
              <div
                aria-hidden="true"
                className="absolute -inset-6 -z-10 rounded-[40px] bg-radial-warm opacity-70 blur-3xl"
              />
            </div>
          </div>
        </div>

        {/* Metric rail */}
        <div className="mt-14 md:mt-20 animate-fade-up" style={{ animationDelay: "780ms" }}>
          <MetricRail />
        </div>

      </div>

      {/* Static editorial roster of supported tools — one hairline rule, no
          duplicate kinetic marquee. Reads like a masthead, not a sales bar. */}
      <div className="container-edge relative z-10 mt-20 md:mt-24">
        <div className="flex items-baseline gap-4 mb-8">
          <span className="eyebrow">The roster</span>
          <span className="h-px flex-1 bg-lattice" />
          <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-graphite-soft hidden md:inline">
            52 tools · open &amp; closed-weight
          </span>
        </div>
        <div className="flex flex-col gap-6">
          {ROSTER.map((group) => (
            <div
              key={group.label}
              className="grid gap-x-8 gap-y-2 md:grid-cols-[180px_1fr] md:items-baseline"
            >
              <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-graphite-soft pt-1">
                {group.label}
              </span>
              <div className="flex flex-wrap items-baseline gap-x-8 gap-y-3 font-display text-[20px] md:text-[24px] tracking-tight text-graphite-soft">
                {group.tools.map((t, i, arr) => (
                  <span key={t} className="flex items-baseline gap-8">
                    <span className="hover:text-ink transition-colors duration-300">
                      {t}
                    </span>
                    {i < arr.length - 1 ? (
                      <span aria-hidden="true" className="crane-dot opacity-30" />
                    ) : null}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
