/**
 * Boltz-1 adapter — open structure prediction.
 * Modal app: `tools/boltz1/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'boltz1';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
