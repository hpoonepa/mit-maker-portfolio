/** fpocket adapter — geometry-based protein binding-pocket detection. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "fpocket";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
