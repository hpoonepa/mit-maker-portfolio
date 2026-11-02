/** MAFFT adapter — multiple protein sequence alignment. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "mafft";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
