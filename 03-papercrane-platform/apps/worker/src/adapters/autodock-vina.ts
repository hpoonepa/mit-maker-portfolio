/** AutoDock Vina adapter — CPU protein-ligand docking. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "autodock-vina";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
