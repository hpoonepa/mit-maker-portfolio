/** HH-suite adapter — profile-to-profile protein comparison. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "hhsuite";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
