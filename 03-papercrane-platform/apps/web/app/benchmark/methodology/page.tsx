import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "Benchmark Methodology";
const DESCRIPTION =
  "The proposed Paper Crane benchmark protocol: targets, tools, metrics, controls, and reproducibility release criteria.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/benchmark/methodology",
  ogTitle: "Methodology",
  ogDesc: "Proposed protocol and release criteria.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Benchmark", path: "/benchmark" },
  { name: "Methodology", path: "/benchmark/methodology" },
];

const TARGETS = [
  {
    pdb: "5O45",
    name: "PD-L1 (atezolizumab Fab interface)",
    note: "Helical-bias hotspot panel; canonical immuno-oncology target.",
  },
  {
    pdb: "7BWJ",
    name: "SARS-CoV-2 RBD",
    note: "ACE2-mimetic interface; well-characterised epitope.",
  },
  {
    pdb: "2LGV",
    name: "RBX1 (RING-box 1)",
    note: "E3 ligase substrate handle; small, flexible target.",
  },
  {
    pdb: "3DI3",
    name: "IL-7Rα extracellular domain",
    note: "Cytokine receptor; published binder benchmark exists.",
  },
  {
    pdb: "1YCR",
    name: "MDM2–p53 interface",
    note: "Classical PPI hotspot; strong literature ground truth.",
  },
];

const TOOLS = [
  { name: "BindCraft", version: "v1.5.0" },
  { name: "BoltzGen", version: "v0.4.1" },
  { name: "RFdiffusion", version: "v1.1.0" },
  { name: "RFdiffusion-AA", version: "v0.2.0" },
  { name: "ProteinMPNN", version: "v1.0.1" },
  { name: "LigandMPNN", version: "v0.3.0" },
  { name: "SolubleMPNN", version: "v1.0.0" },
  { name: "Chai-1", version: "v0.5.0" },
  { name: "Boltz-2", version: "v2.0.0" },
  { name: "AlphaFold2", version: "v2.3.2" },
  { name: "ESMFold", version: "v1.0.3" },
  { name: "ESM2 (650M)", version: "esm2_t33_650M_UR50D" },
];

const METRICS = [
  {
    name: "ipSAE",
    role: "Primary ranker",
    auc: "pooled historical estimate",
    def: "Interprotein Score from Aligned Errors. Reweights PAE so only across-chain residue pairs near the predicted interface contribute. It is a candidate primary ranker, but within-target performance varies and the historical pooled AUC is not evidence of transfer to a new target.",
  },
  {
    name: "ipTM",
    role: "Confidence floor",
    auc: "AUC 0.628",
    def: "Interface predicted-TM score from AlphaFold2 / Boltz. Used as a hard confidence floor before ipSAE reranking, not as a final ranker.",
  },
  {
    name: "DockQ",
    role: "Structural agreement",
    auc: "reference only",
    def: "Continuous CAPRI-style score in [0, 1] comparing predicted interface to a reference complex. Reported only for targets with experimental complex structures.",
  },
  {
    name: "pTMEnergy",
    role: "Secondary signal",
    auc: "exploratory",
    def: "Energy-style transform of pTM proposed in 2025 literature. Tracked as an exploratory secondary signal; not used to break ties on the public leaderboard.",
  },
];

export default function MethodologyPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-32 md:pt-40">
        {/* HEADER */}
        <section className="container-edge pb-16">
          <Reveal>
            <span className="eyebrow">Benchmark · Methodology</span>
            <h1 className="font-serif text-[clamp(2.5rem,6vw,5rem)] leading-[0.95] tracking-[-0.02em] mt-6 mb-6">
              How the benchmark will be run.
            </h1>
            <p className="max-w-[58ch] text-ink/70 text-lg leading-relaxed">
              This is the pre-registered protocol, published before any result
              exists. Nothing here is evidence that a run has been reproduced -
              a published release requires these exact targets, hotspots,
              seeds, scoring pipeline, and hardware controls.
            </p>
            <div className="mt-8 flex flex-wrap gap-3 text-sm">
              <Link
                href="/benchmark"
                className="inline-flex items-center gap-2 px-4 py-2 border border-ink/20 hover:border-ink/60 transition"
              >
                ← Benchmark
              </Link>
              <a
                href="https://github.com/papercrane-bio/benchmark/blob/main/methodology-v1.0.md"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 border border-ink/20 hover:border-ink/60 transition"
              >
                Signed methodology v1.0 ↗
              </a>
              <a
                href="https://github.com/papercrane-bio/benchmark/blob/main/GOVERNANCE.md"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 border border-ink/20 hover:border-ink/60 transition"
              >
                Governance ↗
              </a>
              <span className="inline-flex items-center gap-2 px-4 py-2 border border-ink/20 font-mono text-ink/60">
                Public harness pending validation
              </span>
            </div>
          </Reveal>
        </section>

        {/* TARGETS */}
        <section className="container-edge pb-20">
          <Reveal>
            <h2 className="font-serif text-3xl md:text-4xl tracking-[-0.01em] mb-2">
              Targets
            </h2>
            <p className="text-ink/60 max-w-[62ch] mb-8">
              Five PDB structures spanning helical interfaces, viral antigens,
              flexible E3 handles, cytokine receptors, and a canonical PPI.
            </p>
            <div className="border-t border-ink/15">
              {TARGETS.map((t) => (
                <div
                  key={t.pdb}
                  className="grid grid-cols-[6.5rem_1fr] md:grid-cols-[7.5rem_1fr_2fr] gap-4 py-5 border-b border-ink/15"
                >
                  <span className="font-mono text-sm text-crane">{t.pdb}</span>
                  <span className="font-medium">{t.name}</span>
                  <span className="text-ink/60 text-sm md:col-span-1 col-span-2">
                    {t.note}
                  </span>
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        {/* TOOLS */}
        <section className="container-edge pb-20">
          <Reveal>
            <h2 className="font-serif text-3xl md:text-4xl tracking-[-0.01em] mb-2">
              Tools tested
            </h2>
            <p className="text-ink/60 max-w-[62ch] mb-8">
              Proposed evaluation set. Versions will be frozen before execution;
              runnable containers, weight references, and commit hashes must ship
              with the first live release.
            </p>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-x-8 gap-y-3 border-t border-ink/15 pt-6">
              {TOOLS.map((t) => (
                <div
                  key={t.name}
                  className="flex items-baseline justify-between gap-3 border-b border-ink/10 pb-2"
                >
                  <span className="font-medium">{t.name}</span>
                  <span className="font-mono text-xs text-ink/60">
                    {t.version}
                  </span>
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        {/* METRICS */}
        <section className="container-edge pb-20">
          <Reveal>
            <h2 className="font-serif text-3xl md:text-4xl tracking-[-0.01em] mb-2">
              Metrics
            </h2>
            <p className="text-ink/60 max-w-[62ch] mb-8">
              We rank with{" "}
              <span className="font-mono text-crane">ipSAE</span> and report
              the rest for context.
            </p>
            <div className="space-y-10">
              {METRICS.map((m) => (
                <div
                  key={m.name}
                  className="grid grid-cols-1 md:grid-cols-[12rem_1fr] gap-4 md:gap-10 border-t border-ink/15 pt-6"
                >
                  <div>
                    <div className="font-mono text-lg text-crane">
                      {m.name}
                    </div>
                    <div className="text-xs uppercase tracking-wider text-ink/50 mt-1">
                      {m.role}
                    </div>
                    <div className="font-mono text-xs text-ink/70 mt-2">
                      {m.auc}
                    </div>
                  </div>
                  <p className="text-ink/80 leading-relaxed max-w-[62ch]">
                    {m.def}
                  </p>
                </div>
              ))}
            </div>
          </Reveal>
        </section>

        {/* PROTOCOL */}
        <section className="container-edge pb-20">
          <Reveal>
            <h2 className="font-serif text-3xl md:text-4xl tracking-[-0.01em] mb-6">
              Protocol
            </h2>
            <ol className="space-y-6 max-w-[68ch]">
              <li className="grid grid-cols-[2.5rem_1fr] gap-4">
                <span className="font-mono text-sm text-ink/50 pt-1">01</span>
                <div>
                  <div className="font-medium">Generate</div>
                  <p className="text-ink/70 mt-1">
                    Each tool will run <span className="font-mono">N=50</span>{" "}
                    seeds per target with author-recommended defaults plus a
                    fixed hotspot panel per PDB. Sequence length sweeps are
                    declared up-front, never tuned post-hoc.
                  </p>
                </div>
              </li>
              <li className="grid grid-cols-[2.5rem_1fr] gap-4">
                <span className="font-mono text-sm text-ink/50 pt-1">02</span>
                <div>
                  <div className="font-medium">Validate</div>
                  <p className="text-ink/70 mt-1">
                    All designs will be predicted with{" "}
                    <span className="font-mono">Boltz-2</span> at{" "}
                    <span className="font-mono">recycles=3</span>,{" "}
                    <span className="font-mono">samples=5</span>. We keep the
                    top-1 by ipTM as the canonical structure.
                  </p>
                </div>
              </li>
              <li className="grid grid-cols-[2.5rem_1fr] gap-4">
                <span className="font-mono text-sm text-ink/50 pt-1">03</span>
                <div>
                  <div className="font-medium">Rerank</div>
                  <p className="text-ink/70 mt-1">
                    Candidates passing{" "}
                    <span className="font-mono">ipTM ≥ 0.50</span> are reranked
                    by <span className="font-mono">ipSAE</span>. Top-K per tool
                    will advance to the leaderboard.
                  </p>
                </div>
              </li>
              <li className="grid grid-cols-[2.5rem_1fr] gap-4">
                <span className="font-mono text-sm text-ink/50 pt-1">04</span>
                <div>
                  <div className="font-medium">Report</div>
                  <p className="text-ink/70 mt-1">
                    Per-tool means, medians, and full distributions will be
                    published. Cost (USD) and GPU-seconds will be measured on the
                    same A100-80GB instance class.
                  </p>
                </div>
              </li>
            </ol>
          </Reveal>
        </section>

        {/* REPRODUCIBILITY */}
        <section className="container-edge pb-20">
          <Reveal>
            <h2 className="font-serif text-3xl md:text-4xl tracking-[-0.01em] mb-6">
              Reproducibility
            </h2>
            <div className="grid md:grid-cols-2 gap-10 max-w-[80ch]">
              <div>
                <div className="text-xs uppercase tracking-wider text-ink/50 mb-2">
                  Live release requirements
                </div>
                <ul className="space-y-2 text-ink/80">
                  <li>- Exact tool versions &amp; commit hashes</li>
                  <li>- Per-target hotspot YAMLs</li>
                  <li>- All seeds, params, and configs</li>
                  <li>- Versioned prediction and rerank pipeline</li>
                  <li>- Raw outputs for every reported cell</li>
                </ul>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-ink/50 mb-2">
                  Public harness
                </div>
                <pre className="font-mono text-xs bg-ink/5 border border-ink/15 p-4 leading-relaxed overflow-x-auto">
{`Status: planned
Release gate: clean-environment rerun
Artifacts: configs, seeds, outputs, scores
Repository: linked when runnable`}
                </pre>
              </div>
            </div>
          </Reveal>
        </section>

        {/* HONESTY CARD */}
        <section className="container-edge pb-32">
          <Reveal>
            <div className="border-l-2 border-crane pl-6 max-w-[68ch]">
              <div className="text-xs uppercase tracking-wider text-crane mb-3">
                Limitations
              </div>
              <h2 className="font-serif text-2xl md:text-3xl tracking-[-0.01em] mb-4">
                We don&rsquo;t claim significance we can&rsquo;t defend.
              </h2>
              <ul className="space-y-3 text-ink/75 leading-relaxed">
                <li>
                  <span aria-hidden="true">• </span>In silico metrics are not wet-lab binding. The historical
                  pooled ipSAE estimate is target-confounded and is not a
                  guarantee on any target here.
                </li>
                <li>
                  <span aria-hidden="true">• </span>Per-target rankings can flip with{" "}
                  <span className="font-mono">N=50</span> seeds. Differences
                  inside the noise band are shown, not hidden.
                </li>
                <li>
                  <span aria-hidden="true">• </span>Cost and speed depend on instance class, queue, and
                  retries. A live release must publish raw runs so both can be
                  re-derived.
                </li>
                <li>
                  <span aria-hidden="true">• </span>When a tool fails on a target, we say so on the
                  leaderboard. We do not silently drop runs.
                </li>
              </ul>
            </div>
          </Reveal>
        </section>
      </main>
      <Footer />
    </>
  );
}
