import type { Metadata } from "next";
import Link from "next/link";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/sections/Footer";
import { Reveal } from "@/components/Reveal";
import { pageMetadata } from "@/lib/metadata";
import { breadcrumbJsonLd, jsonLdString } from "@/lib/structured-data";

const TITLE = "CLI quickstart";
const DESCRIPTION =
  "Install the Paper Crane CLI, authenticate, submit a design job, and export results: all from your terminal.";

export const metadata: Metadata = pageMetadata({
  title: TITLE,
  description: DESCRIPTION,
  path: "/docs/cli",
  ogTitle: "Paper Crane CLI",
  ogDesc: "Install. Authenticate. Submit. Export.",
});

const BREADCRUMBS = [
  { name: "Home", path: "/" },
  { name: "Docs", path: "/docs" },
  { name: "CLI", path: "/docs/cli" },
];

type Step = {
  id: string;
  title: string;
  blurb: string;
  command: string;
  output: string;
  note?: string;
};

const STEPS: Step[] = [
  {
    id: "install",
    title: "Install",
    blurb:
      "Homebrew is the recommended path on macOS and Linux. An npm fallback is provided for CI runners and Windows.",
    command: `# Homebrew (recommended)
brew install papercrane-bio/papercrane/papercrane

# npm fallback
npm i -g @papercrane/cli`,
    output: `==> Pouring papercrane--0.4.2.arm64_sonoma.bottle.tar.gz
  /opt/homebrew/Cellar/papercrane/0.4.2: 14 files, 8.7MB
papercrane --version
0.4.2`,
  },
  {
    id: "authenticate",
    title: "Authenticate",
    blurb:
      "papercrane login opens your browser to a one-time auth callback. The token is written to ~/.config/papercrane/config.toml with mode 600.",
    command: `papercrane login`,
    output: `? How would you like to log in?
  > OAuth (open browser)
    Paste API key
i Open this URL in your browser:
  https://api.papercrane.bio/cli-auth?cb=…
✓ API key saved to ~/.config/papercrane/config.toml (chmod 600)
i Logged in as you@lab.org (Org: rosen-lab, Tier: pro)`,
    note: "For CI, pass --api-key non-interactively or set PAPERCRANE_API_KEY.",
  },
  {
    id: "submit",
    title: "Submit a job",
    blurb:
      "One call. Pick a project, a tool, a target, and the hotspots that matter. The CLI returns the job id immediately and queues the run.",
    command: `papercrane jobs submit \\
  --project pdl1-binders \\
  --tools boltzgen \\
  --target 5J89 \\
  --hotspots A:42,A:87 \\
  --num-designs 1`,
    output: `⠋ submitting job
✓ submitted job_8f3c1a92ee → queued`,
  },
  {
    id: "list",
    title: "List jobs",
    blurb:
      "See what's running, done, or failed. Filter by status and pipe --json into jq for scripting.",
    command: `papercrane jobs list --status running`,
    output: `ID            TOOL       STATUS    DESIGNS  SUBMITTED
job_8f3c1a92  boltzgen   running   0/1      2026-04-29 14:11`,
  },
  {
    id: "export",
    title: "Export designs",
    blurb:
      "Pull a multi-FASTA of every design from a job (or filter by project), or download a single structure as cif/pdb/fasta for downstream tools.",
    command: `# Multi-FASTA of a whole job
papercrane designs export-fasta \\
  --job job_8f3c1a92ee \\
  --out designs.fasta

# Single structure
papercrane designs download des_91f0a2 --format fasta`,
    output: `✓ wrote 87 sequences → designs.fasta
✓ saved ./des_91f0a2.fasta`,
  },
  {
    id: "keys",
    title: "API keys",
    blurb:
      "API keys (with scopes like designs:read, jobs:write) are issued and revoked from the dashboard. Once you have a key, papercrane login --api-key <KEY> wires it into your shell config.",
    command: `# After creating a key in the dashboard:
papercrane login --api-key pcr_live_… `,
    output: `✓ API key saved to ~/.config/papercrane/config.toml (chmod 600)
i Logged in as ci-bot@lab.org (Org: rosen-lab, Tier: pro)`,
    note: "Programmatic key creation lands with the v0.5 CLI: use the dashboard for now.",
  },
];

export default function CliDocsPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdString(breadcrumbJsonLd(BREADCRUMBS)) }}
      />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="relative pt-28 md:pt-32">
        <div className="container-edge pb-24">
          {/* breadcrumb */}
          <div className="mb-8 flex items-center justify-between gap-6 text-[13px]">
            <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-graphite">
              <Link href="/" className="hover:text-ink transition">Home</Link>
              <span aria-hidden className="text-graphite/50">/</span>
              <Link href="/docs" className="hover:text-ink transition">Docs</Link>
              <span aria-hidden className="text-graphite/50">/</span>
              <span className="text-ink">CLI</span>
            </nav>
          </div>

          {/* Two-column shell: reading column + on-this-page */}
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_200px] gap-x-12">
            <article className="min-w-0 max-w-[72ch]">
              <Reveal>
                <span className="eyebrow">CLI</span>
                <h1 className="mt-4 font-display text-[clamp(36px,4.6vw,56px)] leading-[1.05] text-ink">
                  papercrane, in your terminal.
                </h1>
                <p className="mt-5 text-graphite text-[17px] leading-[1.7]">
                  The CLI is the fastest path from a target PDB to a ranked
                  FASTA. Everything you can do in the dashboard: submit
                  campaigns, watch logs, pull designs: is one command away.
                </p>

                <div className="mt-8 flex flex-wrap gap-3 text-[13px]">
                  <a
                    href="#install"
                    className="rounded-full bg-crane px-4 py-2 text-paper hover:bg-crane/90 transition"
                  >
                    Install →
                  </a>
                  <Link
                    href="/docs"
                    className="rounded-full border border-lattice px-4 py-2 text-ink hover:bg-paper-fold transition"
                  >
                    Back to docs
                  </Link>
                  <Link
                    href="/docs/api/auth"
                    className="rounded-full border border-lattice px-4 py-2 text-ink hover:bg-paper-fold transition"
                  >
                    HTTP API
                  </Link>
                </div>

                {STEPS.map((step, i) => (
                  <section key={step.id} className={i === 0 ? "mt-14" : "mt-16"}>
                    <h2
                      id={step.id}
                      className="font-sans text-[22px] tracking-tight text-ink scroll-mt-28"
                    >
                      <span className="font-mono text-[12px] text-graphite/70 mr-3 align-middle">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      {step.title}
                    </h2>
                    <p className="mt-3 text-graphite text-[15.5px] leading-[1.7]">
                      {step.blurb}
                    </p>
                    <CommandBlock command={step.command} />
                    <OutputBlock output={step.output} />
                    {step.note ? (
                      <p className="mt-3 text-graphite/80 text-[13.5px] leading-[1.6]">
                        <span className="font-mono text-[11px] text-crane mr-2 align-middle">
                          NOTE
                        </span>
                        {step.note}
                      </p>
                    ) : null}
                  </section>
                ))}

                {/* Prev/Next */}
                <nav
                  aria-label="Pagination"
                  className="mt-16 grid grid-cols-1 sm:grid-cols-2 gap-3 border-t border-lattice pt-6 text-[13px]"
                >
                  <Link
                    href="/docs"
                    className="text-ink hover:text-crane transition"
                  >
                    ← Docs home
                  </Link>
                  <Link
                    href="/docs/api/auth"
                    className="sm:text-right text-ink hover:text-crane transition"
                  >
                    HTTP API reference →
                  </Link>
                </nav>
              </Reveal>
            </article>

            {/* Right: on-this-page */}
            <aside className="hidden lg:block sticky top-28 self-start max-h-[calc(100vh-8rem)] overflow-y-auto text-[12.5px]">
              <p className="eyebrow mb-3">On this page</p>
              <ul className="space-y-2 text-graphite">
                {STEPS.map((s, i) => (
                  <li key={s.id}>
                    <a href={`#${s.id}`} className="hover:text-crane transition">
                      <span className="font-mono text-[10.5px] text-graphite/60 mr-2">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      {s.title}
                    </a>
                  </li>
                ))}
              </ul>
            </aside>
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}

function CommandBlock({ command }: { command: string }) {
  return (
    <figure className="mt-6 overflow-hidden rounded-2xl border border-lattice bg-paper-fold">
      <figcaption className="flex items-center justify-between border-b border-lattice px-4 py-2 font-mono text-[11px] text-graphite">
        <span>shell</span>
        <span aria-hidden>$</span>
      </figcaption>
      <pre className="overflow-x-auto px-4 py-4 text-[12.5px] leading-[1.65] text-ink">
        <code className="font-mono">{command}</code>
      </pre>
    </figure>
  );
}

function OutputBlock({ output }: { output: string }) {
  return (
    <figure className="mt-3 overflow-hidden rounded-2xl border border-ink/10 bg-ink text-paper">
      <figcaption className="flex items-center justify-between border-b border-paper/10 px-4 py-2 font-mono text-[11px] text-paper/60">
        <span>output</span>
        <span aria-hidden>•••</span>
      </figcaption>
      <pre className="overflow-x-auto px-4 py-4 text-[12.5px] leading-[1.65]">
        <code className="font-mono">{output}</code>
      </pre>
    </figure>
  );
}
