/** ImmuneBuilder adapter — antibody, nanobody, and TCR structure prediction. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "immunebuilder";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
