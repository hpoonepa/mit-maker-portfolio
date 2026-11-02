import type { Metadata } from "next";
import { redirect } from "next/navigation";

/**
 * Per-model benchmark detail pages are withheld until the first reproducible
 * run set is published.
 *
 * This route previously rendered per-model metrics sourced from the
 * checked-in preview dataset (`packages/brand/benchmark/preview.json`). That
 * dataset is illustrative, not measured, so the render path is gone. The
 * route is kept: rather than deleted: so previously published or indexed
 * `/benchmark/<tool>` URLs land on the pre-registered methodology instead of
 * a 404. It will be restored when real per-model results exist.
 */

export const metadata: Metadata = {
  title: "Benchmark",
  robots: { index: false, follow: true },
};

export default function ModelDetailPage() {
  redirect("/benchmark");
}
