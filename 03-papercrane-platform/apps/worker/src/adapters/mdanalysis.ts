/** MDAnalysis adapter — protein RMSD, radius-of-gyration, and geometry analysis. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "mdanalysis";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
