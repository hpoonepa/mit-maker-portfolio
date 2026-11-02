"use client";

import Link from "next/link";
import { Reveal } from "../Reveal";
import { PreRegistration } from "../benchmark/PreRegistration";

/**
 * Landing-page benchmark section.
 *
 * This section previously rendered an illustrative hit-rate table. Those
 * numbers were never measured, so they are gone: the benchmark is
 * pre-registered, and the honest surface before the first reproducible run
 * set is the specification itself.
 */

const methodologyHref = "/benchmark/methodology";

export function Benchmark() {
  return (
    <section id="benchmark" className="py-section relative">
      <div className="container-edge">
        <Reveal>
          <div className="flex items-baseline gap-4 mb-16">
            <span className="eyebrow">§ 04 — The Benchmark</span>
            <span className="h-px flex-1 bg-lattice" />
            <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane">
              · PRE-REGISTERED ·
            </span>
          </div>
        </Reveal>

        <div className="grid lg:grid-cols-12 gap-10 lg:gap-16 items-start">
          <div className="lg:col-span-5">
            <Reveal delay={1}>
              <h2 className="font-display text-display-lg balance leading-[0.95]">
                We publish the{" "}
                <em className="italic font-normal text-crane">methodology</em>{" "}
                before the results.
              </h2>
            </Reveal>

            <Reveal delay={2}>
              <p className="mt-10 text-[17px] leading-[1.55] text-graphite max-w-md font-sans">
                Targets, hotspots, seed counts, hit thresholds, and statistics
                are declared up front in a signed, versioned specification, so
                no threshold can be chosen after the fact.
              </p>
              <p className="mt-5 text-[17px] leading-[1.55] text-graphite max-w-md font-sans">
                Runs are not published yet. The leaderboard opens when a run set
                reproduces from a clean environment against those pre-registered
                criteria — not before.
              </p>
            </Reveal>

            <Reveal delay={3} className="mt-10 space-y-3">
              <Meta
                k="Scoring stack"
                v="Boltz-2 · ipSAE · DockQ · Rosetta ΔΔG"
              />
              <Meta
                k="Hit criteria"
                v="ipSAE ≥ 0.35 · ipTM ≥ 0.60 · pLDDTᵢ ≥ 70"
              />
              <Meta k="Statistics" v="95% Wilson CI · paired bootstrap" />
              <Meta
                k="Oversight"
                v="External advisory panel · public comment"
              />
            </Reveal>

            <Reveal delay={4} className="mt-10 flex flex-wrap gap-3">
              <Link href={methodologyHref} className="btn-ghost">
                Read the methodology
              </Link>
              <Link href="/benchmark" className="btn-ghost">
                See the pre-registration →
              </Link>
            </Reveal>
          </div>

          {/* Pre-registration — no results are rendered until runs validate */}
          <Reveal delay={2} className="lg:col-span-7">
            <PreRegistration eyebrowLabel="Paper Crane Benchmark · v1.0" />
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-5 items-baseline text-[13px]">
      <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
        {k}
      </span>
      <span className="font-sans text-ink">{v}</span>
    </div>
  );
}
