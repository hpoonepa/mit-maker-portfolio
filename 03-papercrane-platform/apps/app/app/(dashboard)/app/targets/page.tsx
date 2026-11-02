import Link from "next/link";
import { Plus, Target as TargetIcon, Flame } from "lucide-react";

/**
 * Targets list.
 *
 * Sibling to Projects: a workspace-level index of uploaded structures.
 * Mirrors the empty/loaded pattern used on /app/projects so the two feel
 * like twins.
 *
 * Once `targets.list` lands on AppRouter, swap the stub for:
 *
 *   const trpc = await createServerTrpc();
 *   const targets = await trpc.targets.list.query();
 */
type TargetRow = {
  id: string;
  name: string;
  pdbId: string | null;
  chain: string;
  residueCount: number;
  hotspotCount: number;
  updatedAt: string;
};

export default async function TargetsPage() {
  // TODO(@papercrane/trpc): const targets = await (await createServerTrpc()).targets.list.query();
  const targets: TargetRow[] = [];

  return (
    <div className="space-y-8">
      <header className="flex items-end justify-between gap-6">
        <div>
          <h1 className="font-display text-display-md text-ink">
            Targets
          </h1>
          <p className="mt-2 max-w-lg font-sans text-[15px] text-graphite">
            Upload a PDB or mmCIF, mark the interface hotspots, then reuse it
            across jobs.
          </p>
        </div>
        <Link href="/app/targets/new" className="btn-primary shrink-0">
          <Plus className="w-4 h-4" />
          New target
        </Link>
      </header>

      {targets.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {targets.map((t) => (
            <li key={t.id}>
              <Link
                href={`/app/targets/${t.id}`}
                className="group block p-6 transition-colors hover:border-lattice-strong hover:bg-paper-fold"
              >
                <div className="flex items-start justify-between">
                  <div className="inline-flex h-10 w-10 items-center justify-center bg-paper text-ink">
                    <TargetIcon className="w-4 h-4" />
                  </div>
                  {t.pdbId && (
                    <span className="font-mono text-[11px] text-graphite-soft">
                      {t.pdbId}
                    </span>
                  )}
                </div>
                <h2 className="mt-5 font-display text-[22px] text-ink tracking-[-0.01em] group-hover:text-crane-deep transition-colors">
                  {t.name}
                </h2>
                <dl className="mt-4 flex items-center gap-5 font-mono text-[12px] text-graphite">
                  <div className="flex items-center gap-1.5">
                    <span className="text-graphite-soft">chain</span>
                    <span className="text-ink">{t.chain}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-graphite-soft">res</span>
                    <span className="text-ink">{t.residueCount}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Flame className="w-3 h-3" />
                    <span className="text-ink">{t.hotspotCount}</span>
                  </div>
                </dl>
                <p className="mt-4 font-sans text-[12px] text-graphite-soft">
                  Updated {relativeTime(t.updatedAt)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="px-8 py-16 text-center">
      <div className="mx-auto inline-flex h-12 w-12 items-center justify-center bg-paper">
        <TargetIcon className="w-5 h-5 text-ink" />
      </div>
      <h2 className="mt-5 font-display text-[26px] text-ink">No targets yet</h2>
      <p className="mt-2 mx-auto max-w-md font-sans text-[15px] text-graphite">
        Upload a structure, select a chain, and mark any hotspots needed by the
        design tool.
      </p>
      <Link href="/app/targets/new" className="mt-6 inline-flex btn-primary">
        <Plus className="w-4 h-4" />
        Upload target
      </Link>
    </div>
  );
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const delta = Math.max(0, now - then);
  const mins = Math.floor(delta / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
