/**
 * BindCraft adapter — composite binder design (RFdiffusion + MPNN + AF2).
 * Modal app: `tools/bindcraft/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'bindcraft';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
