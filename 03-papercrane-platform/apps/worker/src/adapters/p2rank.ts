/** P2Rank adapter — protein-ligand binding-site prediction. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "p2rank";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
