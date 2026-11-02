import { redirect } from "next/navigation";

/**
 * Per-target deep-dive pages are withheld until the first reproducible run
 * set is published.
 *
 * This route previously rendered per-cell hit rates, CIs, and cost figures
 * from `benchmark_runs`: rows seeded from the checked-in preview dataset
 * (`packages/brand/benchmark/preview.json`), never from a validated run. The
 * render path is gone. The route is kept so existing `/leaderboard/<target>`
 * URLs land on the pre-registered methodology rather than a 404.
 */

export const metadata = {
  title: "Benchmark: Paper Crane",
  robots: { index: false, follow: true },
};

export default function TargetPage() {
  redirect("/leaderboard");
}
