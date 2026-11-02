/**
 * Germinal adapter — de novo epitope-targeted antibody/nanobody design (VHH/scFv).
 * License-gated: non-commercial (IgLM + PyRosetta dependencies).
 * Modal app: `tools/germinal/modal_app.py`.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'germinal';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
