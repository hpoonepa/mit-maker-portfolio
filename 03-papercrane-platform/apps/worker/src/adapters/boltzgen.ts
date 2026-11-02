/**
 * BoltzGen adapter — all-atom diffusion-based binder design.
 * Modal app: `tools/boltzgen/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'boltzgen';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
