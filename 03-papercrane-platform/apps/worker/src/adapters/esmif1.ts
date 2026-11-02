/** ESM-IF1 adapter — fixed-backbone inverse folding. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "esmif1";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
