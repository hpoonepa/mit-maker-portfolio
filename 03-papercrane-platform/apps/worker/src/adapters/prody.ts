/** ProDy adapter — protein normal-mode dynamics analysis. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "prody";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
