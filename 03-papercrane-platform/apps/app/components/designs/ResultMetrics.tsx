import { formatResultMetric, isBoltz, isMpnn, resultMetrics } from "@/lib/results/metrics";

export function ResultMetrics({ tool, metrics, compact = false }: { tool?: string | null; metrics: Record<string, unknown>; compact?: boolean }) {
  const values = resultMetrics(tool, metrics);
  if (!values.length) return <p className="text-sm text-graphite-soft">No numerical metrics were recorded for this result.</p>;
  return (
    <div>
      <dl className={compact ? "grid grid-cols-2 gap-x-5 gap-y-3" : "grid grid-cols-2 gap-5 lg:grid-cols-4"}>
        {(compact ? values.slice(0, 4) : values).map((metric) => (
          <div key={metric.key} title={metric.description ?? metric.key} className="min-w-0">
            <dt className="font-sans text-xs text-graphite">{metric.label}</dt>
            <dd className={compact ? "mt-1 font-mono text-lg text-ink tabular-nums" : "mt-2 font-mono text-[28px] leading-tight text-ink tabular-nums"}>{formatResultMetric(metric)}</dd>
            {!compact && metric.direction && <p className="mt-1 text-[11px] text-graphite-soft">{metric.direction === "low" ? "Lower is better" : "Higher is better"}</p>}
          </div>
        ))}
      </dl>
      {!compact && (isMpnn(tool) || isBoltz(tool)) && values.some((value) => value.description) && (
        <details className="mt-5 border-t border-lattice pt-4 text-sm text-graphite">
          <summary className="cursor-pointer hover:text-ink">What these scores mean</summary>
          <dl className="mt-4 space-y-3">{values.filter((v) => v.description).map((v) => <div key={v.key}><dt className="font-medium text-ink">{v.label}</dt><dd className="mt-1 leading-relaxed">{v.description}</dd></div>)}</dl>
          <a className="mt-4 inline-block underline underline-offset-4" href={isBoltz(tool) ? "https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md#output" : "https://github.com/dauparas/ProteinMPNN"} target="_blank" rel="noreferrer">{isBoltz(tool) ? "Boltz output documentation" : "ProteinMPNN documentation"}</a>
        </details>
      )}
    </div>
  );
}
