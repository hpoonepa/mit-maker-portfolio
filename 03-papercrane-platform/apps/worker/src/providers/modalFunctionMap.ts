/**
 * Tool id → Modal Function mapping.
 *
 * Each Paper Crane tool image is deployed on Modal as a separately versioned
 * Function. The owning workspace is read from `MODAL_WORKSPACE` at resolve
 * time (default: `boozercam660`, the developer's authenticated profile).
 * `MODAL_FUNCTIONS` only carries the per-tool name + major version — the
 * workspace is layered on by `resolveModalFunction()` so the same map works
 * across local dev, staging, and prod without rewrites.
 *
 * If a `toolVersion` is provided we prefer a version-specific entry (e.g.
 * `bindcraft@1.0.0`); otherwise we fall back to the tool default.
 *
 * New tools added to the registry MUST be mirrored here — a missing entry
 * will surface as `UnknownModalFunctionError` at spawn time rather than a
 * silent 404 from Modal.
 */

export interface ModalFunctionRef {
  /** Modal workspace that owns the deployed Function. */
  workspace: string;
  /** Deployed Function name (matches `@app.function(name=...)`). */
  name: string;
  /** Name passed to `modal.Function.from_name` for deployed invocations. */
  appName: string;
  /** Exported function inside the deployed app. */
  entrypoint: string;
  /** Function returns its NDJSON events in the result instead of log streaming. */
  returnsEvents: boolean;
  /** Optional version tag, surfaces in Modal URL path. */
  version?: string;
}

/** Workspace fallback when `MODAL_WORKSPACE` is unset. */
export const DEFAULT_MODAL_WORKSPACE = "boozercam660";

/** Read the active Modal workspace from env, falling back to the default. */
export function getModalWorkspace(): string {
  const v = process.env.MODAL_WORKSPACE;
  return v && v.length > 0 ? v : DEFAULT_MODAL_WORKSPACE;
}

/**
 * Per-tool Function name + major version. Workspace is filled in by
 * `resolveModalFunction()` at call time so it can be overridden via env.
 */
type ModalFunctionEntry = Omit<ModalFunctionRef, "workspace">;

const UNPREFIXED_MODAL_APPS = new Set([
  "alphafold3",
  "boltz1",
  "boltz2",
  "boltzgen",
  "chai1",
  "chroma",
  "esm2",
  "ligandmpnn",
  "solublempnn",
]);

function deployedRef(toolId: string): ModalFunctionEntry {
  return {
    // `name` stays stable for the legacy injected HTTP client used in tests.
    name: toolId,
    appName: UNPREFIXED_MODAL_APPS.has(toolId)
      ? toolId
      : `papercrane-${toolId}`,
    entrypoint: toolId === "solublempnn" ? "predict" : "papercrane_dispatch",
    returnsEvents: new Set(["rfdiffusion", "proteinmpnn", "boltz2", "esm2"]).has(toolId),
    version: "1",
  };
}

const LEGACY_MODAL_FUNCTIONS: Record<string, { name: string; version: string }> = {
  bindcraft: { name: "bindcraft", version: "1" },
  rfdiffusion: { name: "rfdiffusion", version: "1" },
  proteinmpnn: { name: "proteinmpnn", version: "1" },
  boltz1: { name: "boltz1", version: "1" },
  boltz2: { name: "boltz2", version: "1" },
  boltzgen: { name: "boltzgen", version: "1" },
  chai1: { name: "chai1", version: "1" },
  chroma: { name: "chroma", version: "1" },
  alphafold2: { name: "alphafold2", version: "1" },
  // AlphaFold 3-compatible inference runs through the Protenix Modal adapter.
  alphafold3: { name: "alphafold3", version: "1" },
  ligandmpnn: { name: "ligandmpnn", version: "1" },
  solublempnn: { name: "solublempnn", version: "1" },
  esm2: { name: "esm2", version: "1" },
  esmc: { name: "esmc", version: "1" },
  germinal: { name: "germinal", version: "1" },
  rfdiffusionaa: { name: "rfdiffusionaa", version: "1" },
  rfd3: { name: "rfd3", version: "1" },
  rf3: { name: "rf3", version: "1" },
  antifold: { name: "antifold", version: "1" },
  thermompnn: { name: "thermompnn", version: "1" },
  pdbfixer: { name: "pdbfixer", version: "1" },
  esmfold: { name: "esmfold", version: "1" },
  disco: { name: "disco", version: "1" },
  esmif1: { name: "esmif1", version: "1" },
  evoef2: { name: "evoef2", version: "1" },
  omegafold: { name: "omegafold", version: "1" },
  immunebuilder: { name: "immunebuilder", version: "1" },
  "openmm-relax": { name: "openmm-relax", version: "1" },
  foldseek: { name: "foldseek", version: "1" },
  p2rank: { name: "p2rank", version: "1" },
  freesasa: { name: "freesasa", version: "1" },
  "autodock-vina": { name: "autodock-vina", version: "1" },
  plip: { name: "plip", version: "1" },
  mmseqs2: { name: "mmseqs2", version: "1" },
  hmmer: { name: "hmmer", version: "1" },
  mafft: { name: "mafft", version: "1" },
  dssp: { name: "dssp", version: "1" },
  fpocket: { name: "fpocket", version: "1" },
  mdanalysis: { name: "mdanalysis", version: "1" },
  pdb2pqr: { name: "pdb2pqr", version: "1" },
  propka: { name: "propka", version: "1" },
  apbs: { name: "apbs", version: "1" },
  smina: { name: "smina", version: "1" },
  protparam: { name: "protparam", version: "1" },
  parasail: { name: "parasail", version: "1" },
  "cd-hit": { name: "cd-hit", version: "1" },
  diamond: { name: "diamond", version: "1" },
  hhsuite: { name: "hhsuite", version: "1" },
  prody: { name: "prody", version: "1" },
  "pdb-tools": { name: "pdb-tools", version: "1" },
  prodigy: { name: "prodigy", version: "1" },
  arpeggio: { name: "arpeggio", version: "1" },
  dockq: { name: "dockq", version: "1" },
};

export const MODAL_FUNCTIONS: Record<string, ModalFunctionEntry> =
  Object.fromEntries(
    Object.keys(LEGACY_MODAL_FUNCTIONS).map((toolId) => [
      toolId,
      deployedRef(toolId),
    ]),
  );

export class UnknownModalFunctionError extends Error {
  constructor(public readonly toolId: string) {
    super(`No Modal function mapping for tool: ${toolId}`);
    this.name = "UnknownModalFunctionError";
  }
}

/**
 * Resolve a tool id (and optional semantic version) to a deployed Modal Function.
 *
 * Version resolution is deliberately simple: if callers pass a semver like
 * `1.2.3`, we key on the major (`1`) because Modal deploys pin major versions.
 * Breaking changes bump the Function name, not the version tag.
 */
export function resolveModalFunction(
  toolId: string,
  toolVersion?: string,
  workspaceOverride?: string,
): ModalFunctionRef {
  const base = MODAL_FUNCTIONS[toolId];
  if (!base) throw new UnknownModalFunctionError(toolId);

  const workspace =
    workspaceOverride && workspaceOverride.length > 0
      ? workspaceOverride
      : getModalWorkspace();

  if (!toolVersion) return { workspace, ...base };

  const major = toolVersion.split(".")[0];
  if (!major || major === base.version) return { workspace, ...base };

  // Allow major-version overrides without forcing every entry to be exhaustive.
  return { workspace, ...base, version: major };
}
