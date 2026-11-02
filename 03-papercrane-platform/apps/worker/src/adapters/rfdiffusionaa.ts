/**
 * RFdiffusion All-Atom adapter — ligand- and metal-aware backbone generation.
 *
 * Modal app: `tools/rfdiffusionaa/modal_app.py` (not deployed yet — stub).
 * This module is the typed entrypoint the registry routes to; real GPU
 * dispatch happens through `ModalProvider` from the processor.
 */
import type { ToolAdapter } from '@papercrane/jobs';
import { runViaModal } from './_modalRunner';

export const SLUG = 'rfdiffusionaa';

export const run: ToolAdapter = (input, opts) => runViaModal(SLUG, input, opts);
