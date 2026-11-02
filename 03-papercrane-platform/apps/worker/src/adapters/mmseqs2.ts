/** MMseqs2 adapter — pairwise protein sequence homology search. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "mmseqs2";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
