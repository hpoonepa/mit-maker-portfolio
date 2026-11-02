/** FreeSASA adapter — solvent-accessible surface-area calculation. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "freesasa";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
