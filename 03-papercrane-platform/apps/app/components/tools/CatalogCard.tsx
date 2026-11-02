import Link from "next/link";
import { goodAt } from "@/lib/jobs/toolDescriptions";
import { jobInputKind } from "@papercrane/types";

export type CatalogCardTool = {
  id: string; slug: string; name: string; version: string; description: string;
  category: string; gpuType: string; gpuCount: number; minVramGb: number;
  tier: string; timePerDesignSeconds: number; status?: "ga" | "beta";
  runnable?: boolean; metadataOffline?: boolean;
};

export function CatalogCard({ tool }: { tool: CatalogCardTool }) {
  const runnable = tool.runnable === true && !tool.metadataOffline;
  const detailsHref = `/app/tools/${tool.slug}`;
  const setupHref = `/app/jobs/new?tool=${encodeURIComponent(tool.slug)}`;
  const kind = jobInputKind([tool.slug]);
  const input = kind === "target" ? "Target structure" : kind === "backbone" ? "Backbone structure" : kind === "complex" ? "Protein structures" : "Amino-acid sequences";
  return (
    <article className="flex h-full flex-col py-6 pr-4">
      <h3 className="text-[25px] leading-tight tracking-[-0.025em] text-ink">
        <Link href={runnable ? setupHref : detailsHref} className="hover:text-crane">{tool.name}</Link>
      </h3>
      <p className="mt-3 max-w-md text-sm leading-relaxed text-graphite">{goodAt(tool.slug, tool.description)}</p>
      <p className="mt-4 text-xs text-graphite">{runnable ? `Input: ${input}` : tool.metadataOffline ? "Availability unavailable" : "Not available to run yet"}</p>
      <div className="mt-5 flex items-center gap-5">
        {runnable && <Link href={setupHref} className="inline-flex items-center gap-2 text-sm text-crane hover:text-ink">Run {tool.name}</Link>}
        <Link href={detailsHref} aria-label={`About ${tool.name}`} className="text-xs text-graphite hover:text-ink">Details</Link>
      </div>
    </article>
  );
}
