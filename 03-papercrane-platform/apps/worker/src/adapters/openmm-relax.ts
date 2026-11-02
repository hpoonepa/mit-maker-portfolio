/** OpenMM Relax adapter — all-atom minimization and structure cleanup. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "openmm-relax";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
