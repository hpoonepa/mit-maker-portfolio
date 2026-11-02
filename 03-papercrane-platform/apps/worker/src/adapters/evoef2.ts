/** EvoEF2 adapter — physics-based stability and interface scoring. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "evoef2";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
