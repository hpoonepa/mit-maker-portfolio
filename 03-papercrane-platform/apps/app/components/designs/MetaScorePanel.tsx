import { BrainCircuit, CircleAlert } from 'lucide-react';
import { cn } from '@/lib/utils';

export type ExperimentalMetaScore = {
  version: string;
  evidenceType: 'computational';
  status: 'scored' | 'insufficient_metrics';
  score: number | null;
  coverage: number;
  priorSource: 'target_prior' | 'observed_metric_fallback';
  targetKey: string | null;
  availableMetrics: number;
  experimental: true;
  rationale: string;
  liabilities: string[];
  citations: string[];
  contributions: Array<{
    metric: string;
    label: string;
    value: number;
    weight: number;
    alignedValue: number;
    contribution: number;
  }>;
  caveats: string[];
};

export function MetaScorePanel({ score }: { score: ExperimentalMetaScore }) {
  const scored = score.status === 'scored' && score.score !== null;
  const scorePct = scored ? Math.round(score.score! * 100) : null;
  const coveragePct = Math.round(score.coverage * 100);
  const sourceLabel =
    score.priorSource === 'target_prior'
      ? `${score.targetKey ?? 'Target'} prior`
      : 'Metric fallback';
  const topContributions = score.contributions.slice(0, 5);

  return (
    <section
      aria-labelledby="llm-meta-score-title"
      className="p-5"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <BrainCircuit className="h-4 w-4 text-crane" aria-hidden />
          <div>
            <h3
              id="llm-meta-score-title"
              className="font-sans text-[12px] text-ink"
            >
              LLM meta-score
            </h3>
            <p className="mt-0.5 font-sans text-[9px] text-graphite-soft">
              Experimental · Computational only · {sourceLabel}
            </p>
          </div>
        </div>
        <div className="text-right">
          <div className="font-display text-[34px] leading-none tabular-nums text-ink">
            {scorePct === null ? '-' : scorePct}
          </div>
          <div className="mt-1 font-sans text-[9px] text-graphite-soft">
            Relative evidence / 100
          </div>
        </div>
      </div>

      <div className="mt-5">
        <div className="mb-1.5 flex items-center justify-between font-sans text-[9px] text-graphite-soft">
          <span>Prior coverage</span>
          <span>{coveragePct}% · {score.availableMetrics} metrics</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-lattice">
          <div
            className={cn(
              'h-full rounded-full',
              coveragePct >= 60 ? 'bg-ink' : coveragePct >= 30 ? 'bg-amber-600' : 'bg-crane',
            )}
            style={{ width: `${coveragePct}%` }}
          />
        </div>
      </div>

      <p className="mt-4 font-sans text-[13px] leading-relaxed text-graphite">
        {score.rationale}
      </p>

      {topContributions.length > 0 ? (
        <div className="mt-5 pt-4">
          <div className="font-sans text-[9px] text-graphite-soft">
            Observed contributions
          </div>
          <div className="mt-2 space-y-2">
            {topContributions.map((item) => (
              <div
                key={item.metric}
                className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-baseline gap-3"
              >
                <span className="truncate font-sans text-[12px] text-graphite">
                  {item.label}
                </span>
                <span className="font-mono text-[10px] tabular-nums text-graphite-soft">
                  w {formatSigned(item.weight)}
                </span>
                <span className="w-10 text-right font-mono text-[11px] tabular-nums text-ink">
                  {Math.round(item.alignedValue * 100)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {score.liabilities.length > 0 ? (
        <div className="mt-5 pt-4">
          <div className="font-sans text-[9px] text-graphite-soft">
            Target liabilities
          </div>
          <ul className="mt-2 space-y-2">
            {score.liabilities.slice(0, 3).map((liability) => (
              <li key={liability} className="flex gap-2 font-sans text-[12px] leading-relaxed text-graphite">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-crane" aria-hidden />
                <span>{liability}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-5 flex gap-2 pt-4 text-amber-800">
        <CircleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <p className="font-sans text-[11px] leading-relaxed">
          Computed from in-silico metrics only. No wet-lab measurement is used. This is
          not P(bind), and the current 11-target evaluation is statistically unresolved.
        </p>
      </div>

      <div className="mt-3 font-sans text-[8px] text-graphite-soft">
        {score.version}
        {score.citations.length > 0 ? ` · ${score.citations.join(' · ')}` : ''}
      </div>
    </section>
  );
}

function formatSigned(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}`;
}
