/**
 * ESM2 adapter — protein language model embeddings + PLL scoring.
 * Modal app: `tools/esm2/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'esm2';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
