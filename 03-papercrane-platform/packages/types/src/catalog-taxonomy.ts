import { z } from "zod";

/**
 * Catalog taxonomy — the single source of truth for how the tool catalog is
 * organized across every surface (marketing roster, dashboard catalog, job
 * picker).
 *
 * The problem this solves: tools historically carried a handful of different
 * `category` vocabularies (DB enum `backbone`/`composite`/`ranking`, manifest
 * kebab `binder-design`/`structure-prediction`, manifest snake
 * `backbone_generation`/`embedding_scoring`). Each UI surface re-derived its
 * own grouping, so the same 15 models were presented three different ways.
 *
 * Here we collapse all of that into FOUR functional buckets keyed by what a
 * user is trying to do:
 *
 *   • binder-design       — get binders for a target (end-to-end models +
 *                           backbone→sequence pipelines + combo cards)
 *   • sequence-design     — design a sequence for a backbone (the MPNN family)
 *   • structure-prediction— fold / validate a complex
 *   • scoring             — embeddings, ranking, filtering
 *
 * Combo cards (e.g. RFdiffusion → ProteinMPNN) are curated catalog entries
 * that are NOT rows in the `tools` table. Real stage-to-stage chaining is a
 * follow-up milestone, so they ship with `status: 'coming_soon'`.
 */

export const CATALOG_CATEGORY_KEYS = [
  "binder-design",
  "sequence-design",
  "structure-prediction",
  "scoring",
] as const;

export const CatalogCategoryKeySchema = z.enum(CATALOG_CATEGORY_KEYS);
export type CatalogCategoryKey = (typeof CATALOG_CATEGORY_KEYS)[number];

export interface CatalogCategoryMeta {
  key: CatalogCategoryKey;
  /** Human section heading, e.g. "Binder design". */
  label: string;
  /** One-line explainer shown under the section heading. */
  tagline: string;
  /** Display order (ascending). */
  order: number;
}

export const CATALOG_CATEGORIES: readonly CatalogCategoryMeta[] = [
  {
    key: "binder-design",
    label: "Binder design",
    tagline:
      "Design binders for a target — end-to-end models and backbone → sequence pipelines.",
    order: 0,
  },
  {
    key: "sequence-design",
    label: "Sequence design",
    tagline: "Design a sequence for a given backbone — the MPNN family.",
    order: 1,
  },
  {
    key: "structure-prediction",
    label: "Structure prediction",
    tagline: "Fold and validate complexes.",
    order: 2,
  },
  {
    key: "scoring",
    label: "Embeddings & scoring",
    tagline: "Rank, filter, and score designs.",
    order: 3,
  },
] as const;

/**
 * Every category vocabulary we have ever emitted → its functional bucket.
 * Covers DB enum, manifest kebab-case, and manifest snake_case forms so any
 * surface can hand us whatever it has without pre-normalizing.
 */
const CATEGORY_ALIASES: Record<string, CatalogCategoryKey> = {
  // — binder design (backbone generators, composites, and utility land here) —
  backbone: "binder-design",
  "backbone-generation": "binder-design",
  backbone_generation: "binder-design",
  composite: "binder-design",
  "binder-design": "binder-design",
  binder_design: "binder-design",
  utility: "binder-design",
  // — sequence design (MPNN family) —
  sequence: "sequence-design",
  "sequence-design": "sequence-design",
  sequence_design: "sequence-design",
  // — structure prediction —
  structure: "structure-prediction",
  "structure-prediction": "structure-prediction",
  structure_prediction: "structure-prediction",
  // — embeddings & scoring —
  ranking: "scoring",
  validation: "scoring",
  scoring: "scoring",
  embedding_scoring: "scoring",
  "embedding-scoring": "scoring",
};

/**
 * Normalize any known category string into one of the four buckets. Unknown
 * values default to `binder-design` (never silently dropped) — the same
 * "never lose a catalog entry" stance the ToolPicker took.
 */
export function toCatalogCategory(raw: string): CatalogCategoryKey {
  const key = typeof raw === "string" ? raw.toLowerCase() : raw;
  return CATEGORY_ALIASES[key] ?? "binder-design";
}

/** Convenience: category string → human section label. */
export function catalogCategoryLabel(raw: string): string {
  const key = toCatalogCategory(raw);
  const meta = CATALOG_CATEGORIES.find((c) => c.key === key);
  // CATALOG_CATEGORIES is exhaustive over CatalogCategoryKey, so this is safe.
  return meta ? meta.label : "Binder design";
}

export type ComboStatus = "coming_soon" | "available";

/**
 * A curated multi-stage pipeline surfaced as a single card. Combos are NOT
 * `tools` rows — they are static config here until real chaining lands, at
 * which point `status` flips to `available` and the worker executes the
 * stages in order (the `compose()` adapter already models this).
 */
export interface ComboCard {
  /** `a+b` id, matching the compose() adapter's manifest id convention. */
  id: string;
  name: string;
  /** Ordered tool slugs the pipeline runs. */
  stages: readonly string[];
  category: CatalogCategoryKey;
  tagline: string;
  tier: "free" | "pro" | "frontier";
  status: ComboStatus;
}

export const COMBO_CARDS: readonly ComboCard[] = [
  {
    id: "rfdiffusion+proteinmpnn",
    name: "RFdiffusion → ProteinMPNN",
    stages: ["rfdiffusion", "proteinmpnn"],
    category: "binder-design",
    tagline:
      "De novo backbone, then sequence design — the classic scaffold route.",
    tier: "free",
    status: "coming_soon",
  },
  {
    id: "rfdiffusionaa+ligandmpnn",
    name: "RFdiffusionAA → LigandMPNN",
    stages: ["rfdiffusionaa", "ligandmpnn"],
    category: "binder-design",
    tagline:
      "Ligand-aware backbone and sequence design for small-molecule sites.",
    tier: "free",
    status: "coming_soon",
  },
] as const;

/** Combo cards that belong in a given category bucket. */
export function combosForCategory(key: CatalogCategoryKey): ComboCard[] {
  return COMBO_CARDS.filter((c) => c.category === key);
}

/**
 * What KIND of input a tool needs to run. This is finer-grained than the
 * catalog category: two tools can share a category but need different inputs
 * (e.g. Boltz-2 co-folds two structures while Boltz-1 takes raw sequences —
 * both are "structure-prediction"). The job wizard renders the matching input
 * form off this, and multi-select is constrained so every selected tool shares
 * one input kind (otherwise a single input form can't serve them all).
 *
 *   • target     — a target PDB (+ optional hotspots); the tool designs a binder
 *   • backbone   — a backbone PDB to redesign the sequence of (inverse folding)
 *   • complex    — two structures (target + partner) to co-fold
 *   • sequences  — one or more raw amino-acid sequences (scoring / seq-only)
 */
export type ToolInputKind = "target" | "backbone" | "complex" | "sequences";

/** Whether a tool takes a small-molecule ligand alongside its main input. */
export type LigandSupport = "none" | "optional" | "required";

export interface ToolInputSpec {
  inputKind: ToolInputKind;
  /** Does the tool make use of hotspot residues? (only ever for `target`.) */
  needsHotspots: boolean;
  ligand: LigandSupport;
}

const DEFAULT_INPUT_SPEC: ToolInputSpec = {
  inputKind: "target",
  needsHotspots: false,
  ligand: "none",
};

/**
 * Per-tool input requirements, derived from each tool's `schemas/input.json`
 * and adapter resolution logic. Keyed by tool slug (== tool id).
 */
export const TOOL_INPUT_SPECS: Record<string, ToolInputSpec> = {
  // — binder design: give a target, the tool designs the binder —
  rfdiffusion: { inputKind: "target", needsHotspots: true, ligand: "none" },
  rfdiffusionaa: {
    inputKind: "target",
    needsHotspots: true,
    ligand: "optional",
  },
  chroma: { inputKind: "target", needsHotspots: true, ligand: "none" },
  bindcraft: { inputKind: "target", needsHotspots: true, ligand: "none" },
  boltzgen: { inputKind: "target", needsHotspots: true, ligand: "optional" },
  germinal: { inputKind: "target", needsHotspots: true, ligand: "none" },
  rfd3: { inputKind: "target", needsHotspots: true, ligand: "optional" },
  disco: { inputKind: "sequences", needsHotspots: false, ligand: "optional" },
  // — sequence design: give a backbone, the tool designs the sequence —
  proteinmpnn: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  solublempnn: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  ligandmpnn: {
    inputKind: "backbone",
    needsHotspots: false,
    ligand: "required",
  },
  antifold: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  thermompnn: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  esmif1: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  // — structure prediction: co-fold two given structures —
  boltz2: { inputKind: "complex", needsHotspots: false, ligand: "none" },
  chai1: { inputKind: "complex", needsHotspots: false, ligand: "none" },
  alphafold3: { inputKind: "complex", needsHotspots: false, ligand: "none" },
  rf3: { inputKind: "sequences", needsHotspots: false, ligand: "optional" },
  esmfold: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  pdbfixer: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  evoef2: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  "openmm-relax": {
    inputKind: "backbone",
    needsHotspots: false,
    ligand: "none",
  },
  omegafold: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  immunebuilder: {
    inputKind: "sequences",
    needsHotspots: false,
    ligand: "none",
  },
  foldseek: { inputKind: "complex", needsHotspots: false, ligand: "none" },
  p2rank: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  freesasa: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  "autodock-vina": {
    inputKind: "backbone",
    needsHotspots: false,
    ligand: "required",
  },
  plip: { inputKind: "backbone", needsHotspots: false, ligand: "optional" },
  dssp: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  fpocket: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  mdanalysis: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  pdb2pqr: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  propka: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  apbs: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  smina: {
    inputKind: "backbone",
    needsHotspots: false,
    ligand: "required",
  },
  prody: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  "pdb-tools": {
    inputKind: "backbone",
    needsHotspots: false,
    ligand: "none",
  },
  prodigy: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  arpeggio: { inputKind: "backbone", needsHotspots: false, ligand: "none" },
  dockq: { inputKind: "complex", needsHotspots: false, ligand: "none" },
  // — sequence-only: raw sequences in (boltz1 is seq-based; ESM scores seqs) —
  boltz1: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  esm2: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  esmc: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  mmseqs2: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  hmmer: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  mafft: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  protparam: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  parasail: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  "cd-hit": { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  diamond: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
  hhsuite: { inputKind: "sequences", needsHotspots: false, ligand: "none" },
};

/** Input spec for a tool slug; unknown tools default to `target`/no-ligand. */
export function toolInputSpec(slug: string): ToolInputSpec {
  return TOOL_INPUT_SPECS[slug] ?? DEFAULT_INPUT_SPEC;
}

/**
 * The input kind a job takes, given its selected tool slugs. Returns `null` for
 * an empty selection. Multi-select is constrained (in the picker) so every
 * selected tool shares one kind, so the first tool's kind represents the job.
 */
export function jobInputKind(slugs: readonly string[]): ToolInputKind | null {
  if (slugs.length === 0) return null;
  return toolInputSpec(slugs[0]!).inputKind;
}

/**
 * The strongest ligand requirement across a set of selected tools:
 * `required` if any tool requires it, else `optional` if any supports it,
 * else `none`.
 */
export function jobLigandRequirement(slugs: readonly string[]): LigandSupport {
  let result: LigandSupport = "none";
  for (const slug of slugs) {
    const l = toolInputSpec(slug).ligand;
    if (l === "required") return "required";
    if (l === "optional") result = "optional";
  }
  return result;
}
