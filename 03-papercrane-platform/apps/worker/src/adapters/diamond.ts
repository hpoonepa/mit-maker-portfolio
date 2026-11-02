/** DIAMOND adapter — request-scoped protein homology search. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "diamond";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
