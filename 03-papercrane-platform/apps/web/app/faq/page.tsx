import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "FAQ";
const DESCRIPTION =
  "Answers about Paper Crane beta access, supported tools, BYOK Modal compute, scoring, data privacy, and reproducibility.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/faq",
  ogTitle: "FAQ",
  ogDesc: "Beta · Tools · Pricing · Compute · Privacy · Reproducibility.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "FAQ", path: "/faq" },
];

type QA = { q: string; a: React.ReactNode };
type Category = { id: string; title: string; items: QA[] };

const CATEGORIES: Category[] = [
  {
    id: "beta",
    title: "Beta access",
    items: [
      {
        q: "What's in the beta?",
        a: (
          <>
            A hosted workflow surface for the binder-design pipeline we run for
            our own campaigns: target intake, tool orchestration (RFdiffusion,
            ProteinMPNN, BindCraft, BoltzGen), structure prediction (Boltz-2,
            Chai-1, AlphaFold2), and ranking with ipSAE / iPTM / pDockQ. No
            wet-lab automation, no LIMS.
          </>
        ),
      },
      {
        q: "How do I get access?",
        a: (
          <>
            Request an invite from the homepage or email{" "}
            <a className="underline" href="mailto:beta@papercrane.bio">
              beta@papercrane.bio
            </a>
            . iGEM teams and academic labs are prioritized while the beta is
            capacity-limited.
          </>
        ),
      },
      {
        q: "Who is the beta for right now?",
        a: (
          <>
            Computational protein-design groups with a defined target and the
            ability to evaluate predictions. We are not a fit yet for teams
            without a structural-biology background.
          </>
        ),
      },
    ],
  },
  {
    id: "tools",
    title: "Tools",
    items: [
      {
        q: "Which tools can I run?",
        a: (
          <>
            RFdiffusion, ProteinMPNN / SolubleMPNN / LigandMPNN, BindCraft,
            BoltzGen for design; Boltz-1/2, Chai-1, and AlphaFold2 / AF-Multimer
            for prediction; Foldseek and ESM2 for retrieval and scoring; ipSAE
            for ranking. The set tracks what we use internally.
          </>
        ),
      },
      {
        q: "Can I add a tool that isn't on the list?",
        a: (
          <>
            During beta, custom tools land case-by-case. If it runs in a
            container and accepts a sequence or structure, it can usually be
            wired in. Tell us what you need.
          </>
        ),
      },
      {
        q: "Do you support multi-step workflows?",
        a: (
          <>
            Yes. A run is a DAG of steps, each step is a single tool, and
            outputs of one step are addressable inputs to the next. The same
            graph executes locally, on Modal, or on Vast.ai.
          </>
        ),
      },
    ],
  },
  {
    id: "compute",
    title: "Compute (BYOK Modal)",
    items: [
      {
        q: "Do I need my own GPU?",
        a: (
          <>
            No. Default execution uses a shared backend with metered usage. If
            you want full control over cost and quotas, bring your own.
          </>
        ),
      },
      {
        q: "Can I bring my own Modal account?",
        a: (
          <>
            Yes. Paste a Modal token and runs execute under your workspace -
            your quota, your billing, your logs. We never proxy your token. The
            same pattern works for Vast.ai instance keys.
          </>
        ),
      },
      {
        q: "What happens if a job fails mid-run?",
        a: (
          <>
            Each step is idempotent and content-addressed. Reruns skip steps
            whose inputs haven&apos;t changed; failures surface with the underlying
            tool&apos;s stderr, not a wrapped error.
          </>
        ),
      },
    ],
  },
  {
    id: "scoring",
    title: "Scoring",
    items: [
      {
        q: "How do you score binders?",
        a: (
          <>
            Predictions are run through Boltz-2 or Chai-1 (and AF2 when
            requested), then ranked by a composite of interface metrics. ipSAE
            is the primary signal; iPTM and pDockQ are reported alongside.
            Thresholds are user-configurable per campaign.
          </>
        ),
      },
      {
        q: "What's ipSAE?",
        a: (
          <>
            ipSAE: interprotein Score from Aligned Errors: is a binder-ranking
            metric derived from the predicted aligned-error matrix at the
            interface. We surface it because, in our hands and in the
            literature it draws on, it discriminates real interfaces better than
            iPTM alone.
          </>
        ),
      },
      {
        q: "Do you publish your filtering thresholds?",
        a: (
          <>
            Yes. Default thresholds and the rationale behind them live in the
            docs. You can override any of them per run.
          </>
        ),
      },
    ],
  },
  {
    id: "privacy",
    title: "Data privacy",
    items: [
      {
        q: "Where is my data stored?",
        a: (
          <>
            Sequences, structures, and run artifacts are stored in object
            storage scoped to your workspace. Logs and metadata sit in our
            primary database. See the{" "}
            <Link className="underline" href="/privacy">
              privacy policy
            </Link>{" "}
            for region and retention details.
          </>
        ),
      },
      {
        q: "Do you train on my designs?",
        a: <>No. Customer designs are not used to train models.</>,
      },
      {
        q: "Can I export my designs?",
        a: (
          <>
            Yes. Every run exports as a folder of FASTA, PDB / CIF, JSON
            metrics, and the full run manifest. There is no proprietary file
            format and no export wall.
          </>
        ),
      },
      {
        q: "Can I delete my data?",
        a: (
          <>
            Yes. Workspace deletion removes artifacts and metadata; backups age
            out per the retention schedule in the privacy policy.
          </>
        ),
      },
    ],
  },
  {
    id: "reproducibility",
    title: "Reproducibility",
    items: [
      {
        q: "What's the public benchmark?",
        a: (
          <>
            A pre-registered comparison of design pipelines on a fixed set of
            targets, scored with the same metrics and seeds for everyone. The
            methodology is published and frozen before any result is scored;
            runs are not published yet. See{" "}
            <Link className="underline" href="/benchmark">
              /benchmark
            </Link>{" "}
            for the specification and release criteria.
          </>
        ),
      },
      {
        q: "Are runs reproducible?",
        a: (
          <>
            Each run pins tool versions, container digests, seeds, and inputs
            into a manifest. Re-running the manifest on the same backend
            reproduces the artifacts; switching backends reproduces the
            sequences and structures up to nondeterminism documented per tool.
          </>
        ),
      },
      {
        q: "Do you offer pricing for academic labs?",
        a: (
          <>
            Yes. Free for iGEM teams and academics. Lab and pharma tiers are on
            the{" "}
            <Link className="underline" href="/pricing">
              pricing page
            </Link>
            .
          </>
        ),
      },
    ],
  },
];

function fmtNum(n: number) {
  return `Q${n.toString().padStart(2, "0")}`;
}

export default function FAQPage() {
  let counter = 0;
  const total = CATEGORIES.reduce((n, c) => n + c.items.length, 0);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-32 md:pt-40">
        <section className="container-edge pb-16">
          <Reveal>
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2 mb-10">
              <span className="eyebrow">FAQ · {total} questions</span>
              <span className="h-px flex-1 min-w-[2rem] bg-lattice" />
              <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
                {CATEGORIES.length} CATEGORIES
              </span>
            </div>
            <h1 className="font-fraunces text-5xl md:text-7xl leading-[0.95] tracking-tight max-w-4xl">
              Questions, folded once.
            </h1>
            <p className="mt-6 max-w-2xl text-graphite-soft text-lg leading-relaxed">
              Short answers about beta access, supported tools, compute,
              scoring, privacy, and reproducibility. If something here is wrong
              or missing, write to{" "}
              <a className="underline" href="mailto:hello@papercrane.bio">
                hello@papercrane.bio
              </a>
              .
            </p>
          </Reveal>
        </section>

        <section className="container-edge pb-24">
          <nav aria-label="FAQ categories" className="mb-12">
            <ul className="flex flex-wrap gap-x-6 gap-y-2 font-mono text-[11px] tracking-[0.18em] uppercase text-graphite-soft">
              {CATEGORIES.map((cat) => (
                <li key={cat.id}>
                  <a className="hover:text-graphite" href={`#${cat.id}`}>
                    {cat.title}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <div className="space-y-20">
            {CATEGORIES.map((cat) => (
              <section key={cat.id} id={cat.id} aria-labelledby={`${cat.id}-h`}>
                <Reveal>
                  <div className="flex items-baseline gap-4 mb-6">
                    <h2
                      id={`${cat.id}-h`}
                      className="font-fraunces text-3xl md:text-4xl tracking-tight"
                    >
                      {cat.title}
                    </h2>
                    <span className="h-px flex-1 bg-lattice" />
                    <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-graphite-soft">
                      {cat.items.length} Q
                    </span>
                  </div>

                  <dl className="border-t border-lattice">
                    {cat.items.map((item) => {
                      counter += 1;
                      const num = fmtNum(counter);
                      return (
                        <details
                          key={num}
                          className="group border-b border-lattice"
                        >
                          <summary className="flex cursor-pointer list-none items-baseline gap-4 py-5 outline-none focus-visible:ring-2 focus-visible:ring-graphite/40">
                            <dt className="contents">
                              <span className="font-mono text-[11px] tracking-[0.2em] uppercase text-graphite-soft shrink-0 w-10">
                                {num}
                              </span>
                              <span className="font-fraunces text-xl md:text-2xl leading-snug flex-1">
                                {item.q}
                              </span>
                              <span
                                aria-hidden
                                className="font-mono text-graphite-soft transition-transform group-open:rotate-45"
                              >
                                +
                              </span>
                            </dt>
                          </summary>
                          <dd className="pb-6 pl-14 pr-8 text-graphite-soft leading-relaxed max-w-3xl">
                            {item.a}
                          </dd>
                        </details>
                      );
                    })}
                  </dl>
                </Reveal>
              </section>
            ))}
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
