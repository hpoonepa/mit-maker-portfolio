/** ThermoMPNN adapter — stability-guided point-mutation design. */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'thermompnn';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
