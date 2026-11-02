import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "Blog";
const DESCRIPTION =
  "Notes from the Paper Crane team — benchmark releases, methodology essays, and origami-grade engineering writing.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/blog",
  ogTitle: "The Fold",
  ogDesc: "Notes from the Paper Crane team.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Blog", path: "/blog" },
];

const lead = {
  eyebrow: "Issue 01 · Benchmark",
  kicker: "Methodology",
  title: "Why we benchmark on PD-L1, RBD, and IL-7Rα.",
  dek: "Three targets, three reasons. The case for a small, defensible benchmark over a sprawling, irreproducible one — and why the field has been measuring the wrong thing for two years.",
  byline: "Harsha Poonepalle",
  eta: "May 2026",
  readingTime: "11 min read",
};

const queue = [
  {
    n: "02",
    kicker: "Engineering",
    title: "From Conda hell to one-line binders.",
    dek: "How we packaged eight protein design tools behind one API — and what we lost, and kept, along the way.",
    byline: "Paper Crane team",
    eta: "May 2026",
    readingTime: "9 min",
  },
  {
    n: "03",
    kicker: "Methodology",
    title: "ipSAE vs ipTM vs pDockQ — what actually predicts binding.",
    dek: "We ran 540 designs and asked which interface metric correlates with downstream wet-lab success. Spoiler: ipSAE wins, by a wider margin than expected.",
    byline: "Paper Crane team",
    eta: "June 2026",
    readingTime: "14 min",
  },
  {
    n: "04",
    kicker: "Field notes",
    title: "What we learned from 12,000 failed binders.",
    dek: "An honest post-mortem of the misses — what the metrics caught, what they didn't, and the failure modes nobody publishes.",
    byline: "Paper Crane team",
    eta: "July 2026",
    readingTime: "—",
  },
];

export default function BlogPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-32 md:pt-40">
        <section className="container-edge pb-24">
          <Reveal>
            <div className="flex items-baseline gap-4 mb-12">
              <span className="eyebrow">§ The Fold</span>
              <span className="h-px flex-1 bg-lattice" />
              <a
                href="/rss.xml"
                className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft hover:text-crane transition-colors"
                aria-label="RSS feed"
              >
                RSS ↗
              </a>
            </div>
          </Reveal>

          <div className="grid lg:grid-cols-12 gap-10 items-end mb-24 md:mb-32">
            <Reveal delay={1} className="lg:col-span-8">
              <h1 className="font-display text-display-xl balance leading-[0.92]">
                Notes from the{" "}
                <em className="italic font-normal text-crane">workbench.</em>
              </h1>
            </Reveal>
            <Reveal delay={2} className="lg:col-span-4">
              <p className="font-sans text-[18px] leading-[1.6] text-graphite max-w-[40ch]">
                Benchmark releases, methodology essays, and engineering
                writing — paper-thin, fold-clean. Issue 01 lands with v1.0 of
                the benchmark.
              </p>
            </Reveal>
          </div>

          {/* Lead — featured upcoming */}
          <Reveal delay={1}>
            <article className="grid lg:grid-cols-12 gap-10 mb-20 pb-20 border-b border-lattice">
              <div className="lg:col-span-7">
                <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-crane mb-5">
                  {lead.eyebrow}
                </div>
                <h2 className="font-display text-[40px] md:text-[56px] leading-[1.02] tracking-tight balance">
                  {lead.title}
                </h2>
              </div>
              <div className="lg:col-span-5 lg:pl-6 lg:border-l lg:border-lattice">
                <p className="font-sans text-[18px] leading-[1.65] text-graphite max-w-[60ch]">
                  {lead.dek}
                </p>
                <dl className="mt-8 grid grid-cols-3 gap-4 font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
                  <div>
                    <dt className="text-graphite-soft/70 mb-1">Author</dt>
                    <dd className="text-graphite normal-case tracking-normal font-sans text-[13px]">
                      {lead.byline}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-graphite-soft/70 mb-1">Drops</dt>
                    <dd className="text-graphite normal-case tracking-normal font-sans text-[13px]">
                      {lead.eta}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-graphite-soft/70 mb-1">Length</dt>
                    <dd className="text-graphite normal-case tracking-normal font-sans text-[13px]">
                      {lead.readingTime}
                    </dd>
                  </div>
                </dl>
                <div className="mt-6 inline-flex items-center gap-2 font-mono text-[10px] tracking-[0.22em] uppercase text-graphite-soft">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-crane/70" />
                  In edit · preview only
                </div>
              </div>
            </article>
          </Reveal>

          {/* Queue — editorial list, no card grid */}
          <div className="grid lg:grid-cols-12 gap-10">
            <div className="lg:col-span-3">
              <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite-soft sticky top-32">
                In the queue
                <span className="block mt-2 h-px w-8 bg-crane/60" />
              </div>
            </div>
            <ol className="lg:col-span-9 divide-y divide-lattice">
              {queue.map((p, i) => (
                <Reveal key={p.title} delay={((i % 3) + 1) as 1 | 2 | 3}>
                  <li className="group grid md:grid-cols-12 gap-6 py-8 first:pt-0">
                    <div className="md:col-span-1 font-mono text-[11px] tracking-[0.2em] text-graphite-soft pt-1">
                      № {p.n}
                    </div>
                    <div className="md:col-span-7">
                      <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-crane mb-2">
                        {p.kicker}
                      </div>
                      <h3 className="font-display text-[26px] md:text-[30px] leading-[1.15] tracking-tight">
                        {p.title}
                      </h3>
                      <p className="mt-3 font-sans text-[16px] leading-[1.6] text-graphite max-w-[58ch]">
                        {p.dek}
                      </p>
                    </div>
                    <div className="md:col-span-4 md:text-right font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft pt-1 space-y-1">
                      <div>{p.eta}</div>
                      <div className="text-graphite-soft/70">
                        {p.readingTime}
                      </div>
                      <div className="text-graphite-soft/70 normal-case tracking-normal font-sans text-[13px]">
                        {p.byline}
                      </div>
                    </div>
                  </li>
                </Reveal>
              ))}
            </ol>
          </div>

          <Reveal delay={3}>
            <div className="mt-24 hairline-border bg-paper-fold rounded-sm px-8 py-10 md:px-12 md:py-14 grid lg:grid-cols-12 gap-6 items-center">
              <div className="lg:col-span-8">
                <h3 className="font-display text-[28px] md:text-[34px] leading-[1.1] balance">
                  Want first dibs on the writing?
                </h3>
                <p className="mt-3 font-sans text-[15px] leading-[1.6] text-graphite max-w-[55ch]">
                  Same address as the waitlist. We email Issue 01 when it
                  ships, then nothing for a month at a time. No tracking
                  pixels, no sequences.
                </p>
              </div>
              <div className="lg:col-span-4 flex flex-col items-start lg:items-end gap-3">
                <Link href="/#cta" className="btn-primary">
                  Join the list
                  <span className="crane-dot-pulse" />
                </Link>
                <a
                  href="/rss.xml"
                  className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite-soft hover:text-crane transition-colors"
                >
                  Or subscribe via RSS ↗
                </a>
              </div>
            </div>
          </Reveal>
        </section>
      </main>
      <Footer />
    </>
  );
}
