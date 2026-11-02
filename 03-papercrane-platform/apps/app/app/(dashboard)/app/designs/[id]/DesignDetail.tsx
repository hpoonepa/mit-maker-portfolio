"use client";

import dynamic from "next/dynamic";
import { Download } from "lucide-react";
import { trpc } from "@/lib/trpc/client";
import { SequenceViewer } from "@/components/designs/SequenceViewer";
import { ResultMetrics } from "@/components/designs/ResultMetrics";
import { CommentThread } from "@/components/annotations/CommentThread";
import { StarButton } from "@/components/annotations/StarButton";
import { TagChips } from "@/components/annotations/TagChips";
import { ProvenanceBanner } from "@/components/designs/ProvenanceBadge";
import { expectsCoordinates, isMpnn, toolLabel } from "@/lib/results/metrics";

const MolstarViewer = dynamic(() => import("@/components/viewer/MolstarViewer").then((m) => m.MolstarViewer), { ssr: false, loading: () => <p className="p-8 text-sm text-graphite">Loading structure…</p> });

export interface DesignDetailProps {
  designId: string;
  seed: number;
  structureUrl: string | null;
  sequence: string | null;
  length: number | null;
  metrics: Record<string, number>;
  jobId: string | null;
  tool: string | null;
  provenance?: string | null;
}

export function DesignDetail({ designId, seed, structureUrl, sequence, metrics, tool, provenance }: DesignDetailProps) {
  const annotationsQuery = trpc.annotations.listByDesign.useQuery({ designId });
  const membersQuery = trpc.members.list.useQuery();
  const members = (membersQuery.data?.items ?? []).map((m) => ({ userId: m.userId, name: m.name ?? null, email: m.email }));
  const annotations = annotationsQuery.data?.annotations ?? [];
  const hasCoordinates = !!structureUrl && expectsCoordinates(tool);
  const formats = [...(sequence ? ["fasta"] : []), "csv", "json", ...(hasCoordinates ? ["cif"] : [])];
  return <div className="space-y-6">
    <ProvenanceBanner provenance={provenance} />
    <section className="bg-paper p-6 sm:p-8" aria-label="Model results">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3"><h2 className="font-display text-2xl text-ink">{toolLabel(tool)} results</h2><StarButton designId={designId} starred={annotationsQuery.data?.starred ?? false} starCount={annotationsQuery.data?.starCount ?? 0} /></div>
      <ResultMetrics tool={tool} metrics={metrics} />
      {isMpnn(tool) && <p className="mt-5 text-sm leading-relaxed text-graphite">These scores describe sequence compatibility with the input backbone. Binding and experimental activity have not been measured by this run.</p>}
    </section>
    {sequence && <SequenceViewer sequence={sequence} />}
    {hasCoordinates && <section className="space-y-3"><h2 className="font-display text-2xl text-ink">Structure</h2><div className="overflow-hidden"><MolstarViewer structureUrl={`/api/designs/${encodeURIComponent(designId)}/export/cif`} ariaLabel={`Structure for seed ${seed}`} /></div></section>}
    <section className="flex flex-wrap items-center gap-3 p-5" aria-label="Downloads"><span className="mr-auto text-sm font-medium text-ink">Download result</span>{formats.map((format) => <a key={format} href={`/api/designs/${designId}/export/${format}`} className="inline-flex items-center gap-2 rounded-lg border border-lattice bg-paper px-4 py-2 text-sm text-ink hover:bg-paper-fold"><Download className="h-4 w-4" />{format.toUpperCase()}</a>)}</section>
    <details className="rounded-xl border border-lattice p-5"><summary className="cursor-pointer text-sm font-medium text-ink">Notes & tags{annotations.length ? ` (${annotations.length})` : ""}</summary><div className="mt-5 space-y-5"><TagChips designId={designId} tags={annotationsQuery.data?.tags ?? []} /><CommentThread designId={designId} annotations={annotations} members={members} /></div></details>
  </div>;
}
