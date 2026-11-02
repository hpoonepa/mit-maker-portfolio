/**
 * AlphaFold 3 adapter — closed-weights complex prediction (commercial API).
 *
 * Unlike the other 11 adapters AF3 uses an HTTP transport (DeepMind /
 * Isomorphic API), not Modal — the manifest's `transport.type === 'https'`
 * surfaces this. The registry still routes by slug; the actual HTTP wiring
 * lives in the ModalProvider's transport-aware branch (or a future
 * dedicated `apiProvider`).
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'alphafold3';
export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
