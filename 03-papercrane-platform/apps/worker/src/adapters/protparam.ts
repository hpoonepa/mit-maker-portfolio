/** Biopython ProtParam adapter — protein sequence physicochemical analysis. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "protparam";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
