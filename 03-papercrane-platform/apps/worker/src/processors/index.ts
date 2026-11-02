/**
 * Processor registry.
 *
 * The "production" processor is `processJob` in `../jobProcessor.ts` — it
 * spawns a real GPU container via the configured Provider (Modal today).
 *
 * The "dev" processor is `runSynthJob` in `./synth-job.ts` — it walks the
 * tool chain on a timer and writes synthetic Design rows. It is wired only
 * by the dev fallback path in `server.ts` and refuses to run when
 * NODE_ENV=production.
 *
 * This file exists as a single import surface so future processors (a
 * benchmark replay processor, a regression-test processor, ...) can be
 * registered alongside without touching `server.ts`.
 */

export { processJob } from '../jobProcessor';
export type {
  ProcessJobInput,
  ProcessJobResult,
} from '../jobProcessor';

export { runSynthJob } from './synth-job';
export type {
  SynthJobInput,
  SynthJobDeps,
  SynthJobResult,
} from './synth-job';

/**
 * Resolve which processor a dev-queue handler should call.
 *
 * Returns `'synth'` only when:
 *   - NODE_ENV !== 'production', AND
 *   - the caller passed `useSynth: true` (the dev-queue branch in server.ts)
 *
 * Otherwise returns `'real'`. This indirection keeps the production path from
 * accidentally importing synth-job.
 */
export function resolveProcessorMode(useSynth: boolean): 'real' | 'synth' {
  if (process.env.NODE_ENV === 'production') return 'real';
  return useSynth ? 'synth' : 'real';
}
