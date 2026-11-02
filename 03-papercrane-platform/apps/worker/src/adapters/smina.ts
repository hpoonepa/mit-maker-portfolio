/** smina adapter — CPU protein-ligand docking. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "smina";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
