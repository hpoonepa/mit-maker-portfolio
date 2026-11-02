/**
 * Boltz-2 adapter — open structure prediction (next-gen).
 * Modal app: `tools/boltz2/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'boltz2';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
