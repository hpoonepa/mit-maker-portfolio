/**
 * Settings → Rate limits.
 *
 * Stub mode: no `usage.rateLimits` (or equivalent) tRPC procedure exists yet.
 * The audit/billing routers expose subscription + audit data, but nothing
 * surfaces per-scope buckets, current consumption, or reset-at timestamps.
 *
 * Rather than fabricate numbers, this page renders the configured scope grid
 * with a `pending telemetry` state on every card and a single editorial
 * placeholder banner. When the telemetry proc ships, swap `STUB_SCOPES` for a
 * server caller (see TODO inline): the layout already handles `>80%` Crane-red
 * fills and reset-at relative time, so the only delta is the data source.
 *
 * NO fabricated numbers. NO new tRPC procs. NO new deps.
 */

export const dynamic = "force-dynamic";
export const revalidate = 0;

type ScopeKey =
  | "designs.read"
  | "designs.write"
  | "jobs.submit"
  | "jobs.read"
  | "exports.create"
  | "api.requests";

type ScopeMeta = {
  key: ScopeKey;
  label: string;
  blurb: string;
};

// Static scope catalogue: these are the buckets the platform *will* meter.
// No usage numbers here on purpose; this is just the grid skeleton.
const STUB_SCOPES: ScopeMeta[] = [
  {
    key: "designs.read",
    label: "designs.read",
    blurb: "GET /v1/designs and list endpoints",
  },
  {
    key: "designs.write",
    label: "designs.write",
    blurb: "POST/PATCH on design resources",
  },
  {
    key: "jobs.submit",
    label: "jobs.submit",
    blurb: "Boltz / Protenix / RFdiff submissions",
  },
  {
    key: "jobs.read",
    label: "jobs.read",
    blurb: "Job status polling and result fetch",
  },
  {
    key: "exports.create",
    label: "exports.create",
    blurb: "Bulk CSV / FASTA / PDB exports",
  },
  {
    key: "api.requests",
    label: "api.requests",
    blurb: "Aggregate API request ceiling",
  },
];

export default async function RateLimitsPage() {
  // TODO(@papercrane/trpc): when usage.rateLimits ships, replace `null` with:
  //   const trpc = await createServerTrpc();
  //   const buckets = await trpc.usage.rateLimits.query();
  // Each bucket should expose { scope, current, max, resetAt }.
  const buckets: null = null;

  return (
    <div className="space-y-8">
      <header className="border-b border-graphite-soft/15 pb-5">
        <p className="font-sans text-[12px] text-graphite-soft">
          Quotas
        </p>
        <h1 className=".5 font-sans text-[22px] font-medium tracking-tight text-ink">
          Rate limits
        </h1>
        <p className="mt-1.5 max-w-2xl font-sans text-[13.5px] leading-relaxed text-graphite">
          Per-scope request budgets and reset windows for this organisation.
          Buckets refill on a rolling window; the bar tints Crane-red once a
          scope crosses 80% utilisation so you can pre-empt 429s.
        </p>
      </header>

      {!buckets && (
        <div
          role="status"
          className="rounded-lg border border-graphite-soft/20 bg-bone px-5 py-4 font-sans text-[13px] text-graphite"
        >
          Rate limits will appear here once telemetry ships. The grid below is
          the configured scope set: current consumption and reset-at
          timestamps are intentionally blank rather than estimated.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {STUB_SCOPES.map((scope) => (
          <ScopeCard key={scope.key} scope={scope} />
        ))}
      </div>
    </div>
  );
}

function ScopeCard({ scope }: { scope: ScopeMeta }) {
  // Stub: no live numbers. When wired, compute:
  //   const pct = bucket.current / bucket.max;
  //   const overThreshold = pct > 0.8;
  const pct: number | null = null;
  const overThreshold = pct !== null && pct > 0.8;

  return (
    <article className="rounded-lg border border-graphite-soft/15 bg-paper p-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[12px] tracking-tight text-ink">
            {scope.label}
          </p>
          <p className="mt-1 font-sans text-[12px] leading-snug text-graphite-soft">
            {scope.blurb}
          </p>
        </div>
      </header>

      <dl className="mt-4 space-y-2">
        <div className="flex items-baseline justify-between">
          <dt className="font-sans text-[12px] text-graphite-soft">
            Bucket
          </dt>
          <dd className="font-mono text-[13px] tabular-nums text-ink">
            {pct === null ? "- / -" : "N/A"}
          </dd>
        </div>
        <div className="flex items-baseline justify-between">
          <dt className="font-sans text-[12px] text-graphite-soft">
            Resets
          </dt>
          <dd className="font-sans text-[12px] tabular-nums text-graphite">
            PENDING
          </dd>
        </div>
      </dl>

      <div
        className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-graphite-soft/15"
        aria-hidden
      >
        {overThreshold && pct !== null && (
          <div
            className="h-full bg-crane"
            style={{ width: `${Math.min(100, Math.round(pct * 100))}%` }}
          />
        )}
      </div>
    </article>
  );
}
