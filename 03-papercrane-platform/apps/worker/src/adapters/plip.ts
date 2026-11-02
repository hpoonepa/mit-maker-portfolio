/** PLIP adapter — protein-ligand interaction profiling. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "plip";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
