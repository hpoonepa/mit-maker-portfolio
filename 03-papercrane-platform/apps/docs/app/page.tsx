import Link from "next/link";

const SECTIONS = [
  {
    title: "Getting started",
    blurb: "Install the CLI, sign in, and run your first job in under five minutes.",
    href: "/getting-started",
  },
  {
    title: "Quickstart",
    blurb: "Sign up → upload a target → launch a binder run → download designs.",
    href: "/quickstart",
  },
  {
    title: "Concepts",
    blurb: "Projects, jobs, designs, metrics — the model under the platform.",
    href: "/concepts/projects-and-targets",
  },
  {
    title: "Tools",
    blurb: "Catalog of 12 protein design tools — when to use each, GPU costs, defaults.",
    href: "/tools",
  },
  {
    title: "API",
    blurb: "REST and tRPC reference — auth, seed consumption, webhook signing.",
    href: "/api",
  },
  {
    title: "Billing",
    blurb: "Tiers, seeds, overage, top-ups, and how charges map to compute.",
    href: "/billing",
  },
];

export default function DocsHome() {
  return (
    <div>
      <div className="eyebrow text-graphite">Paper Crane Docs</div>
      <h1 className="mt-3 font-display text-[52px] leading-[1.02] tracking-tight text-ink">
        Every protein design tool. <br />
        <span className="text-crane">One workflow.</span>
      </h1>
      <p className="mt-5 max-w-[640px] text-[16px] leading-7 text-ink-soft">
        These docs cover the Paper Crane platform — from your first run to API integration,
        billing, and the science of binder QC. Pick a section below.
      </p>

      <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {SECTIONS.map((s) => (
          <Link
            key={s.href}
            href={s.href}
            className="group block rounded-2xl border border-lattice-strong bg-paper-fold/40 p-5 transition-colors hover:border-ink hover:bg-paper-fold"
          >
            <div className="flex items-center justify-between">
              <span className="font-display text-[20px] tracking-tight text-ink">{s.title}</span>
              <span className="font-mono text-[18px] text-graphite group-hover:text-crane">→</span>
            </div>
            <p className="mt-2 text-[14px] text-ink-soft">{s.blurb}</p>
          </Link>
        ))}
      </div>

      <div className="mt-16 border-t border-lattice pt-6 text-[13px] text-graphite">
        Looking for the marketing site? <Link className="text-crane hover:underline" href="https://papercrane.bio">papercrane.bio</Link>
        {" · "}
        Looking for the app? <Link className="text-crane hover:underline" href="https://app.papercrane.bio">app.papercrane.bio</Link>
      </div>
    </div>
  );
}
