/** HMMER phmmer adapter — protein sequence homology scoring. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "hmmer";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
