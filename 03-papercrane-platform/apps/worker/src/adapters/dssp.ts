/** DSSP adapter — secondary-structure assignment from protein coordinates. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "dssp";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
