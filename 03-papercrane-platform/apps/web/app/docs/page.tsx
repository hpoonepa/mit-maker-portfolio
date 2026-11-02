import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "Docs";
const DESCRIPTION =
  "Paper Crane documentation — API reference, tool guides, and end-to-end campaign tutorials.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/docs",
  ogTitle: "Docs",
  ogDesc: "API reference. Tool guides. Campaign tutorials.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Docs", path: "/docs" },
];

// ---------- Sidebar nav model ----------
type NavItem = { label: string; href: string; status?: "todo" | "ready" };
type NavSection = { title: string; items: NavItem[] };

const NAV: NavSection[] = [
  {
    title: "Get started",
    items: [
      { label: "Introduction", href: "/docs", status: "ready" },
      { label: "Quickstart", href: "/docs/quickstart", status: "todo" },
      { label: "Concepts", href: "/docs/concepts", status: "todo" },
      { label: "Pricing & quotas", href: "/pricing", status: "ready" },
    ],
  },
  {
    title: "Campaigns",
    items: [
      { label: "Designing a binder", href: "/docs/campaigns/binder", status: "todo" },
      { label: "Hotspots & targets", href: "/docs/campaigns/hotspots", status: "todo" },
      { label: "Filtering & ranking", href: "/docs/campaigns/ranking", status: "todo" },
      { label: "Wet-lab handoff", href: "/docs/campaigns/handoff", status: "todo" },
    ],
  },
  {
    title: "API reference",
    items: [
      { label: "Authentication", href: "/docs/api/auth", status: "todo" },
      { label: "Jobs", href: "/docs/api/jobs", status: "todo" },
      { label: "Webhooks", href: "/docs/api/webhooks", status: "todo" },
      { label: "Errors", href: "/docs/api/errors", status: "todo" },
    ],
  },
];

// ---------- Tool catalog ----------
type Tool = {
  slug: string;
  name: string;
  family: "Generation" | "Sequence" | "Structure" | "Embedding";
  blurb: string;
};

const TOOLS: Tool[] = [
  { slug: "rfdiffusion", name: "RFdiffusion", family: "Generation", blurb: "Diffusion-based de novo backbones with hotspot conditioning." },
  { slug: "bindcraft", name: "BindCraft", family: "Generation", blurb: "End-to-end binder hallucination with built-in AF2 validation." },
  { slug: "boltzgen", name: "BoltzGen", family: "Generation", blurb: "All-atom diffusion design — side-chain aware from step zero." },
  { slug: "chroma", name: "Chroma", family: "Generation", blurb: "Programmable structure generation with conditional sampling." },
  { slug: "proteinmpnn", name: "ProteinMPNN", family: "Sequence", blurb: "Inverse-folding sequence design for any backbone." },
  { slug: "ligandmpnn", name: "LigandMPNN", family: "Sequence", blurb: "Ligand-aware sequence design for active sites and pockets." },
  { slug: "solublempnn", name: "SolubleMPNN", family: "Sequence", blurb: "Solubility-tuned MPNN — biased away from aggregation." },
  { slug: "alphafold3", name: "AlphaFold 3", family: "Structure", blurb: "Multi-modal complex prediction across protein, NA, ligand." },
  { slug: "boltz1", name: "Boltz-1", family: "Structure", blurb: "Open biomolecular structure prediction at AF2-class accuracy." },
  { slug: "boltz2", name: "Boltz-2", family: "Structure", blurb: "Affinity-aware successor with improved interface scoring." },
  { slug: "chai1", name: "Chai-1", family: "Structure", blurb: "Foundation model for protein, ligand, and nucleic-acid complexes." },
  { slug: "esm2", name: "ESM-2", family: "Embedding", blurb: "Protein language model — embeddings, PLL, zero-shot scoring." },
];

const FAMILY_ORDER: Tool["family"][] = ["Generation", "Sequence", "Structure", "Embedding"];

// ---------- Page ----------
export default function DocsPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-28 md:pt-32">
        <div className="container-edge pb-24">
          {/* breadcrumb / search row */}
          <div className="mb-8 flex items-center justify-between gap-6 text-[13px]">
            <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-graphite">
              <Link href="/" className="hover:text-ink transition">Home</Link>
              <span aria-hidden className="text-graphite/50">/</span>
              <span className="text-ink">Docs</span>
            </nav>
            <DocsSearchStub />
          </div>

          {/* Three-column docs shell */}
          <div className="grid grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)_200px] gap-x-12">
            {/* Left: section nav */}
            <aside className="hidden lg:block sticky top-28 self-start max-h-[calc(100vh-8rem)] overflow-y-auto pr-2">
              <DocsNav active="/docs" />
            </aside>

            {/* Center: reading column */}
            <article className="min-w-0 max-w-[68ch]">
              <Reveal>
                <span className="eyebrow">§ Docs</span>
                <h1 className="mt-4 font-display text-[clamp(40px,5.4vw,64px)] leading-[1.05] text-ink">
                  Build binders. Ship them.
                </h1>
                <p className="mt-5 text-graphite text-[17px] leading-[1.7]">
                  Paper Crane catalogs 52 protein tools behind one authenticated
                  API, with GA and beta readiness shown explicitly. These docs
                  cover the platform end-to-end — from your first hotspot pick
                  to a wet-lab-ready ranked list.
                </p>

                <div className="mt-8 flex flex-wrap gap-3 text-[13px]">
                  <Link
                    href="/docs/quickstart"
                    className="rounded-full bg-crane px-4 py-2 text-paper hover:bg-crane/90 transition"
                  >
                    Get started in 5 minutes →
                  </Link>
                  <Link
                    href="/docs/api/auth"
                    className="rounded-full border border-lattice px-4 py-2 text-ink hover:bg-paper-fold transition"
                  >
                    API reference
                  </Link>
                  <Link
                    href="https://app.papercrane.bio"
                    className="rounded-full border border-lattice px-4 py-2 text-ink hover:bg-paper-fold transition"
                  >
                    Open the app
                  </Link>
                </div>

                {/* Callout: info */}
                <Callout kind="info" title="Public docs are folding in stages.">
                  Stub pages below are marked <code className="font-mono text-[12px]">TODO</code>.
                  The fastest path today is the in-app onboarding.
                </Callout>

                {/* Quick start preview / code */}
                <h2 id="quickstart" className="mt-14 font-sans text-[22px] tracking-tight text-ink">
                  Quickstart
                </h2>
                <p className="mt-3 text-graphite text-[15.5px] leading-[1.7]">
                  Authenticate, post a target, watch the campaign fold. The same
                  call works against every model in the catalog.
                </p>
                <CodeBlock
                  lang="bash"
                  code={`curl https://api.papercrane.bio/v1/jobs \\
  -H "Authorization: Bearer $PAPERCRANE_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "tool": "bindcraft",
    "target_pdb": "2LGV",
    "hotspots": ["A47","A52","A55"],
    "n_designs": 100
  }'`}
                />

                {/* Tools index */}
                <h2 id="tools" className="mt-14 font-sans text-[22px] tracking-tight text-ink">
                  Tool catalog
                </h2>
                <p className="mt-3 text-graphite text-[15.5px] leading-[1.7]">
                  The complete <Link href="/tools" className="text-ink underline decoration-lattice-strong underline-offset-4 hover:decoration-crane">52-tool catalog</Link> lives on the public tools index; this page highlights the core models by stage of your pipeline.
                </p>
                <ToolGrid />

                {/* Prev / Next */}
                <nav
                  aria-label="Pagination"
                  className="mt-16 grid grid-cols-1 sm:grid-cols-2 gap-3 border-t border-lattice pt-6 text-[13px]"
                >
                  <span className="opacity-50">← You are at the start</span>
                  <Link
                    href="/docs/quickstart"
                    className="sm:text-right text-ink hover:text-crane transition"
                  >
                    Quickstart →
                  </Link>
                </nav>
              </Reveal>
            </article>

            {/* Right: on-this-page */}
            <aside className="hidden lg:block sticky top-28 self-start max-h-[calc(100vh-8rem)] overflow-y-auto text-[12.5px]">
              <p className="eyebrow mb-3">On this page</p>
              <ul className="space-y-2 text-graphite">
                <li><a href="#quickstart" className="hover:text-crane transition">Quickstart</a></li>
                <li><a href="#tools" className="hover:text-crane transition">Tool catalog</a></li>
              </ul>
            </aside>
          </div>

          {/* Mobile sidebar drawer (CSS-only) */}
          <details className="lg:hidden mt-12 rounded-2xl border border-lattice bg-paper-fold/40">
            <summary className="cursor-pointer list-none px-5 py-3 text-[13px] text-ink flex items-center justify-between">
              <span>Browse all docs</span>
              <span aria-hidden className="text-graphite">▾</span>
            </summary>
            <div className="px-5 pb-5">
              <DocsNav active="/docs" />
            </div>
          </details>
        </div>
      </main>
      <Footer />
    </>
  );
}

// ---------- Components ----------

function DocsSearchStub() {
  return (
    <label className="relative hidden md:flex items-center w-[260px]">
      <span className="sr-only">Search docs</span>
      <input
        type="search"
        placeholder="Search docs"
        aria-label="Search docs"
        className="w-full rounded-full border border-lattice bg-paper-fold/60 px-4 py-1.5 text-[13px] text-ink placeholder:text-graphite/70 focus:outline-none focus:border-crane/60 focus:bg-paper transition"
      />
      <kbd className="absolute right-3 font-mono text-[10.5px] text-graphite/80 border border-lattice rounded px-1.5 py-px bg-paper">
        ⌘K
      </kbd>
    </label>
  );
}

function DocsNav({ active }: { active: string }) {
  return (
    <nav aria-label="Docs sections" className="text-[13px]">
      {NAV.map((section) => (
        <div key={section.title} className="mb-6">
          <p className="eyebrow mb-2">{section.title}</p>
          <ul className="space-y-1.5">
            {section.items.map((item) => {
              const isActive = item.href === active;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={
                      isActive
                        ? "text-crane font-medium"
                        : "text-graphite hover:text-ink transition"
                    }
                  >
                    {item.label}
                  </Link>
                  {item.status === "todo" && (
                    <span className="ml-2 font-mono text-[10px] text-graphite/60 align-middle">
                      TODO
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function Callout({
  kind,
  title,
  children,
}: {
  kind: "info" | "warning" | "danger";
  title: string;
  children: React.ReactNode;
}) {
  const tone =
    kind === "danger"
      ? "border-crane/40 bg-crane/[0.04]"
      : kind === "warning"
        ? "border-amber-500/40 bg-amber-500/[0.05]"
        : "border-lattice bg-paper-fold/50";
  return (
    <aside
      role="note"
      className={`mt-8 rounded-2xl border ${tone} px-5 py-4 text-[14px] leading-[1.6] text-ink`}
    >
      <p className="font-medium">{title}</p>
      <div className="mt-1 text-graphite">{children}</div>
    </aside>
  );
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  return (
    <figure className="mt-6 overflow-hidden rounded-2xl border border-ink/10 bg-ink text-paper">
      <figcaption className="flex items-center justify-between border-b border-paper/10 px-4 py-2 font-mono text-[11px] text-paper/60">
        <span>{lang}</span>
        <span aria-hidden>•••</span>
      </figcaption>
      <pre className="overflow-x-auto px-4 py-4 text-[12.5px] leading-[1.65]">
        <code className="font-mono">{code}</code>
      </pre>
    </figure>
  );
}

function ToolGrid() {
  return (
    <div className="mt-6 space-y-8">
      {FAMILY_ORDER.map((family) => {
        const items = TOOLS.filter((t) => t.family === family);
        return (
          <div key={family}>
            <p className="eyebrow mb-3">{family}</p>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-px bg-lattice rounded-2xl overflow-hidden border border-lattice">
              {items.map((tool) => (
                <li key={tool.slug} className="bg-paper hover:bg-paper-fold/60 transition">
                  <Link
                    href={`/docs/tools/${tool.slug}`}
                    className="block px-5 py-4"
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-ink text-[15px]">{tool.name}</span>
                      <span className="font-mono text-[10.5px] text-graphite/70">
                        /docs/tools/{tool.slug}
                      </span>
                    </div>
                    <p className="mt-1 text-graphite text-[13.5px] leading-[1.55]">
                      {tool.blurb}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
