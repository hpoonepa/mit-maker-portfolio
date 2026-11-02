"use client";

import { Reveal } from "../Reveal";
import { ArrowUpRight } from "lucide-react";
import { PUBLIC_TOOL_CATALOG } from "@/lib/tool-catalog";

const tools = [
  {
    name: "RFdiffusion",
    kind: "Generative backbone",
    author: "Baker Lab",
    license: "Open",
    year: "2023",
  },
  {
    name: "ProteinMPNN",
    kind: "Sequence design",
    author: "Baker Lab",
    license: "MIT",
    year: "2022",
  },
  {
    name: "BindCraft",
    kind: "End-to-end binder",
    author: "Pacesa et al.",
    license: "Open",
    year: "2024",
  },
  {
    name: "Chai-1",
    kind: "Structure prediction",
    author: "Chai Discovery",
    license: "Closed · Frontier",
    year: "2024",
  },
  {
    name: "Boltz-2",
    kind: "Validator",
    author: "MIT",
    license: "Open",
    year: "2025",
  },
  {
    name: "Chroma",
    kind: "Generative model",
    author: "Generate:Bio",
    license: "Open",
    year: "2023",
  },
  {
    name: "LigandMPNN",
    kind: "Ligand-aware design",
    author: "Baker Lab",
    license: "Open",
    year: "2024",
  },
  {
    name: "AlphaFold 3",
    kind: "Structure prediction",
    author: "Isomorphic",
    license: "Closed · Frontier",
    year: "2024",
  },
];

export function Tools() {
  return (
    <section id="tools" className="py-section">
      <div className="container-edge">
        <Reveal>
          <div className="flex items-baseline gap-4 mb-16">
            <span className="eyebrow">§ 03 — The Catalog</span>
            <span className="h-px flex-1 bg-lattice" />
          </div>
        </Reveal>

        <div className="grid lg:grid-cols-12 gap-10 items-end mb-20">
          <Reveal delay={1} className="lg:col-span-7">
            <h2 className="font-display text-display-lg balance leading-[0.95]">
              Every tool,{" "}
              <em className="italic font-normal text-crane">
                version-pinned
              </em>
              , containerized, benchmarked.
            </h2>
          </Reveal>
          <Reveal delay={2} className="lg:col-span-4 lg:col-start-9">
            <p className="text-[17px] leading-[1.5] text-graphite font-sans max-w-sm">
              A curated index of every protein design tool worth running — with
              reproducible environments, pinned weights, and head-to-head
              metrics on the same targets.
            </p>
          </Reveal>
        </div>

        {/* Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-px bg-lattice-strong hairline-border">
          {tools.map((t, i) => (
            <Reveal
              key={t.name}
              delay={((i % 4) + 1) as 1 | 2 | 3 | 4}
              className="group relative bg-paper p-6 md:p-8 transition-all hover:bg-paper-fold cursor-pointer aspect-[5/4]"
            >
              {/* corner accent */}
              <div className="absolute top-0 right-0 w-10 h-10 overflow-hidden">
                <div className="absolute top-0 right-0 w-20 h-20 -translate-y-1/2 translate-x-1/2 rotate-45 bg-paper-deep group-hover:bg-crane/8 transition-colors" />
              </div>

              {/* tool header */}
              <div className="flex items-start justify-between">
                <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite">
                  {t.year}
                </span>
                <ArrowUpRight
                  className="w-4 h-4 text-graphite-soft group-hover:text-crane group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-all"
                  strokeWidth={1.5}
                />
              </div>

              {/* tool name */}
              <h3 className="mt-10 font-display text-[26px] md:text-[30px] leading-[1.02] tracking-tight">
                {t.name}
              </h3>

              {/* meta */}
              <div className="mt-auto absolute bottom-6 md:bottom-8 left-6 md:left-8 right-6 md:right-8">
                <div className="h-px w-10 bg-ink mb-4 group-hover:bg-crane transition-colors" />
                <div className="font-sans text-[13px] text-ink">{t.kind}</div>
                <div className="mt-1 font-mono text-[10px] tracking-[0.18em] uppercase text-graphite flex justify-between">
                  <span>{t.author}</span>
                  <span
                    className={
                      t.license.includes("Closed")
                        ? "text-crane"
                        : "text-graphite-soft"
                    }
                  >
                    {t.license}
                  </span>
                </div>
              </div>
            </Reveal>
          ))}
        </div>

        <Reveal delay={3} className="mt-10 flex items-center gap-3 justify-end">
          <span className="font-mono text-[11px] tracking-[0.2em] uppercase text-graphite">
            + {PUBLIC_TOOL_CATALOG.length - tools.length} more in catalog
          </span>
          <a
            href="/tools"
            className="group inline-flex items-center gap-1.5 font-sans text-[14px] text-ink underline underline-offset-4 decoration-lattice-strong hover:decoration-crane"
          >
            Browse all {PUBLIC_TOOL_CATALOG.length} tools
            <ArrowUpRight
              className="w-3.5 h-3.5 text-graphite-soft group-hover:text-crane group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-all"
              strokeWidth={1.5}
            />
          </a>
        </Reveal>
      </div>
    </section>
  );
}
