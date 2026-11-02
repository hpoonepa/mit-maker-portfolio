/** RoseTTAFold3 adapter — all-atom sequence-to-structure prediction. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "rf3";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
