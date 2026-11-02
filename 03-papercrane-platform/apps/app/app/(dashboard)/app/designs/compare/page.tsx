import Link from "next/link";
import { createServerTrpc } from "@/lib/trpc/server";
import {
  CompareView,
  type CompareDesign,
} from "@/components/designs/CompareView";

/**
 * Compare designs side-by-side. Reads `?ids=a,b,c` from the query string
 * (comma-separated, max 4) and fetches each via the existing
 * `designs.get` tRPC procedure in parallel: no new procs required.
 */
export default async function CompareDesignsPage({
  searchParams,
}: {
  searchParams: Promise<{ ids?: string | string[] }>;
}) {
  const sp = await searchParams;
  const raw = sp.ids;
  const idsParam = Array.isArray(raw) ? raw.join(",") : raw ?? "";
  const ids = [...new Set(idsParam
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean))]
    .slice(0, 4);

  if (ids.length < 2) {
    return (
      <div className="space-y-6">
        <div className="px-6 py-10 text-center">
          <p className="font-display text-display-sm text-ink">
            Select at least 2 designs to compare
          </p>
          <p className="mt-2 font-sans text-[13px] text-graphite">
            Multi-select designs in the gallery, then hit <em>Compare</em>.
          </p>
          <Link
            href="/app/designs"
            className="mt-6 inline-flex items-center gap-2 rounded-full border border-lattice-strong bg-paper px-4 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold transition-colors"
          >
            Back to designs
          </Link>
        </div>
      </div>
    );
  }

  const trpc = await createServerTrpc();
  const results = await Promise.all(
    ids.map(async (id): Promise<CompareDesign> => {
      try {
        const d = await trpc.designs.get.query({ id });
        const m = (d.metrics ?? {}) as Record<string, number | string>;
        const seq =
          typeof m.sequence === "string"
            ? m.sequence
            : typeof (d as { sequence?: string }).sequence === "string"
              ? (d as { sequence: string }).sequence
              : null;
        const length =
          typeof (d as { length?: number }).length === "number"
            ? (d as { length: number }).length
            : typeof m.length === "number"
              ? m.length
              : seq
                ? seq.length
                : null;
        return {
          id: d.id,
          seed: d.seed,
          provenance: d.provenance,
          tool: (d as { tool?: string | null }).tool ?? null,
          sequence: seq,
          length,
          metrics: numericMetrics(m),
          error: null,
        };
      } catch {
        return {
          id,
          seed: null,
          metrics: {},
          sequence: null,
          length: null,
          error: "This result could not be loaded. Open it to check access or try again.",
        };
      }
    }),
  );

  return <CompareView designs={results} />;
}

function numericMetrics(
  m: Record<string, number | string>,
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(m)) {
    if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
  }
  return out;
}
