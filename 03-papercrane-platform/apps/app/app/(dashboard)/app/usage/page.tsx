import { UsageMeter } from "@/components/dashboard/UsageMeter";
import { createServerTrpc } from "@/lib/trpc/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

/**
 * Usage dashboard: seeds consumed, GPU-hours, projection. Backed by the
 * live `usage.*` tRPC router so the page reflects the same numbers as the
 * widgets on the home dashboard. Falls back to a benign empty period if
 * the router throws (e.g. unauth, db blip) so the page still renders.
 */
export default async function UsagePage() {
  const trpc = await createServerTrpc();

  let period;

  try {
    const [current, byTool] = await Promise.all([
      trpc.usage.getCurrentPeriodUsage.query(),
      trpc.usage.getSeedsByTool.query(),
    ]);
    period = {
      seedsIncluded: current.seedsIncluded,
      seedsConsumed: current.seedsConsumed,
      overageSeeds: current.overageSeeds,
      periodStart: current.periodStart,
      periodEnd: current.periodEnd,
      byTool: byTool.totals ?? {},
    };
  } catch {
    return <div className="space-y-4"><h1 className="text-display-md text-ink">Usage</h1><p className="text-graphite">Usage is temporarily unavailable. Refresh to try again.</p></div>;
  }

  const daysLeft = Math.max(
    1,
    Math.ceil((new Date(period.periodEnd).getTime() - Date.now()) / 86400_000)
  );
  const elapsedDays = Math.max(1, (Date.now() - new Date(period.periodStart).getTime()) / 86400_000);
  const dailyRate = period.seedsConsumed / elapsedDays;
  const projected = Math.round(period.seedsConsumed + dailyRate * daysLeft);

  return (
    <div className="space-y-10">
      <header>
        <h1 className="font-display text-display-md text-ink">Usage</h1>
        <p className="mt-2 max-w-xl font-sans text-[15px] text-graphite">
          A seed is one design attempt. Jobs consume seeds according to the
          tool; see the pricing page for the full table.
        </p>
      </header>

      <section className="p-8">
        <UsageMeter
          consumed={period.seedsConsumed}
          included={period.seedsIncluded}
          size="full"
        />
        <div className="mt-7 grid gap-6 md:grid-cols-2">
          <Stat
            label="Days remaining"
            value={String(daysLeft)}
            hint="in current billing period"
          />
          <Stat
            label="Projected seeds"
            value={projected.toString()}
            hint="at current burn rate"
          />
        </div>
      </section>

      <section>
        <h2 className="font-display text-[22px] text-ink">By tool</h2>
        <p className="mt-1 font-sans text-[14px] text-graphite">
          Seeds consumed per tool this period.
        </p>

        {Object.keys(period.byTool).length === 0 ? (
          <div className="mt-5 px-6 py-10 text-center font-sans text-[14px] text-graphite">
            No usage yet this period.
          </div>
        ) : (
          <ul className="mt-5 space-y-2">
            {Object.entries(period.byTool).map(([tool, count]) => (
              <li
                key={tool}
                className="flex items-center justify-between px-5 py-3"
              >
                <span className="font-sans text-[14px] text-ink">{tool}</span>
                <span className="font-mono text-[13px] text-ink">{count}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div>
      <div className="font-sans text-[12px] text-graphite-soft">
        {label}
      </div>
      <div className="mt-1 font-display text-[28px] text-ink tracking-[-0.01em]">
        {value}
      </div>
      {hint && (
        <div className="mt-1 font-sans text-[12px] text-graphite">{hint}</div>
      )}
    </div>
  );
}
