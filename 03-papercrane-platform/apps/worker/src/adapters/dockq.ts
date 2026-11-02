/** DockQ adapter — docking-model quality assessment. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "dockq";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
