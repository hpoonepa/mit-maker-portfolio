/** PDBe Arpeggio adapter — interatomic contact analysis. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "arpeggio";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
