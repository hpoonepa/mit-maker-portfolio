import Link from "next/link";
import { Reveal } from "../Reveal";

const PARAGRAPHS = [
  {
    k: "Targets",
    body: "The proposed panel uses seven canonical targets spanning surface chemistries, sizes, and design difficulty. Hotspots will be declared once per target, frozen before execution, and reused across every tool.",
  },
  {
    k: "Validation pipeline",
    body: "The proposed pipeline folds each generated design with Boltz-2 against the target receptor, then records ipTM, interface pAE, pDockQ, and ipSAE. The first live release must publish the exact scorer versions and justify the primary ranker from cited validation data.",
  },
  {
    k: "Filtering thresholds",
    body: "The draft Tier-A rule is ipSAE ≥ 0.35, ipTM ≥ 0.60, and interface pLDDT ≥ 70. These thresholds remain proposal values until their calibration sources and sensitivity analysis ship with the benchmark.",
  },
  {
    k: "Cost methodology",
    body: "GPU time will be measured wall-clock on a declared instance class. Cost-per-success will use captured run cost divided by Tier-A hits; closed-weight API charges and open-weight GPU costs will be reported separately.",
  },
  {
    k: "Reproducibility",
    body: "Promotion to a live benchmark requires committed configs and seeds, pinned images and weights, public target inputs and hotspot files, and a clean-environment rerun from the published harness.",
  },
  {
    k: "Statistics",
    body: "The planned report includes 95% Wilson confidence intervals and paired bootstrap comparisons. Rank claims will be withheld when the declared uncertainty criteria are not met.",
  },
  {
    k: "Submission process",
    body: "The submission process is still being validated. Open-weight tools will require a pinned runnable repository; closed-weight tools will require an auditable API endpoint that accepts the standard inputs.",
  },
];

export function MethodologySection() {
  return (
    <section id="methodology" className="py-section bg-paper-fold scroll-mt-24">
      <div className="container-edge">
        <Reveal>
          <div className="flex items-baseline gap-4 mb-12">
            <span className="eyebrow">§ Methodology</span>
            <span className="h-px flex-1 bg-lattice" />
            <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
              · protocol draft ·
            </span>
          </div>
        </Reveal>

        <div className="grid lg:grid-cols-12 gap-10">
          <Reveal delay={1} className="lg:col-span-5">
            <h2 className="font-display text-display-md balance leading-[0.96]">
              How we{" "}
              <em className="italic font-normal text-graphite">measure.</em>
            </h2>
            <p className="mt-6 font-sans text-[16px] leading-[1.6] text-graphite max-w-md">
              Declared in advance: the controls and the evidence a run set must
              produce before any number is published here.
            </p>
            <Link
              href="/benchmark/methodology"
              className="btn-primary mt-8"
            >
              Review the protocol draft
              <span className="crane-dot-pulse" />
            </Link>

            <div className="mt-12 space-y-3">
              <Spec k="Targets"        v="PD-L1 · RBD · IL-7Rα · 5G51 · 1CRN · 4HHB · 6X1A" />
              <Spec k="Scoring stack"  v="Boltz-2 · ipSAE · DockQ · Rosetta ΔΔG" />
              <Spec k="Hit criteria"   v="ipSAE ≥ 0.35 · ipTM ≥ 0.60 · pLDDTᵢ ≥ 70" />
              <Spec k="Planned runs"   v="30 seeds per cell" />
              <Spec k="Compute"        v="Captured per run and instance class" />
              <Spec k="Statistics"     v="Planned: 95% Wilson CI · paired bootstrap" />
              <Spec k="Release gate"   v="Artifacts · harness · clean rerun" />
            </div>
          </Reveal>

          <Reveal delay={2} className="lg:col-span-7">
            <ol className="space-y-8">
              {PARAGRAPHS.map((p, i) => (
                <li key={p.k} className="grid grid-cols-[44px_1fr] gap-5">
                  <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane pt-1">
                    {String(i + 1).padStart(2, "0")}
                  </div>
                  <div>
                    <div className="font-display text-[20px] leading-tight text-ink">
                      {p.k}
                    </div>
                    <p className="mt-2 font-sans text-[15px] leading-[1.65] text-graphite">
                      {p.body}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Spec({ k, v }: { k: string; v: string }) {
  return (
    <div className="grid grid-cols-[140px_1fr] gap-5 items-baseline border-b border-lattice py-3">
      <span className="font-mono text-[10px] tracking-[0.22em] uppercase text-graphite-soft">
        {k}
      </span>
      <span className="font-sans text-[14px] text-ink">{v}</span>
    </div>
  );
}
