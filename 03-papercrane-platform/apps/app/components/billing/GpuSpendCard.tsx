"use client";

import { Loader2 } from "lucide-react";
import { trpc } from "@/lib/trpc/client";

/**
 * GPU spend card: shows running spend vs the per-org beta cap and a 20-row
 * history of recent submissions. Progress bar colour shifts:
 *   - <80%  : crane (default)
 *   - 80-95%: amber-500
 *   - >95%  : crane-deep
 *
 * The cap is configurable per-org (the founders can raise it without a code
 * change). Defaults to $50 via the schema default.
 */
export function GpuSpendCard() {
  const { data, isLoading, error } = trpc.usage.getGpuSpend.useQuery(undefined, {
    refetchOnWindowFocus: false,
  });

  if (isLoading) {
    return (
      <section className="p-8">
        <div className="flex items-center gap-2 font-sans text-[13px] text-graphite">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading GPU spend…
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="p-8">
        <p className="font-sans text-[13px] text-crane-deep">
          Could not load GPU spend: {error?.message ?? "unknown error"}
        </p>
      </section>
    );
  }

  const pct = Math.min(1, Math.max(0, data.pctUsed));
  const pctDisplay = (pct * 100).toFixed(0);
  // Tailwind requires concrete classes (the JIT can't see dynamic strings),
  // so we branch on the ratio and pick from a fixed set.
  const barColor =
    pct < 0.8 ? "bg-crane" : pct < 0.95 ? "bg-amber-500" : "bg-crane-deep";
  const labelColor =
    pct < 0.8 ? "text-ink" : pct < 0.95 ? "text-amber-700" : "text-crane-deep";

  return (
    <section
      data-testid="gpu-spend-card"
      className="p-8"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-sans text-[12px] text-graphite-soft">
            GPU spend (beta cap)
          </p>
          <h2 className="mt-2 font-display text-[28px] text-ink tracking-[-0.01em]">
            ${data.currentSpendUsd.toFixed(2)}{" "}
            <span className="text-graphite">/ ${data.capUsd.toFixed(2)}</span>
          </h2>
          <p className="mt-1 font-sans text-[14px] text-graphite max-w-md">
            Hard cap during private beta. Email{" "}
            <a
              href="mailto:founders@papercrane.bio"
              className="underline decoration-graphite-soft underline-offset-2"
            >
              founders@papercrane.bio
            </a>{" "}
            to raise it.
          </p>
        </div>
        <div className="text-right">
          <p className="font-sans text-[12px] text-graphite-soft">
            Used
          </p>
          <p
            className={`mt-1 font-mono text-[20px] tabular-nums ${labelColor}`}
          >
            {pctDisplay}%
          </p>
        </div>
      </div>

      {/* Progress bar */}
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Number(pctDisplay)}
        className="mt-6 h-2 w-full overflow-hidden rounded-full bg-lattice"
      >
        <div
          className={`h-full ${barColor} transition-[width] duration-500 ease-out`}
          style={{ width: `${pct * 100}%` }}
        />
      </div>

      {/* Recent jobs */}
      <div className="mt-8">
        <h3 className="font-sans text-[12px] text-graphite-soft">
          Recent jobs
        </h3>
        {data.recentJobs.length === 0 ? (
          <p className="mt-3 font-sans text-[13px] text-graphite">
            No jobs submitted yet: spend is $0.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full font-sans text-[13px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-[0.14em] text-graphite-soft">
                  <th className="py-2 pr-3 font-normal">Date</th>
                  <th className="py-2 pr-3 font-normal">Tool</th>
                  <th className="py-2 pr-3 font-normal">GPU</th>
                  <th className="py-2 pr-3 font-normal">Job</th>
                  <th className="py-2 pr-3 text-right font-normal">Estimated</th>
                  <th className="py-2 text-right font-normal">Actual</th>
                </tr>
              </thead>
              <tbody>
                {data.recentJobs.map((row) => (
                  <tr key={row.id}>
                    <td className="py-2 pr-3 text-graphite">
                      {new Date(row.createdAt).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                      })}
                    </td>
                    <td className="py-2 pr-3 font-mono text-[12px] text-ink">
                      {row.tool}
                    </td>
                    <td className="py-2 pr-3 font-mono text-[12px] text-graphite">
                      {row.gpuType}
                    </td>
                    <td className="py-2 pr-3 font-mono text-[12px] text-graphite-soft">
                      {row.jobId ? row.jobId.slice(0, 8) : "N/A"}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink">
                      ${row.estimatedUsd.toFixed(2)}
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-ink">
                      {row.actualUsd === null ? (
                        <span className="text-graphite-soft">pending</span>
                      ) : (
                        `$${row.actualUsd.toFixed(2)}`
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
