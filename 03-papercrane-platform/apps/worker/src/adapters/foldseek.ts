/** Foldseek adapter — pairwise protein structure comparison. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "foldseek";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
