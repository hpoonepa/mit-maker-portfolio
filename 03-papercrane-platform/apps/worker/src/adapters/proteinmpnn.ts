/**
 * ProteinMPNN adapter — sequence design (inverse folding).
 * Modal app: `tools/proteinmpnn/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'proteinmpnn';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
