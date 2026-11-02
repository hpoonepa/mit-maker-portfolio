"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowUpRight, Download } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { ResultMetrics } from "@/components/designs/ResultMetrics";
import { SequenceViewer } from "@/components/designs/SequenceViewer";
import { ProvenanceBadge } from "@/components/designs/ProvenanceBadge";
import { resultMetrics, toolLabel, isMpnn } from "@/lib/results/metrics";

export interface DesignGridProps { jobId: string; toolId?: string; active?: boolean; total?: number }
export function DesignGrid({ jobId, toolId, active = false, total }: DesignGridProps) {
  const query = trpc.designs.listByJob.useQuery({ jobId, limit: 500 }, { refetchInterval: active ? 3000 : false });
  const [sortBy, setSortBy] = useState("seed");
  const designs = query.data?.items;
  const metrics = useMemo(() => {
    const found = new Map<string, ReturnType<typeof resultMetrics>[number]>();
    for (const d of designs ?? []) for (const m of resultMetrics(toolId, d.metrics)) if (!found.has(m.key)) found.set(m.key, m);
    return [...found.values()];
  }, [designs, toolId]);
  const visible = useMemo(() => [...(designs ?? [])].sort((a, b) => {
    if (sortBy === "seed") return a.seed - b.seed;
    const av = a.metrics[sortBy], bv = b.metrics[sortBy];
    if (typeof av !== "number") return typeof bv === "number" ? 1 : 0;
    if (typeof bv !== "number") return -1;
    const direction = metrics.find((m) => m.key === sortBy)?.direction;
    return direction === "high" ? bv - av : av - bv;
  }), [designs, sortBy, metrics]);
  return (
    <section aria-label="Run results" className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div><h2 className="font-display text-[28px] text-ink">Results</h2><p className="mt-1 text-sm text-graphite">{query.isLoading ? "Loading results…" : `${visible.length} ${visible.length === 1 ? "result" : "results"} from ${toolLabel(toolId)}`}{isMpnn(toolId) ? " · Sequence design" : ""}</p></div>
        {visible.length > 1 && <label className="flex items-center gap-2 text-xs text-graphite">Sort by <select className="rounded-lg border border-lattice bg-paper px-3 py-2 text-ink" value={sortBy} onChange={(e) => setSortBy(e.target.value)}><option value="seed">Seed</option>{metrics.map((m) => <option key={m.key} value={m.key}>{m.label} {m.direction === "high" ? "↓" : "↑"}</option>)}</select></label>}
      </div>
      {query.isError && <div role="alert" className="rounded-lg border border-crane/30 p-5 text-sm text-crane-deep">Could not load results. <button onClick={() => void query.refetch()} className="underline">Try again</button></div>}
      {!query.isLoading && !query.isError && !visible.length && <p className="rounded-lg border border-lattice p-6 text-sm text-graphite">{active ? "Results will appear here as the run completes." : "This run did not produce any results. Check the run details for errors."}</p>}
      {visible.map((d) => {
        const sequence = d.sequence ?? (typeof d.metrics.sequence === "string" ? d.metrics.sequence : null);
        return <article key={d.id} className="overflow-hidden bg-paper">
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4">
            <div className="flex items-center gap-3"><h3 className="font-sans text-base font-medium text-ink">{sequence ? "Sequence" : "Result"} · seed {d.seed}</h3><ProvenanceBadge provenance={d.provenance} /></div>
            <Link href={`/app/designs/${d.id}`} className="inline-flex items-center gap-1.5 text-sm text-graphite hover:text-ink">Open result <ArrowUpRight className="h-4 w-4" /></Link>
          </div>
          <div className="space-y-6 p-6"><ResultMetrics tool={toolId} metrics={d.metrics} />{sequence && <SequenceViewer sequence={sequence} />}
            <div className="flex flex-wrap gap-2">{(sequence ? ["fasta", "csv", "json"] : ["csv", "json"]).map((format) => <a key={format} href={`/api/designs/${d.id}/export/${format}`} className="inline-flex items-center gap-2 rounded-lg border border-lattice px-3 py-2 text-xs text-ink hover:bg-paper-fold"><Download className="h-3.5 w-3.5" />{format === "fasta" ? "Download FASTA" : format === "csv" ? "Scores CSV" : "Full JSON"}</a>)}</div>
          </div>
        </article>;
      })}
      {total != null && total > 500 && <p className="text-sm text-graphite">Showing the first 500 results. Use the job export to download the complete run.</p>}
    </section>
  );
}
