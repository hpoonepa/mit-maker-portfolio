/** PROPKA adapter — CPU residue pKa prediction. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "propka";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
