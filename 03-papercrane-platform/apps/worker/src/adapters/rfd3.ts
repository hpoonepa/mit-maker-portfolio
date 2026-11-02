/** RFdiffusion3 adapter — all-atom constrained protein design. */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'rfd3';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
