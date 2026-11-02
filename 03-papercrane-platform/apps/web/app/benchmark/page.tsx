import type { Metadata } from "next";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { PreRegistration } from "@/components/benchmark/PreRegistration";
import { MethodologySection } from "@/components/benchmark/MethodologySection";
import { SubmitForm } from "@/components/benchmark/SubmitForm";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

/**
 * Public benchmark page.
 *
 * This page deliberately renders no results. The Paper Crane benchmark is
 * pre-registered: the specification is published, signed, and frozen before
 * any run is scored. Until the execution pipeline is validated end-to-end
 * there is nothing reproducible to show, so we show the specification.
 */

const TITLE = "Benchmark";
const DESCRIPTION =
  "A pre-registered, publicly specified benchmark for protein binder design. Methodology first; results are published only after a clean-environment rerun.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/benchmark",
  ogTitle: "Benchmark",
  ogDesc: "Pre-registered methodology. Results published after validation.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Benchmark", path: "/benchmark" },
];

const RELEASE_GATE = [
  "Pinned tool versions, container digests, and weight references",
  "Per-target hotspot files, configs, and the full seed range",
  "Raw outputs and scores for every reported cell",
  "A clean-environment rerun that reproduces the published aggregates",
];

export default function BenchmarkPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-32 md:pt-40">
        {/* HEADER */}
        <section className="container-edge pb-12">
          <Reveal>
            <div className="flex items-baseline gap-4 mb-10">
              <span className="eyebrow">Benchmark · v1.0</span>
              <span className="h-px flex-1 bg-lattice" />
              <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane">
                · PRE-REGISTERED ·
              </span>
            </div>
          </Reveal>

          <div className="grid lg:grid-cols-12 gap-10 items-end mb-14">
            <Reveal delay={1} className="lg:col-span-8">
              <h1 className="font-display text-display-xl balance leading-[0.92]">
                The methodology is public{" "}
                <em className="italic font-normal text-crane">
                  before the results are.
                </em>
              </h1>
            </Reveal>
            <Reveal delay={2} className="lg:col-span-4">
              <p className="font-sans text-[17px] leading-[1.55] text-graphite max-w-md">
                Every target, hotspot, seed count, and hit threshold was
                declared and signed in advance. Runs are not published yet;
                results land here once the pipeline reproduces cleanly.
              </p>
            </Reveal>
          </div>

          <Reveal delay={3}>
            <PreRegistration />
          </Reveal>
        </section>

        {/* RELEASE GATE */}
        <section className="container-edge pb-20">
          <Reveal>
            <div className="flex items-baseline gap-4 mb-8">
              <span className="eyebrow">What ships with the first release</span>
              <span className="h-px flex-1 bg-lattice" />
            </div>
          </Reveal>
          <div className="grid lg:grid-cols-12 gap-10 items-start">
            <Reveal delay={1} className="lg:col-span-5">
              <h2 className="font-display text-display-md balance leading-[0.96]">
                A result is only a result if{" "}
                <em className="italic font-normal text-graphite">
                  you can re-run it.
                </em>
              </h2>
            </Reveal>
            <Reveal delay={2} className="lg:col-span-7">
              <ul className="space-y-4 font-sans text-[15px] leading-[1.65] text-graphite max-w-xl">
                {RELEASE_GATE.map((item) => (
                  <li key={item} className="flex gap-3 border-b border-lattice pb-4">
                    <span className="crane-dot mt-2 shrink-0" />
                    <span className="text-ink-soft">{item}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-6 font-sans text-[14px] leading-[1.65] text-graphite max-w-xl">
                Until all four hold for a run set, this page shows the protocol
                and nothing else. That is the guarantee, not a placeholder.
              </p>
            </Reveal>
          </div>
        </section>

        {/* METHODOLOGY */}
        <MethodologySection />

        {/* SUBMIT */}
        <section className="py-section">
          <div className="container-edge">
            <Reveal>
              <div className="flex items-baseline gap-4 mb-12">
                <span className="eyebrow">Submit your model</span>
                <span className="h-px flex-1 bg-lattice" />
              </div>
            </Reveal>

            <div className="grid lg:grid-cols-12 gap-10 items-start">
              <Reveal delay={1} className="lg:col-span-6">
                <h2 className="font-display text-display-md balance leading-[0.96]">
                  Built a binder design tool?{" "}
                  <em className="italic font-normal text-crane">
                    Register it for the first run set.
                  </em>
                </h2>
                <p className="mt-6 font-sans text-[16px] leading-[1.6] text-graphite max-w-md">
                  Share your tool name, repository, paper, and contact email.
                  We&rsquo;ll follow up as the reproducible submission harness and
                  review process are validated.
                </p>
                <ul className="mt-8 space-y-3 font-sans text-[14px] text-ink-soft max-w-md">
                  <li className="flex gap-3"><span className="crane-dot mt-2" />Public, open-weight tools added free of charge</li>
                  <li className="flex gap-3"><span className="crane-dot mt-2" />Closed-weight tools require an API endpoint we can call</li>
                  <li className="flex gap-3"><span className="crane-dot mt-2" />Published results include configs, seeds, and an audit trail</li>
                  <li className="flex gap-3"><span className="crane-dot mt-2" />Release cadence begins after the first reproducible run set</li>
                </ul>
              </Reveal>

              <Reveal delay={2} className="lg:col-span-6">
                <SubmitForm />
              </Reveal>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
