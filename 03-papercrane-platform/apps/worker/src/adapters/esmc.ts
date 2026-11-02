/**
 * ESM-C 300M adapter — protein language model embeddings + PLL scoring.
 * Modal app: `tools/esmc/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'esmc';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
