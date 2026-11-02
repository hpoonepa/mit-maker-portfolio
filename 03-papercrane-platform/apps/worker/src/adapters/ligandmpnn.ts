/**
 * LigandMPNN adapter — ligand-aware sequence design.
 * Modal app: `tools/ligandmpnn/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'ligandmpnn';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
