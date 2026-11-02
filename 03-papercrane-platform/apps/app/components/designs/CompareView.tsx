import Link from "next/link";
import { ArrowLeft, Download } from "lucide-react";
import { formatResultMetric, resultMetrics, toolLabel } from "@/lib/results/metrics";
import { ProvenanceBadge } from "./ProvenanceBadge";

export interface CompareDesign {
  id: string;
  seed: number | null;
  rank?: number | null;
  tool?: string | null;
  sequence?: string | null;
  length?: number | null;
  metrics: Record<string, number>;
  provenance?: string | null;
  error?: string | null;
}

export function CompareView({ designs }: { designs: CompareDesign[] }) {
  if (designs.length < 2) {
    return (
      <div className="space-y-6">
        <Link href="/app/designs" className="inline-flex items-center gap-2 text-sm text-graphite hover:text-ink">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to designs
        </Link>
        <div className="px-6 py-10 text-center">
          <p className="font-display text-display-sm text-ink">Select at least 2 results to compare</p>
          <p className="mt-2 text-sm text-graphite">Select results in the gallery, then choose Compare.</p>
        </div>
      </div>
    );
  }

  const cols = designs.slice(0, 4);
  const metrics = cols.map((design) => resultMetrics(design.tool, design.metrics));
  // Labels normalize aliases such as ipTM/iptm without conflating different model scores.
  const rows = [...new Map(metrics.flat().map((metric) => [metric.label, metric])).values()];

  return (
    <div className="space-y-6">
      <div>
        <Link href="/app/designs" className="inline-flex items-center gap-2 text-sm text-graphite hover:text-ink">
          <ArrowLeft className="h-3.5 w-3.5" /> Back to designs
        </Link>
        <h1 className="mt-4 font-display text-display-md text-ink">Compare {cols.length} results</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-graphite">
          Original model outputs. Compare scores from the same model and input settings; a dash means that metric was not returned.
        </p>
      </div>

      <div className="overflow-x-auto bg-paper">
        <table className="w-full min-w-[640px] table-fixed border-collapse text-left">
          <thead>
            <tr>
              <th scope="col" className="w-44 px-5 py-5 text-xs font-medium text-graphite">Result</th>
              {cols.map((design, index) => (
                <th key={design.id} scope="col" className="px-5 py-5 align-top font-normal">
                  <Link href={`/app/designs/${design.id}`} className="font-medium text-ink underline-offset-4 hover:underline">
                    Result {index + 1}
                  </Link>
                  <p className="mt-1 text-sm text-graphite">{toolLabel(design.tool)}</p>
                  <p className="mt-1 font-mono text-xs text-graphite-soft">{design.id.slice(0, 8)}</p>
                  <ProvenanceBadge provenance={design.provenance} className="mt-3" />
                  {design.error && <p role="alert" className="mt-3 text-sm text-crane-deep">{design.error}</p>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row" className="px-5 py-4 text-sm font-medium text-graphite">Seed</th>
              {cols.map((design) => <td key={design.id} className="px-5 py-4 font-mono text-sm tabular-nums">{design.seed ?? "—"}</td>)}
            </tr>
            {rows.map((row) => (
              <tr key={row.label}>
                <th scope="row" className="px-5 py-4 align-top text-sm font-medium text-graphite">
                  {row.label}
                  {row.direction && <span className="mt-1 block text-xs font-normal text-graphite-soft">{row.direction === "low" ? "Lower is better" : "Higher is better"}</span>}
                </th>
                {metrics.map((values, index) => {
                  const value = values.find((metric) => metric.label === row.label);
                  return <td key={cols[index]!.id} title={value?.description} className="px-5 py-4 font-mono text-base tabular-nums text-ink">{value ? formatResultMetric(value) : <span className="text-graphite-soft">—</span>}</td>;
                })}
              </tr>
            ))}
            <tr>
              <th scope="row" className="px-5 py-4 text-sm font-medium text-graphite">Length</th>
              {cols.map((design) => <td key={design.id} className="px-5 py-4 font-mono text-sm tabular-nums">{design.length != null ? `${design.length} aa` : design.sequence ? `${design.sequence.length} aa` : "—"}</td>)}
            </tr>
            <tr>
              <th scope="row" className="px-5 py-4 align-top text-sm font-medium text-graphite">Sequence</th>
              {cols.map((design) => (
                <td key={design.id} className="px-5 py-4 align-top">
                  {design.sequence ? <>
                    <p className="max-h-64 overflow-y-auto break-all font-mono text-xs leading-relaxed text-ink">{design.sequence}</p>
                    <a href={`/api/designs/${design.id}/export/fasta`} className="mt-4 inline-flex items-center gap-1.5 text-xs text-graphite hover:text-ink"><Download className="h-3.5 w-3.5" /> FASTA</a>
                  </> : <span className="text-graphite-soft">—</span>}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="text-sm text-graphite">These results have no numeric model metrics.</p>}
    </div>
  );
}
