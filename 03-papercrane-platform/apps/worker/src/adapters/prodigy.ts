/** PRODIGY adapter — protein-protein binding-affinity prediction. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "prodigy";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
