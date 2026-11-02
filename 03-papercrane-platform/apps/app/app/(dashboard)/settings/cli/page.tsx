import Link from "next/link";

/**
 * `/settings/cli`: In-product CLI quickstart.
 *
 * Static server component. Shows install commands, the auth flow, and a
 * cheat-sheet of the most-useful subcommands.
 *
 * Auth approach
 * -------------
 *   The codebase does not currently expose a `cli.token` tRPC procedure
 *   (no `cli` router under `packages/trpc/src/routers/`). Per the Wave-D
 *   spec: "NEVER fabricate an auth code": this page falls back to the
 *   OAuth browser flow that `papercrane login` already triggers. When a
 *   server-side install-token procedure ships, swap the auth section for
 *   a one-shot reveal (mirroring `KeyList`'s "shown once" pattern).
 */
export default function CliQuickstartPage() {
  return (
    <div className="space-y-10">
      <header className="border-b border-graphite-soft/15 pb-5">
        <p className="font-sans text-[12px] text-graphite-soft">
          CLI · papercrane
        </p>
        <h1 className=".5 font-display text-display-md text-ink">
          Run designs from your terminal
        </h1>
        <p className="mt-2 max-w-xl font-sans text-[13.5px] leading-relaxed text-graphite">
          The <code className="font-mono text-[12.5px] text-ink">papercrane</code>{" "}
          CLI mirrors every dashboard action: submit jobs, stream logs, pull
          designs: without leaving your editor.
        </p>
      </header>

      <InstallSection />
      <AuthSection />
      <QuickRefSection />
    </div>
  );
}

function InstallSection() {
  return (
    <section className="space-y-3">
      <SectionHeader
        eyebrow="Step 1"
        title="Install"
        blurb="Homebrew is the recommended path on macOS and Linux. npm is available as a fallback for any Node toolchain."
      />
      <CodeBlock label="Homebrew (recommended)">
        brew install papercrane-bio/papercrane/papercrane
      </CodeBlock>
      <CodeBlock label="npm (fallback)">
        npm i -g @papercrane/cli
      </CodeBlock>
    </section>
  );
}

function AuthSection() {
  return (
    <section className="space-y-3">
      <SectionHeader
        eyebrow="Step 2"
        title="Authenticate"
        blurb="The CLI uses an OAuth browser handshake: no long-lived tokens stored in your shell history."
      />
      <CodeBlock>papercrane login</CodeBlock>
      <p className="font-sans text-[13px] leading-relaxed text-graphite">
        Run{" "}
        <code className="font-mono text-[12.5px] text-ink">
          papercrane login
        </code>{" "}
        to use the OAuth browser flow. Your default browser will open, you
        approve the device, and the CLI writes a session token to{" "}
        <code className="font-mono text-[12.5px] text-ink">
          ~/.papercrane/credentials
        </code>
        . Tokens auto-rotate every 30 days.
      </p>
      <div className="pt-1">
        <Link
          href="/api/cli/authorize"
          className="inline-flex items-center gap-2 rounded-full bg-crane px-4 py-2 font-sans text-[13px] font-medium text-white transition-colors hover:bg-crane-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crane focus-visible:ring-offset-2"
        >
          Sign in via browser
          <span aria-hidden className="font-mono text-[12px]">
            ↗
          </span>
        </Link>
      </div>
    </section>
  );
}

function QuickRefSection() {
  return (
    <section className="space-y-3">
      <SectionHeader
        eyebrow="Step 3"
        title="Quick reference"
        blurb="Five commands cover ~90% of daily use. See `papercrane help` for the full surface."
      />
      <dl className="divide-y divide-graphite-soft/15 rounded-lg border border-graphite-soft/15 bg-paper">
        {QUICK_REF.map((row) => (
          <div
            key={row.cmd}
            className="grid gap-2 px-5 py-3.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] sm:items-baseline sm:gap-6"
          >
            <dt className="font-mono text-[12.5px] text-ink">{row.cmd}</dt>
            <dd className="font-sans text-[13px] leading-relaxed text-graphite">
              {row.desc}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

const QUICK_REF: Array<{ cmd: string; desc: string }> = [
  {
    cmd: "papercrane init <project>",
    desc: "Scaffold a project directory with target.fasta and a designs/ folder.",
  },
  {
    cmd: "papercrane run rfdiffusion --target target.pdb",
    desc: "Submit a backbone-generation job to your default workspace.",
  },
  {
    cmd: "papercrane jobs ls",
    desc: "List recent jobs with status, runtime, and design count.",
  },
  {
    cmd: "papercrane logs <job-id> --follow",
    desc: "Stream live logs from a running job (Ctrl-C to detach).",
  },
  {
    cmd: "papercrane pull <job-id>",
    desc: "Download all designs + metrics CSV for the given job locally.",
  },
];

function SectionHeader({
  eyebrow,
  title,
  blurb,
}: {
  eyebrow: string;
  title: string;
  blurb: string;
}) {
  return (
    <div>
      <p className="font-sans text-[12px] text-graphite-soft">
        {eyebrow}
      </p>
      <h2 className="mt-1 font-sans text-[18px] font-medium tracking-tight text-ink">
        {title}
      </h2>
      <p className="mt-1.5 max-w-xl font-sans text-[13px] leading-relaxed text-graphite">
        {blurb}
      </p>
    </div>
  );
}

function CodeBlock({
  children,
  label,
}: {
  children: React.ReactNode;
  label?: string;
}) {
  return (
    <div className="space-y-1.5">
      {label && (
        <p className="font-sans text-[12px] text-graphite-soft">
          {label}
        </p>
      )}
      <pre className="overflow-x-auto rounded-xl border border-graphite-soft/15 bg-paper px-4 py-3 font-mono text-[12.5px] leading-relaxed text-ink">
        <code>$ {children}</code>
      </pre>
    </div>
  );
}
