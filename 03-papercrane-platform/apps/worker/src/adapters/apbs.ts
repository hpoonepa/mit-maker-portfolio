/** APBS adapter — CPU Poisson–Boltzmann electrostatics. */
import type { ToolAdapter } from "@papercrane/jobs";
import { runViaModal } from "./_modalRunner";

export const SLUG = "apbs";
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
