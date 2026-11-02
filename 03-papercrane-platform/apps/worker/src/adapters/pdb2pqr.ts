/** PDB2PQR adapter — CPU protonation and charge/radius preparation. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "pdb2pqr";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
