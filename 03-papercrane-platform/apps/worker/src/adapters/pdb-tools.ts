/** pdb-tools adapter — deterministic PDB cleanup and validation. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "pdb-tools";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
