/**
 * Chroma adapter — generative protein backbone diffusion (Generate Biomedicines).
 * Modal app: `tools/chroma/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'chroma';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
