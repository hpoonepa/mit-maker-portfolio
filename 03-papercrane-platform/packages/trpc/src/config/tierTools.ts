/**
 * Plan-tier → allowed toolIds.
 *
 * Free and Pro have the same beta catalogue. Frontier unlocks tools that need
 * either a separate license acknowledgement (Chai-1) or premium compute
 * capacity (AlphaFold 3 via Protenix).
 *
 * Keep the lists in alphabetical order so diffs stay clean.
 */
import type { Tier } from '@papercrane/jobs';

const OPEN_TOOLS: readonly string[] = [
  'antifold',
  'apbs',
  'arpeggio',
  'autodock-vina',
  'bindcraft',
  'boltz1',
  'boltz2',
  'boltzgen',
  'cd-hit',
  'chroma',
  'diamond',
  'disco',
  'dockq',
  'dssp',
  'esm2',
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
  'ligandmpnn',
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
  'proteinmpnn',
  'propka',
  'protparam',
  'rf3',
  'rfd3',
  'rfdiffusion',
  'rfdiffusionaa',
  'smina',
  'solublempnn',
  'thermompnn',
];

const FRONTIER_ONLY: readonly string[] = ['alphafold3', 'chai1', 'germinal'];

export const TIER_TOOL_ALLOWLIST: Record<Tier, string[]> = {
  free: [...OPEN_TOOLS],
  pro: [...OPEN_TOOLS],
  frontier: [...OPEN_TOOLS, ...FRONTIER_ONLY],
};

export function isToolAllowedForTier(tier: Tier, toolId: string): boolean {
  const list = TIER_TOOL_ALLOWLIST[tier];
  return list.includes(toolId);
}
