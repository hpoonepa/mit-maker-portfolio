/**
 * GET /api/leaderboard: public read-only benchmark snapshot.
 *
 * No results are published yet. This endpoint previously served aggregated
 * rows straight out of `benchmark_runs`, which is seeded from the checked-in
 * preview dataset (`packages/brand/benchmark/preview.json` via
 * `benchmark/migrate`) and has never been populated by a validated run. Any
 * consumer would have treated illustrative numbers as measured ones, so the
 * aggregation path is disconnected here rather than merely hidden in the UI.
 *
 * It returns a well-formed empty snapshot (`totalRuns: 0`) so existing
 * clients keep working and render their empty state. Restore the
 * `loadLeaderboard()` call: it is still exported from
 * `lib/leaderboard/query.ts` and unit-tested: once the dispatcher produces
 * run manifests that reproduce from a clean environment under methodology
 * v1.0 §11.
 */

import { NextResponse } from "next/server";
import { emptySnapshot } from "@/lib/leaderboard/query";

export const revalidate = 3600;
export const dynamic = "force-static";

export async function GET(req: Request) {
  const version = new URL(req.url).searchParams.get("version") ?? undefined;

  return NextResponse.json(
    {
      ...emptySnapshot(version),
      published: false,
      status: "pre-registered",
      note: "Benchmark methodology v1.0 is pre-registered and public; no run set has been published yet.",
      methodologyUrl:
        "https://github.com/papercrane-bio/benchmark/blob/main/methodology-v1.0.md",
      governanceUrl:
        "https://github.com/papercrane-bio/benchmark/blob/main/GOVERNANCE.md",
    },
    {
      headers: {
        "cache-control": "public, s-maxage=3600, stale-while-revalidate=86400",
      },
    },
  );
}
