/** CD-HIT adapter — protein sequence clustering. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "cd-hit";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
