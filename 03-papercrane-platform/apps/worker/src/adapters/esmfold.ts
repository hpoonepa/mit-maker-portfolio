/** ESMFold adapter — fast MSA-free sequence-to-structure prediction. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "esmfold";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
