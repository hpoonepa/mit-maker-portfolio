/**
 * Chai-1 adapter — multi-modal complex prediction.
 * Modal app: `tools/chai1/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'chai1';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
