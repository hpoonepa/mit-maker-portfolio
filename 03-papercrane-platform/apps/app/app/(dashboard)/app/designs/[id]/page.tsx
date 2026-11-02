import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { createServerTrpc } from "@/lib/trpc/server";
import { toolLabel } from "@/lib/results/metrics";
import { DesignDetail } from "./DesignDetail";

export default async function DesignDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const trpc = await createServerTrpc();

  let design:
    | Awaited<ReturnType<typeof trpc.designs.get.query>>
    | null = null;
  let loadError: string | null = null;
  try {
    design = await trpc.designs.get.query({ id });
  } catch (err) {
    if (err && typeof err === "object" && "data" in err) {
      const data = (err as { data?: { code?: string } }).data;
      if (data?.code === "NOT_FOUND") notFound();
    }
    loadError = err instanceof Error ? err.message : "Failed to load design.";
  }

  if (!design && !loadError) notFound();

  const m = (design?.metrics ?? {}) as Record<string, number | string>;
  const sequence = typeof m.sequence === "string" ? m.sequence : null;
  const length =
    typeof m.length === "number"
      ? m.length
      : sequence
        ? sequence.length
        : null;


  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/app/designs"
          className="inline-flex items-center gap-2 font-sans text-[13px] text-graphite hover:text-ink transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          All designs
        </Link>
        <div className="mt-5 flex items-start justify-between gap-6 flex-wrap">
          <div className="flex items-start gap-5">
            <div>
              <p className="text-xs text-graphite-soft">Result {id.slice(0, 8)}</p>
              <h1 className="font-display text-[36px] leading-tight text-ink">
                {sequence ? "Sequence" : "Result"} · seed {design?.seed ?? "—"}
              </h1>
              <p className="mt-2 font-sans text-[14px] text-graphite">
                {length != null && (
                  <>
                    <span className="font-mono">{length} aa</span>
                    <span className="mx-2 text-graphite-soft">·</span>
                  </>
                )}
                {toolLabel(design?.tool)}
              </p>
            </div>
          </div>
          {(design as { jobId?: string } | null)?.jobId && (
            <Link
              href={`/app/jobs/${(design as { jobId?: string }).jobId}`}
              className="inline-flex shrink-0 items-center gap-2 rounded-full border border-lattice-strong bg-paper px-4 py-2 font-sans text-[13px] text-ink hover:bg-paper-fold transition-colors"
            >
              View parent job
              <ExternalLink className="h-3 w-3 text-graphite-soft" />
            </Link>
          )}
        </div>
      </div>

      {loadError && (
        <div
          role="alert"
          className="rounded-lg border border-crane/40 bg-crane-glow px-5 py-4 font-sans text-[13px] text-crane-deep"
        >
          {loadError}
        </div>
      )}

      {design && (
        <DesignDetail
          designId={id}
          seed={design.seed}
          structureUrl={(design as { structureUrl?: string }).structureUrl ?? null}
          sequence={sequence}
          length={length}
          metrics={numericMetrics(m)}
          jobId={(design as { jobId?: string }).jobId ?? null}
          tool={(design as { tool?: string }).tool ?? null}
          provenance={(design as { provenance?: string }).provenance ?? "unknown"}
        />
      )}
    </div>
  );
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
