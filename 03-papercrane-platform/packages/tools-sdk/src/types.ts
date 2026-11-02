/**
 * Core domain types for the Paper Crane Tool SDK.
 *
 * These types are intentionally defined locally today; once `@papercrane/types`
 * is populated (see plan doc 02-tool-integration §1) this file will re-export
 * the canonical shapes from that workspace package instead. Consumers should
 * import everything from `@papercrane/tools-sdk` so the future swap is invisible.
 */

// ---------- Normalized request shapes ----------

export interface Residue {
  /** Single-letter chain id (e.g. "A", "B"). */
  chain: string;
  /** 1-indexed residue number. */
  resi: number;
}

export interface DesignConstraints {
  lengthRange?: [number, number];
  disulfides?: boolean;
  solubility?: 'strict' | 'default';
}

export interface DesignRequest {
  /** S3 URI (or local path during dev) to the target PDB. */
  targetPdb: string;
  /** Chain id of the target in `targetPdb`. Optional; tools pick a default. */
  targetChain?: string;
  /** Normalized hotspot residues. */
  hotspots?: Residue[];
  /** Random seeds. The current worker contract emits one design per seed. */
  seeds: number[];
  /** Total designs requested; must equal `seeds.length`. */
  numDesigns: number;
  constraints?: DesignConstraints;
  /** Tool-specific escape hatch — opaque to the core. */
  toolParams?: Record<string, unknown>;
}

// ---------- Result shapes ----------

export interface Design {
  /** S3 URI (or local path) to the predicted PDB/CIF. */
  structurePath: string;
  /** Designed sequence (1-letter codes). */
  sequence: string;
  /** Tool-emitted metrics. Validator image adds canonical metrics later. */
  metrics: Record<string, number>;
  /** Seed that produced this design. */
  seed: number;
}

export interface RunMetadata {
  /** Canonical tool id from the manifest (or composed id "a+b"). */
  tool: string;
  /** Adapter wrapper version. */
  adapterVersion?: string;
  /** When a composed adapter ran, the ordered list of sub-tool ids. */
  stages?: string[];
  /** Arbitrary extra metadata (timings, image digest, etc.). */
  [key: string]: unknown;
}

export interface DesignResult {
  designs: Design[];
  runMetadata: RunMetadata;
}

// ---------- Runtime shapes ----------

/** Per-stage artifact info when an adapter is a composition. */
export interface PreparedStage {
  toolId: string;
  requestPath: string;
  inputsDir: string;
  outputsDir: string;
  toolArtifacts: Record<string, unknown>;
}

export interface PreparedJob {
  /** Root working directory for this job (host path, mounted into the container). */
  workdir: string;
  /** Host path that will be mounted read-only as `/inputs`. */
  inputsDir: string;
  /** Host path that will be mounted writable as `/outputs`. */
  outputsDir: string;
  /** Where the normalized request.json was staged. */
  requestPath: string;
  /** Where the target PDB was staged. */
  targetPath: string;
  /** Arbitrary tool-specific artifacts (paths, cfg files, etc.). */
  toolArtifacts: Record<string, unknown>;
  /** Present only on composed adapters. */
  stages?: PreparedStage[];
}

export interface RawOutput {
  outputDir: string;
  exitCode: number;
  stdout: string;
  stderr: string;
  /** Free-form tool-specific fields that `parse()` consumes. */
  [key: string]: unknown;
}

// ---------- Validation ----------

export interface ValidationError {
  field: string;
  message: string;
}

// ---------- Manifest (re-exported concrete types live in manifest.ts) ----------

export type ToolTier = 'open' | 'open-weights' | 'frontier';

export type ToolCategory =
  | 'backbone'
  | 'backbone_generation'
  | 'sequence'
  | 'sequence_design'
  | 'binder_design'
  | 'structure'
  | 'structure_prediction'
  | 'embed'
  | 'embedding_scoring'
  | 'generative'
  | 'composite'
  | 'other';

export interface ToolComputeProfile {
  gpu: string;
  gpuCount: number;
  cpuCores: number;
  memoryGb: number;
  estSecondsPerDesign: number;
  note?: string;
}

export interface HttpsToolTransport {
  type: 'https';
  endpoint: string;
}

export interface ModalToolTransport {
  type: 'modal';
  app: string;
  function: string;
}

export type ToolTransport = HttpsToolTransport | ModalToolTransport;

export interface ToolManifest {
  id: string;
  displayName: string;
  version: string;
  adapterVersion: string;
  category: ToolCategory;
  tier: ToolTier;
  licenseGate?: boolean;
  license: string;
  image: string;
  imageDigest: string;
  compute: ToolComputeProfile;
  inputSchema?: string;
  outputSchema?: string;
  defaultParams?: Record<string, unknown>;
  composes?: string[];
  transport?: ToolTransport;
}

// ---------- SDK-local types ----------

export interface RunInContainerOptions {
  /** Container runtime: docker / podman / nerdctl. Defaults to "docker". */
  runtime?: 'docker' | 'podman' | 'nerdctl';
  /** GPU device selector (e.g. "all", "0,1"). Omit for CPU-only tools. */
  gpuDevices?: string | undefined;
  /** Hard-kill timeout in seconds (0 = no timeout). */
  timeoutSeconds?: number;
  /** Extra env vars passed through to the container. */
  env?: Record<string, string>;
}

export interface ContainerSpawnConfig {
  runtime: 'docker' | 'podman' | 'nerdctl';
  args: string[];
  env: Record<string, string>;
  cwd: string;
  timeoutSeconds: number;
  preparedJob: PreparedJob;
  image: string;
  imageDigest: string;
}
