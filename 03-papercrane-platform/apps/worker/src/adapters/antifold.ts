/** AntiFold adapter — antibody and nanobody inverse folding. */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'antifold';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
