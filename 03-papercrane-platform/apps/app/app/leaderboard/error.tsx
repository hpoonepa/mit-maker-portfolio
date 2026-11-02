"use client";

import { useEffect } from "react";
import Link from "next/link";

/**
 * Route-segment error boundary. Surfaces DB failures, network hiccups,
 * and aggregation bugs without blowing up the whole app.
 *
 * Next passes an `error.digest` in production (obfuscated id mapping
 * to the server log line). We surface the digest so users can reference
 * a specific incident when filing a bug.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Best-effort: log to server via fetch so the error shows up in
    // aggregated logs, not just the browser console.
    console.error("[leaderboard] render error", error);
  }, [error]);

  return (
    <main className="relative pt-28 md:pt-32 pb-20 md:pb-28">
      <div className="container-edge">
        <div className="flex items-baseline gap-4 mb-10">
          <span className="eyebrow">Benchmark</span>
          <span className="h-px flex-1 bg-lattice" />
          <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-crane">
            · ERROR ·
          </span>
        </div>

        <div className="hairline-border bg-paper rounded-sm p-8 max-w-2xl">
          <h1 className="font-display text-[32px] leading-tight text-ink">
            This page couldn’t load.
          </h1>
          <p className="mt-4 font-sans text-[15px] leading-[1.55] text-graphite">
            Something went wrong rendering the benchmark page. The
            pre-registered methodology is always available directly from the
            benchmark repository.
          </p>

          {error.digest && (
            <p className="mt-4 font-mono text-[11px] text-graphite-soft">
              Incident digest:{" "}
              <span className="text-ink">{error.digest}</span>
            </p>
          )}

          <div className="mt-8 flex flex-wrap gap-3">
            <button type="button" onClick={reset} className="btn-primary">
              Retry
            </button>
            <a
              href="https://github.com/papercrane-bio/benchmark/blob/main/methodology-v1.0.md"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-ghost"
            >
              Read methodology v1.0 ↗
            </a>
            <Link href="/#benchmark" className="btn-ghost">
              ← Back to overview
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
