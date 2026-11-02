/**
 * Pre-submit preview for the first BindCraft job.
 *
 * Shows the user exactly what they're about to spend:
 *   - tool: BindCraft (default protocol)
 *   - seeds: 8 (default first-run: keeps it cheap but not useless)
 *   - compute estimate: ~16 GPU-min on L4
 *   - cost estimate: credits dollarised at tier-free ~$1.20
 *   - ETA: ~20 min wall clock
 *
 * These numbers are deliberately hard-coded for the onboarding preview;
 * the real estimator lives behind `trpc.jobs.estimate` and will slot in
 * when the migration agent finishes wiring the tRPC client.
 */

export interface JobPreviewCardProps {
  targetLabel: string;
  onSubmit: () => void;
  submitting?: boolean;
}

const DEFAULTS = {
  tool: "BindCraft",
  protocol: "default",
  seeds: 8,
  gpuMinutes: 16,
  costUsd: 1.2,
  etaMinutes: 20,
};

export function JobPreviewCard({
  targetLabel,
  onSubmit,
  submitting,
}: JobPreviewCardProps) {
  return (
    <div className="bg-paper p-6">
      <div className="flex items-center justify-between pb-4">
        <div>
          <p className="font-mono text-eyebrow uppercase text-crane">
            Default first run
          </p>
          <p className="mt-1 font-display text-xl text-ink">
            {DEFAULTS.tool} · {DEFAULTS.protocol}
          </p>
        </div>
        <span className="rounded-full bg-crane-glow px-3 py-1 font-mono text-xs text-crane-deep">
          target: {targetLabel}
        </span>
      </div>

      <dl className="mt-5 grid gap-4 text-sm md:grid-cols-4">
        <Stat label="Seeds" value={String(DEFAULTS.seeds)} />
        <Stat label="GPU-min" value={`~${DEFAULTS.gpuMinutes}`} />
        <Stat label="Est. cost" value={`$${DEFAULTS.costUsd.toFixed(2)}`} />
        <Stat label="ETA" value={`~${DEFAULTS.etaMinutes} min`} />
      </dl>

      <p className="mt-5 text-xs leading-relaxed text-graphite">
        We'll stream results to your dashboard as each seed finishes. You
        can tune seeds, protocol, and filters on the Tools page for your
        next run.
      </p>

      <div className="mt-5 flex justify-end">
        <button
          type="button"
          onClick={onSubmit}
          disabled={submitting}
          className="inline-flex items-center gap-2 rounded-full bg-crane px-6 py-2.5 text-sm font-medium text-paper transition-all hover:bg-crane-deep disabled:opacity-60"
        >
          {submitting ? "Submitting…" : "Submit first job"}
        </button>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-sans text-[0.66rem] text-graphite-soft">
        {label}
      </dt>
      <dd className="mt-1 font-display text-xl text-ink">{value}</dd>
    </div>
  );
}
