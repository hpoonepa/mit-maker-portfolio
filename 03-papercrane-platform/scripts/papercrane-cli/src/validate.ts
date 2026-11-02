/**
 * Tool-id validation for the scaffold-tool command.
 *
 * Rules:
 *   1. Slug pattern ^[a-z][a-z0-9-]{2,30}$ (matches existing tool dirs)
 *   2. Not one of the reserved upstream tool ids (collision with existing
 *      first-party adapters under `tools/`)
 *   3. Directory `tools/<slug>/` must not already exist
 */
import { existsSync, statSync } from "node:fs";
import { join } from "node:path";

export const SLUG_PATTERN = /^[a-z][a-z0-9-]{2,30}$/;

/**
 * First-party adapter ids reserved by the Paper Crane catalog. The CLI
 * refuses to create a new tool dir that shadows these, even if the dir was
 * removed from disk (catch re-creation bugs early).
 *
 * Note: this list is intentionally exhaustive — it includes every tool listed
 * in plan 02 §6 Wave 1-6, even those whose `tools/<id>/` has not yet landed.
 */
export const RESERVED_IDS: ReadonlySet<string> = new Set([
  "bindcraft",
  "boltz1",
  "boltz2",
  "chai1",
  "rfdiffusion",
  "proteinmpnn",
  "ligandmpnn",
  "solublempnn",
  "esm2",
  "boltzgen",
  "chroma",
  "disco",
  "alphafold3",
  "rfdiffusionaa",
  "esmc",
  "esmfold",
  "germinal",
  "rf3",
  "rfd3",
  "antifold",
  "thermompnn",
  "pdbfixer",
  "esmif1",
  "evoef2",
  "omegafold",
  "immunebuilder",
  "openmm-relax",
  "foldseek",
  "p2rank",
  "freesasa",
  "autodock-vina",
  "plip",
  "mmseqs2",
  "hmmer",
  "mafft",
  "dssp",
  "fpocket",
  "mdanalysis",
  "pdb2pqr",
  "propka",
  "apbs",
  "smina",
  "protparam",
  "parasail",
  "cd-hit",
  "diamond",
  "hhsuite",
  "prody",
  "pdb-tools",
  "prodigy",
  "arpeggio",
  "dockq",
]);

export interface ValidateOptions {
  /** Absolute path to the Paper Crane repo root (the dir that contains `tools/`). */
  repoRoot: string;
}

export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

/**
 * Validate a tool id. Throws `ValidationError` on the first failure; returns
 * the normalized slug on success.
 */
export function validateToolName(
  rawName: string,
  opts: ValidateOptions,
): string {
  if (typeof rawName !== "string" || rawName.length === 0) {
    throw new ValidationError("tool name is required");
  }
  const name = rawName.trim();
  if (!SLUG_PATTERN.test(name)) {
    throw new ValidationError(
      `invalid tool id "${name}" — must match ${SLUG_PATTERN.source} ` +
        "(lowercase, digits, hyphens; 3–31 chars; starts with a letter)",
    );
  }
  if (RESERVED_IDS.has(name)) {
    throw new ValidationError(
      `tool id "${name}" is reserved by the Paper Crane catalog`,
    );
  }
  const target = join(opts.repoRoot, "tools", name);
  if (existsSync(target)) {
    let kind = "path";
    try {
      kind = statSync(target).isDirectory() ? "directory" : "file";
    } catch {
      // best-effort — fall through with default label
    }
    throw new ValidationError(
      `tool ${kind} already exists at ${target} — choose a different id or remove the existing dir first`,
    );
  }
  return name;
}
