import Link from "next/link";
import { Reveal } from "../Reveal";

/**
 * Pre-registration panel — the public face of the benchmark until the first
 * reproducible run set is validated.
 *
 * There is no results surface — the methodology is published, versioned, and
 * signed *before* any numbers exist, which is the whole point. Rendering
 * illustrative values here would defeat the pre-registration guarantee, so
 * this component links to the specification instead.
 */

export const METHODOLOGY_DOC_URL =
  "https://github.com/papercrane-bio/benchmark/blob/main/methodology-v1.0.md";
export const GOVERNANCE_DOC_URL =
  "https://github.com/papercrane-bio/benchmark/blob/main/GOVERNANCE.md";

const GUARANTEES = [
  {
    k: "Pre-registered",
    v: "Targets, hotspots, seed counts, hit thresholds, and statistics were fixed and published before any run was scored. Nothing can be tuned after seeing results.",
  },
  {
    k: "Signed & versioned",
    v: "Methodology v1.0 is git-signed and immutable after publication. Changing a threshold, target, or statistic forks a new version with a public diff.",
  },
  {
    k: "External advisory panel",
    v: "Three external members — structural biology, experimental protein engineering, and ML methodology — review methodology changes and adjudicate reproducibility disputes.",
  },
  {
    k: "7-day public comment",
    v: "Every proposed new target goes through a seven-day public comment window before the panel votes on admission.",
  },
];

export function PreRegistration({
  eyebrowLabel = "§ Benchmark · Methodology v1.0",
}: {
  eyebrowLabel?: string;
}) {
  return (
    <div className="hairline-border bg-paper rounded-sm p-6 md:p-8">
      <div className="flex items-baseline justify-between mb-6 flex-wrap gap-3">
        <div>
          <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite">
            {eyebrowLabel}
          </div>
          <div className="font-display text-[22px] mt-1 leading-none">
            Pre-registered. Results pending.
          </div>
        </div>
        <div className="font-mono text-[10px] tracking-[0.18em] uppercase text-graphite-soft">
          · specification published ·
        </div>
      </div>

      <div className="fold-line mb-6 opacity-60" />

      <p className="font-sans text-[15px] leading-[1.65] text-graphite max-w-[62ch]">
        The protocol is public and frozen. The runs are not published yet — the
        execution pipeline is still being validated end-to-end, and we will not
        show a number we cannot reproduce from a clean environment. The
        leaderboard appears here the day the first run set clears that gate,
        against thresholds that were written down long before we saw them.
      </p>

      <dl className="mt-8 space-y-5">
        {GUARANTEES.map((g) => (
          <div key={g.k} className="grid md:grid-cols-[168px_1fr] gap-2 md:gap-5">
            <dt className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane pt-1">
              {g.k}
            </dt>
            <dd className="font-sans text-[14px] leading-[1.65] text-graphite max-w-[58ch]">
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
        <Link href="/benchmark/methodology" className="btn-ghost">
          Protocol summary →
        </Link>
      </div>
    </div>
  );
}

export function PreRegistrationSection() {
  return (
    <Reveal>
      <PreRegistration />
    </Reveal>
  );
}
