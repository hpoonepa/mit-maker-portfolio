/**
 * SolubleMPNN adapter — solubility-optimized inverse folding.
 * Modal app: `tools/solublempnn/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'solublempnn';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
