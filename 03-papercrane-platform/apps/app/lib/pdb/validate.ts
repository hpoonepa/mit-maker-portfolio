/**
 * File-level validation for target uploads.
 *
 * Runs BEFORE we hand the bytes to the parser or request a presigned URL.
 * We intentionally check byte size + content sniff separately so the UI can
 * show the right failure reason quickly without a full parse.
 */
import {
  looksLikeCif,
  looksLikePdb,
  parseStructure,
  type ParsedStructure,
} from "./parse";

/** Tier-aware byte limits. Free tier mirrors the PDB's practical upper bound. */
export const SIZE_LIMIT_FREE_BYTES = 50 * 1024 * 1024; // 50 MB
export const SIZE_LIMIT_PRO_BYTES = 500 * 1024 * 1024; // 500 MB

export type UploadTier = "free" | "pro";

export type ValidationError = {
  code:
    | "empty"
    | "too_large"
    | "bad_extension"
    | "not_structure"
    | "no_chains"
    | "parse_failed";
  message: string;
};

export type ValidationOk = {
  ok: true;
  parsed: ParsedStructure;
  sizeBytes: number;
};

export type ValidationResult =
  | ValidationOk
  | { ok: false; error: ValidationError };

const VALID_EXTENSIONS = [".pdb", ".ent", ".cif", ".mmcif"];

export function limitForTier(tier: UploadTier): number {
  return tier === "pro" ? SIZE_LIMIT_PRO_BYTES : SIZE_LIMIT_FREE_BYTES;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function hasValidExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return VALID_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/**
 * Validates the raw text payload of a structure file. Used by the dropzone
 * after reading the file with `FileReader.readAsText`. We keep this pure so
 * it's trivial to unit-test.
 *
 * `filename` is optional: when present we enforce extension; when absent
 * (e.g. paste-drop) we rely on content sniffing only.
 */
export function validateStructureFile(
  text: string,
  sizeBytes: number,
  tier: UploadTier,
  filename?: string,
): ValidationResult {
  if (sizeBytes === 0 || text.trim().length === 0) {
    return {
      ok: false,
      error: { code: "empty", message: "File is empty" },
    };
  }

  const limit = limitForTier(tier);
  if (sizeBytes > limit) {
    return {
      ok: false,
      error: {
        code: "too_large",
        message: `File is ${formatBytes(sizeBytes)}: max ${formatBytes(limit)} on ${tier} tier`,
      },
    };
  }

  if (filename && !hasValidExtension(filename)) {
    return {
      ok: false,
      error: {
        code: "bad_extension",
        message: "Expected a .pdb, .ent, .cif, or .mmcif file",
      },
    };
  }

  if (!looksLikePdb(text) && !looksLikeCif(text)) {
    return {
      ok: false,
      error: {
        code: "not_structure",
        message: "No ATOM records found: is this a valid PDB or mmCIF?",
      },
    };
  }

  let parsed: ParsedStructure;
  try {
    parsed = parseStructure(text);
  } catch (err) {
    return {
      ok: false,
      error: {
        code: "parse_failed",
        message: err instanceof Error ? err.message : "Failed to parse structure",
      },
    };
  }

  if (parsed.chains.length === 0) {
    return {
      ok: false,
      error: {
        code: "no_chains",
        message: "Parsed structure has no chains with standard amino acids",
      },
    };
  }

  return { ok: true, parsed, sizeBytes };
}
