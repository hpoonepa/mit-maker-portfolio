/** PDBFixer adapter — structure repair and preparation. */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'pdbfixer';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
