/**
 * Tiny adapter between PDB inputs and the `<MolstarViewer>` `structureUrl`
 * prop. Two paths are supported:
 *
 *   1. **Remote**: a validated PDB ID → RCSB CDN URL.
 *   2. **Local**: an uploaded `.pdb` / `.cif` file → in-browser blob URL.
 *
 * Mol* itself is fetch-driven so a blob URL is enough; we don't need to
 * pre-parse anything before mounting.
 */
import { pdbCdnUrl, validatePdbId, type PdbFormat } from "./fetch";
import type { StructureFormat } from "@/components/viewer/types";

/** Source descriptor handed to the viewer. */
export interface CifSource {
  /** Display label: usually the PDB ID or filename. */
  label: string;
  /** Public/blob URL the viewer fetches. */
  url: string;
  /** Format the viewer should pass to Mol*'s `parseTrajectory`. */
  format: StructureFormat;
  /**
   * Cleanup hook: revokes blob URLs created for local file uploads. No-op
   * for remote sources. Callers should invoke on unmount / replacement.
   */
  release: () => void;
}

/**
 * Resolve a user-typed PDB ID to a `CifSource`. mmCIF is preferred because
 * RCSB ships every entry in CIF format; `.pdb` is a legacy fallback for the
 * very few entries where CIF parsing trips Mol*.
 */
export function sourceFromPdbId(raw: string, format: PdbFormat = "cif"): CifSource {
  const id = validatePdbId(raw);
  const { url } = pdbCdnUrl(id, format);
  return {
    label: id,
    url,
    format,
    release: () => {
      /* nothing to release for remote URLs */
    },
  };
}

/** Heuristic: pick a Mol* format from a filename. */
export function inferFormatFromFilename(filename: string): StructureFormat {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".pdb") || lower.endsWith(".ent")) return "pdb";
  return "cif";
}

/**
 * Wrap a user-uploaded structure file into a `CifSource`. We use a blob URL
 * so Mol* can `download()` it like any other source, which keeps the viewer
 * code path identical for remote and local structures.
 */
export function sourceFromFile(file: File): CifSource {
  const url = URL.createObjectURL(file);
  return {
    label: file.name,
    url,
    format: inferFormatFromFilename(file.name),
    release: () => URL.revokeObjectURL(url),
  };
}
