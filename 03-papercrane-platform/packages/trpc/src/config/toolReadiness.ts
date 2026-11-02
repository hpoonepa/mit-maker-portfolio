/** Tools that have completed a live end-to-end production verification. */
export const GA_TOOL_SLUGS = [
  'alphafold3',
  'bindcraft',
  'boltz1',
  'boltz2',
  'boltzgen',
  'chai1',
  'chroma',
  'esm2',
  'ligandmpnn',
  'proteinmpnn',
  'rfdiffusion',
  'solublempnn',
] as const;

/**
 * Tools with a checked-in manifest, worker adapter, Modal mapping, and real
 * dispatch implementation. They are runnable, but stay visibly beta until a
 * live production smoke promotes them to {@link GA_TOOL_SLUGS}.
 *
 * Germinal is intentionally absent: its Modal image still pins a zero SHA and
 * identifies itself as an unbuilt stub.
 */
export const BETA_RUNNABLE_TOOL_SLUGS = [
  'antifold',
  'apbs',
  'arpeggio',
  'autodock-vina',
  'cd-hit',
  'diamond',
  'disco',
  'dockq',
  'dssp',
  'esmc',
  'esmfold',
  'esmif1',
  'evoef2',
  'foldseek',
  'fpocket',
  'freesasa',
  'hhsuite',
  'hmmer',
  'immunebuilder',
  'mafft',
  'mdanalysis',
  'mmseqs2',
  'omegafold',
  'openmm-relax',
  'p2rank',
  'parasail',
  'pdb-tools',
  'pdb2pqr',
  'pdbfixer',
  'plip',
  'prodigy',
  'prody',
  'propka',
  'protparam',
  'rf3',
  'rfd3',
  'rfdiffusionaa',
  'smina',
  'thermompnn',
] as const;

/** Backwards-compatible name for callers that mean GA-verified. */
export const VERIFIED_RUNNABLE_TOOL_SLUGS = GA_TOOL_SLUGS;

export type VerifiedRunnableToolSlug = (typeof GA_TOOL_SLUGS)[number];

const GA_TOOLS = new Set<string>(GA_TOOL_SLUGS);
const RUNNABLE_TOOLS = new Set<string>([
  ...GA_TOOL_SLUGS,
  ...BETA_RUNNABLE_TOOL_SLUGS,
]);

export function isToolRunnable(toolId: string): boolean {
  return RUNNABLE_TOOLS.has(toolId);
}

export function toolReleaseStatus(toolId: string): 'ga' | 'beta' {
  return GA_TOOLS.has(toolId) ? 'ga' : 'beta';
}
