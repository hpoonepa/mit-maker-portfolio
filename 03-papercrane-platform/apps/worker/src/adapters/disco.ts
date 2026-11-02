/** DISCO adapter — joint sequence/structure protein co-design. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "disco";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
