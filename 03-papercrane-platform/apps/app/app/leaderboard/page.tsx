import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { getWebUrl } from "@/lib/links";

/**
 * Public benchmark page.
 *
 * This route previously rendered a DB-backed grid labelled "LIVE". The rows
 * behind it came from the checked-in preview dataset
 * (`packages/brand/benchmark/preview.json`, loaded into `benchmark_runs` by
 * `benchmark/migrate`), and the scheduled dispatcher that was supposed to
 * replace them has never produced a published run. Showing those numbers
 * under a LIVE label was wrong, so the results surface is gone: not hidden.
 *
 * What stays is the part that is actually true and actually unusual: the
 * methodology is pre-registered, signed, and public *before* any result
 * exists. The grid returns when a run set reproduces from a clean
 * environment against those pre-registered thresholds.
 */

const METHODOLOGY_DOC_URL =
  "https://github.com/papercrane-bio/benchmark/blob/main/methodology-v1.0.md";
const GOVERNANCE_DOC_URL =
  "https://github.com/papercrane-bio/benchmark/blob/main/GOVERNANCE.md";

export const metadata = {
  title: "Benchmark: Paper Crane",
  description:
    "A pre-registered protein binder design benchmark. Methodology v1.0 is published, signed, and frozen; results are published only after a clean-environment rerun.",
};

const GUARANTEES = [
  {
    k: "Pre-registered",
    v: "Targets, hotspots, seed ranges, hit thresholds, and statistics were fixed and published before any run was scored. No threshold can be chosen after seeing a result.",
  },
  {
    k: "Signed & versioned",
    v: "Methodology v1.0 is git-signed and immutable after publication. Changing a threshold, target, or statistic forks a new version with a public diff.",
  },
  {
    k: "External advisory panel",
    v: "Three external members: computational structural biology, experimental protein engineering, and ML methodology: review methodology changes, vote on target admissions, and adjudicate reproducibility disputes.",
  },
  {
    k: "7-day public comment",
    v: "Every proposed new target goes through a seven-day public comment window before the panel votes.",
  },
];

const RELEASE_GATE = [
  "Pinned tool versions, container digests, and weight references",
  "Per-target hotspot files, configs, and the full seed range",
  "Raw outputs and scores for every reported cell",
  "A clean-environment rerun that reproduces the published aggregates",
];

export default function BenchmarkStatusPage() {
  const webUrl = getWebUrl();

  return (
    <>
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-28 md:pt-32 pb-20 md:pb-28">
        <div className="container-edge">
          <div className="flex items-baseline gap-4 mb-10">
            <span className="eyebrow">Benchmark</span>
            <span className="h-px flex-1 bg-lattice" />
            <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane">
              · PRE-REGISTERED ·
            </span>
          </div>

          <div className="max-w-3xl mb-12">
            <h1 className="font-display text-display-lg balance leading-[0.95]">
              The methodology is public{" "}
              <em className="italic font-normal text-crane">
                before the results are.
              </em>
            </h1>
            <p className="mt-6 text-[17px] leading-[1.55] text-graphite max-w-2xl font-sans">
              The Paper Crane benchmark specification: targets, hotspots, seed
              ranges, hit thresholds, statistics, and the reproducibility
              contract: is published, signed, and frozen. Runs are not
              published yet: the execution pipeline is still being validated
              end-to-end, and we will not show a number we cannot reproduce
              from a clean environment.
            </p>
            <p className="mt-4 text-[17px] leading-[1.55] text-graphite max-w-2xl font-sans">
              The leaderboard opens here the day the first run set clears that
              gate, scored against criteria written down long before we saw
              them.
            </p>
          </div>

          <div className="hairline-border bg-paper rounded-sm p-6 md:p-8">
            <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite mb-6">
              Paper Crane Benchmark · Methodology v1.0
            </div>
            <dl className="space-y-5">
              {GUARANTEES.map((g) => (
                <div key={g.k} className="grid md:grid-cols-[180px_1fr] gap-2 md:gap-5">
                  <dt className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane pt-1">
                    {g.k}
                  </dt>
                  <dd className="font-sans text-[14px] leading-[1.65] text-graphite max-w-[62ch]">
                    {g.v}
                  </dd>
                </div>
              ))}
            </dl>

            <div className="mt-8 pt-6 border-t border-lattice flex flex-wrap gap-3">
              <a
                href={METHODOLOGY_DOC_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-ghost"
              >
                Methodology v1.0 ↗
              </a>
              <a
                href={GOVERNANCE_DOC_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-ghost"
              >
                Governance &amp; conflict-of-interest policy ↗
              </a>
              <a href={`${webUrl}/benchmark/methodology`} className="btn-ghost">
                Protocol summary →
              </a>
            </div>
          </div>

          <div className="mt-12 grid lg:grid-cols-12 gap-10 items-start">
            <div className="lg:col-span-5">
              <h2 className="font-display text-display-md balance leading-[0.96]">
                A result is only a result if{" "}
                <em className="italic font-normal text-graphite">
                  you can re-run it.
                </em>
              </h2>
            </div>
            <div className="lg:col-span-7">
              <ul className="space-y-4 font-sans text-[15px] leading-[1.65] text-graphite max-w-xl">
                {RELEASE_GATE.map((item) => (
                  <li key={item} className="flex gap-3 border-b border-lattice pb-4">
                    <span className="crane-dot mt-2 shrink-0" />
                    <span className="text-ink-soft">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="mt-12 flex flex-wrap gap-4 items-center">
            <a href={`${webUrl}/#benchmark`} className="btn-ghost">
              ← Back to benchmark overview
            </a>
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}
