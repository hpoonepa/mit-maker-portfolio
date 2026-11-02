/**
 * Adapter registry — slug → ToolAdapter mapping for all 52 registered tools.
 *
 * The job processor calls `getAdapter(toolSlug)` to dispatch a stage. Each
 * entry corresponds to:
 *
 *   • A `tools/<slug>/manifest.json` row (seeded into the `tools` table).
 *   • A `tools/<slug>/modal_app.py` Modal Function (deployment owned by
 *     `MODAL_FUNCTIONS` in `providers/modalFunctionMap.ts`).
 *   • A typed entrypoint in `apps/worker/src/adapters/<slug>.ts`.
 *
 * Adding a new tool requires touching all three. The unit test in
 * `__tests__/registry.test.ts` (when added) asserts parity between the seed
 * list, the modal map, and this registry so drift is caught at CI time.
 */
import type { ToolAdapter } from "@papercrane/jobs";

import { run as alphafold3 } from "./alphafold3";
import { run as antifold } from "./antifold";
import { run as apbs } from "./apbs";
import { run as arpeggio } from "./arpeggio";
import { run as autodockVina } from "./autodock-vina";
import { run as bindcraft } from "./bindcraft";
import { run as boltz1 } from "./boltz1";
import { run as boltz2 } from "./boltz2";
import { run as boltzgen } from "./boltzgen";
import { run as chai1 } from "./chai1";
import { run as chroma } from "./chroma";
import { run as cdHit } from "./cd-hit";
import { run as diamond } from "./diamond";
import { run as disco } from "./disco";
import { run as dockq } from "./dockq";
import { run as dssp } from "./dssp";
import { run as esm2 } from "./esm2";
import { run as esmfold } from "./esmfold";
import { run as esmc } from "./esmc";
import { run as esmif1 } from "./esmif1";
import { run as evoef2 } from "./evoef2";
import { run as foldseek } from "./foldseek";
import { run as fpocket } from "./fpocket";
import { run as freesasa } from "./freesasa";
import { run as germinal } from "./germinal";
import { run as hmmer } from "./hmmer";
import { run as hhsuite } from "./hhsuite";
import { run as immunebuilder } from "./immunebuilder";
import { run as ligandmpnn } from "./ligandmpnn";
import { run as mafft } from "./mafft";
import { run as mdanalysis } from "./mdanalysis";
import { run as mmseqs2 } from "./mmseqs2";
import { run as omegafold } from "./omegafold";
import { run as openmmRelax } from "./openmm-relax";
import { run as p2rank } from "./p2rank";
import { run as pdb2pqr } from "./pdb2pqr";
import { run as pdbfixer } from "./pdbfixer";
import { run as pdbTools } from "./pdb-tools";
import { run as parasail } from "./parasail";
import { run as plip } from "./plip";
import { run as propka } from "./propka";
import { run as prodigy } from "./prodigy";
import { run as prody } from "./prody";
import { run as proteinmpnn } from "./proteinmpnn";
import { run as protparam } from "./protparam";
import { run as rf3 } from "./rf3";
import { run as rfd3 } from "./rfd3";
import { run as rfdiffusion } from "./rfdiffusion";
import { run as rfdiffusionaa } from "./rfdiffusionaa";
import { run as smina } from "./smina";
import { run as solublempnn } from "./solublempnn";
import { run as thermompnn } from "./thermompnn";

/**
 * The 52 tool slugs the registry knows about. Must stay in sync with
 * `packages/db/prisma/seed.ts` `TOOL_SLUGS` and the Modal function map.
 */
export const KNOWN_TOOL_SLUGS = [
  "alphafold3",
  "antifold",
  "apbs",
  "arpeggio",
  "autodock-vina",
  "bindcraft",
  "boltz1",
  "boltz2",
  "boltzgen",
  "chai1",
  "chroma",
  "cd-hit",
  "diamond",
  "disco",
  "dockq",
  "dssp",
  "esm2",
  "esmfold",
  "esmc",
  "esmif1",
  "evoef2",
  "foldseek",
  "fpocket",
  "freesasa",
  "germinal",
  "hmmer",
  "hhsuite",
  "immunebuilder",
  "ligandmpnn",
  "mafft",
  "mdanalysis",
  "mmseqs2",
  "omegafold",
  "openmm-relax",
  "p2rank",
  "pdb2pqr",
  "pdbfixer",
  "pdb-tools",
  "parasail",
  "plip",
  "propka",
  "prodigy",
  "prody",
  "proteinmpnn",
  "protparam",
  "rf3",
  "rfd3",
  "rfdiffusion",
  "rfdiffusionaa",
  "smina",
  "solublempnn",
  "thermompnn",
] as const;
export type KnownToolSlug = (typeof KNOWN_TOOL_SLUGS)[number];

export const ADAPTER_REGISTRY: Record<KnownToolSlug, ToolAdapter> = {
  alphafold3,
  antifold,
  apbs,
  arpeggio,
  "autodock-vina": autodockVina,
  bindcraft,
  boltz1,
  boltz2,
  boltzgen,
  chai1,
  chroma,
  "cd-hit": cdHit,
  diamond,
  disco,
  dockq,
  dssp,
  esm2,
  esmfold,
  esmc,
  esmif1,
  evoef2,
  foldseek,
  fpocket,
  freesasa,
  germinal,
  hmmer,
  hhsuite,
  immunebuilder,
  ligandmpnn,
  mafft,
  mdanalysis,
  mmseqs2,
  omegafold,
  "openmm-relax": openmmRelax,
  p2rank,
  pdb2pqr,
  pdbfixer,
  "pdb-tools": pdbTools,
  parasail,
  plip,
  propka,
  prodigy,
  prody,
  proteinmpnn,
  protparam,
  rf3,
  rfd3,
  rfdiffusion,
  rfdiffusionaa,
  smina,
  solublempnn,
  thermompnn,
};

export class UnknownToolError extends Error {
  constructor(public readonly slug: string) {
    super(`No adapter registered for tool slug: ${slug}`);
    this.name = "UnknownToolError";
  }
}

/**
 * Resolve a tool slug to its adapter. Throws `UnknownToolError` if the slug
 * isn't registered (catch this in the processor and mark the job
 * `failed/unknown_tool`).
 */
export function getAdapter(slug: string): ToolAdapter {
  const adapter = (ADAPTER_REGISTRY as Record<string, ToolAdapter>)[slug];
  if (!adapter) throw new UnknownToolError(slug);
  return adapter;
}
