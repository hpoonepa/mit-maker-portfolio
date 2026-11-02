import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "Getting started";
const DESCRIPTION =
  "Run your first Paper Crane campaign in five minutes — sign up, pick a target, place hotspots, submit a job, browse ranked designs.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/docs/getting-started",
  ogTitle: "Getting started",
  ogDesc: "From signup to ranked designs in five minutes.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Docs", path: "/docs" },
  { name: "Getting started", path: "/docs/getting-started" },
];

// ---------- Sidebar nav model (mirrors /docs) ----------
type NavItem = { label: string; href: string; status?: "todo" | "ready" };
type NavSection = { title: string; items: NavItem[] };

const NAV: NavSection[] = [
  {
    title: "Get started",
    items: [
      { label: "Introduction", href: "/docs", status: "ready" },
      {
        label: "Getting started",
        href: "/docs/getting-started",
        status: "ready",
      },
      { label: "Concepts", href: "/docs/concepts", status: "todo" },
      { label: "Pricing & quotas", href: "/pricing", status: "ready" },
    ],
  },
  {
    title: "Campaigns",
    items: [
      {
        label: "Designing a binder",
        href: "/docs/campaigns/binder",
        status: "todo",
      },
      {
        label: "Hotspots & targets",
        href: "/docs/campaigns/hotspots",
        status: "todo",
      },
      {
        label: "Filtering & ranking",
        href: "/docs/campaigns/ranking",
        status: "todo",
      },
      {
        label: "Wet-lab handoff",
        href: "/docs/campaigns/handoff",
        status: "todo",
      },
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

// ---------- Page ----------
export default function GettingStartedPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)),
        }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-28 md:pt-32">
        <div className="container-edge pb-24">
          {/* breadcrumb row */}
          <div className="mb-8 flex items-center justify-between gap-6 text-[13px]">
            <nav
              aria-label="Breadcrumb"
              className="flex items-center gap-2 text-graphite"
            >
              <Link href="/" className="hover:text-ink transition">
                Home
              </Link>
              <span aria-hidden className="text-graphite/50">
                /
              </span>
              <Link href="/docs" className="hover:text-ink transition">
                Docs
              </Link>
              <span aria-hidden className="text-graphite/50">
                /
              </span>
              <span className="text-ink">Getting started</span>
            </nav>
          </div>

          {/* Three-column docs shell */}
          <div className="grid grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)_200px] gap-x-12">
            {/* Left: section nav */}
            <aside className="hidden lg:block sticky top-28 self-start max-h-[calc(100vh-8rem)] overflow-y-auto pr-2">
              <DocsNav active="/docs/getting-started" />
            </aside>

            {/* Center: reading column */}
            <article className="min-w-0 max-w-[68ch]">
              <Reveal>
                <span className="eyebrow">§ Get started</span>
                <h1 className="mt-4 font-display text-[clamp(40px,5.4vw,64px)] leading-[1.05] text-ink">
                  Getting started in 5 minutes.
                </h1>
                <p className="mt-5 text-graphite text-[17px] leading-[1.7]">
                  Five steps from a fresh account to a ranked list of designs
                  ready for the wet lab. No installs — every model runs on our
                  infrastructure.
                </p>

                {/* 1. Sign up */}
                <section className="mt-14 border-t border-lattice pt-12">
                  <p className="eyebrow">Step 01</p>
                  <h2
                    id="sign-up"
                    className="mt-2 font-display text-[28px] tracking-tight text-ink"
                  >
                    Sign up
                  </h2>
                  <p className="mt-4 text-graphite text-[15.5px] leading-[1.7]">
                    Paper Crane is in private beta. Create an account at{" "}
                    <Link href="/signup" className="text-crane hover:underline">
                      papercrane.bio/signup
                    </Link>{" "}
                    and you&apos;ll receive an invite link once your beta access
                    is approved — usually within a business day.
                  </p>
                  <p className="mt-3 text-graphite text-[15.5px] leading-[1.7]">
                    Already approved? Skip ahead and sign in at{" "}
                    <Link
                      href="https://app.papercrane.bio"
                      className="text-crane hover:underline"
                    >
                      app.papercrane.bio
                    </Link>
                    .
                  </p>
                </section>

                {/* 2. Pick a target */}
                <section className="mt-14 border-t border-lattice pt-12">
                  <p className="eyebrow">Step 02</p>
                  <h2
                    id="pick-a-target"
                    className="mt-2 font-display text-[28px] tracking-tight text-ink"
                  >
                    Pick a target
                  </h2>
                  <p className="mt-4 text-graphite text-[15.5px] leading-[1.7]">
                    Open{" "}
                    <span className="font-mono text-[13px]">New campaign</span>{" "}
                    and tell Paper Crane what you want to bind. The fastest path
                    is a four-character RCSB PDB ID; you can also drag in a
                    local <span className="font-mono text-[13px]">.pdb</span> or{" "}
                    <span className="font-mono text-[13px]">.cif</span> file —
                    AlphaFold structures and cryo-EM models both work.
                  </p>
                  <CodeBlock
                    lang="bash"
                    code={`# Or via the API
curl https://api.papercrane.bio/v1/targets \\
  -H "Authorization: Bearer $PAPERCRANE_KEY" \\
  -d '{ "pdb_id": "2LGV" }'`}
                  />
                </section>

                {/* 3. Choose hotspots */}
                <section className="mt-14 border-t border-lattice pt-12">
                  <p className="eyebrow">Step 03</p>
                  <h2
                    id="choose-hotspots"
                    className="mt-2 font-display text-[28px] tracking-tight text-ink"
                  >
                    Choose hotspots
                  </h2>
                  <p className="mt-4 text-graphite text-[15.5px] leading-[1.7]">
                    The structure loads into an in-browser Mol* viewer. Click
                    residues on the surface to mark them as hotspots — the
                    backbone-design models will steer interfaces toward the
                    patch you select.
                  </p>
                  <p className="mt-3 text-graphite text-[15.5px] leading-[1.7]">
                    Three to six contiguous residues is a good starting point.
                    Hotspots are stored as chain-prefixed residue IDs:
                  </p>
                  <CodeBlock
                    lang="json"
                    code={`{
  "hotspots": [{ "chain": "A", "residues": [47, 52, 55] }]
}`}
                  />
                </section>

                {/* 4. Submit a job */}
                <section className="mt-14 border-t border-lattice pt-12">
                  <p className="eyebrow">Step 04</p>
                  <h2
                    id="submit-a-job"
                    className="mt-2 font-display text-[28px] tracking-tight text-ink"
                  >
                    Submit a job
                  </h2>
                  <p className="mt-4 text-graphite text-[15.5px] leading-[1.7]">
                    Pick a tool from the catalog (BindCraft is a strong default
                    for first-time users), set the number of designs, and hit{" "}
                    <span className="font-mono text-[13px]">Submit</span>. Jobs
                    queue immediately and stream progress to the dashboard.
                  </p>
                  <CodeBlock
                    lang="bash"
                    code={`curl https://api.papercrane.bio/v1/jobs \\
  -H "Authorization: Bearer $PAPERCRANE_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "toolId": "bindcraft",
    "request": {
      "targetPdb": "2LGV",
      "targetChain": "A",
      "hotspots": [{ "chain": "A", "residues": [47, 52, 55] }],
      "numDesigns": 5,
      "seeds": [1, 2, 3, 4, 5]
    }
  }'`}
                  />
                </section>

                {/* 5. Browse results */}
                <section className="mt-14 border-t border-lattice pt-12">
                  <p className="eyebrow">Step 05</p>
                  <h2
                    id="browse-results"
                    className="mt-2 font-display text-[28px] tracking-tight text-ink"
                  >
                    Browse results
                  </h2>
                  <p className="mt-4 text-graphite text-[15.5px] leading-[1.7]">
                    When the campaign finishes, designs are ranked by ipSAE —
                    our default interface confidence score — alongside ipTM,
                    pLDDT, and pAE. Sort, filter, and inspect each design in the
                    same Mol* viewer you used to set hotspots.
                  </p>
                  <p className="mt-3 text-graphite text-[15.5px] leading-[1.7]">
                    Ready to order? Export your shortlist as FASTA for synthesis
                    or CIF for structural follow-up.
                  </p>
                  <CodeBlock
                    lang="bash"
                    code={`# Export top-10 designs as FASTA
curl https://api.papercrane.bio/v1/jobs/$JOB_ID/export?format=fasta&top=10 \\
  -H "Authorization: Bearer $PAPERCRANE_KEY" \\
  -o designs.fasta`}
                  />
                </section>

                {/* Prev / Next */}
                <nav
                  aria-label="Pagination"
                  className="mt-16 grid grid-cols-1 sm:grid-cols-2 gap-3 border-t border-lattice pt-6 text-[13px]"
                >
                  <Link
                    href="/docs"
                    className="text-ink hover:text-crane transition"
                  >
                    ← Introduction
                  </Link>
                  <Link
                    href="/docs/api/auth"
                    className="sm:text-right text-ink hover:text-crane transition"
                  >
                    Authentication →
                  </Link>
                </nav>
              </Reveal>
            </article>

            {/* Right: on-this-page */}
            <aside className="hidden lg:block sticky top-28 self-start max-h-[calc(100vh-8rem)] overflow-y-auto text-[12.5px]">
              <p className="eyebrow mb-3">On this page</p>
              <ul className="space-y-2 text-graphite">
                <li>
                  <a href="#sign-up" className="hover:text-crane transition">
                    1. Sign up
                  </a>
                </li>
                <li>
                  <a
                    href="#pick-a-target"
                    className="hover:text-crane transition"
                  >
                    2. Pick a target
                  </a>
                </li>
                <li>
                  <a
                    href="#choose-hotspots"
                    className="hover:text-crane transition"
                  >
                    3. Choose hotspots
                  </a>
                </li>
                <li>
                  <a
                    href="#submit-a-job"
                    className="hover:text-crane transition"
                  >
                    4. Submit a job
                  </a>
                </li>
                <li>
                  <a
                    href="#browse-results"
                    className="hover:text-crane transition"
                  >
                    5. Browse results
                  </a>
                </li>
              </ul>
            </aside>
          </div>

          {/* Mobile sidebar drawer */}
          <details className="lg:hidden mt-12 rounded-2xl border border-lattice bg-paper-fold/40">
            <summary className="cursor-pointer list-none px-5 py-3 text-[13px] text-ink flex items-center justify-between">
              <span>Browse all docs</span>
              <span aria-hidden className="text-graphite">
                ▾
              </span>
            </summary>
            <div className="px-5 pb-5">
              <DocsNav active="/docs/getting-started" />
            </div>
          </details>
        </div>
      </main>
      <Footer />
    </>
  );
}

// ---------- Components ----------

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
