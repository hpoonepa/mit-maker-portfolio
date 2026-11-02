import { strToU8, zipSync } from "fflate";
import { normaliseDesignProvenance } from "@papercrane/types";

export const ARCHIVE_FORMATS = ["fasta", "cif", "json", "csv"] as const;
export type ArchiveFormat = (typeof ARCHIVE_FORMATS)[number];
export interface ArchiveDesign { id: string; seed: number; provenance?: string | null }
export interface ArchivePage { items: ArchiveDesign[]; nextCursor: string | null }

/** Refuse an incomplete enumeration rather than exporting an arbitrary UI page. */
export async function collectArchiveDesigns(
  fetchPage: (cursor?: string) => Promise<ArchivePage>,
): Promise<ArchiveDesign[]> {
  const designs = new Map<string, ArchiveDesign>();
  const cursors = new Set<string>();
  let cursor: string | undefined;
  do {
    const page = await fetchPage(cursor);
    for (const design of page.items) designs.set(design.id, design);
    if (!page.nextCursor) return [...designs.values()];
    if (cursors.has(page.nextCursor)) throw new Error("Export pagination stopped advancing. Please retry.");
    cursors.add(page.nextCursor);
    cursor = page.nextCursor;
  } while (cursor);
  return [...designs.values()];
}

type ArchiveEntry = {
  designId: string;
  seed: number;
  provenance: string;
  format: ArchiveFormat;
  path: string;
} & ({ status: "exported"; bytes: number; sha256: string } | { status: "failed"; error: string });

export async function buildResearchArchive(options: {
  designs: ArchiveDesign[];
  formats: ArchiveFormat[];
  scope: "job" | "project";
  scopeId: string;
  snapshotAt: string;
  onProgress?: (attempted: number, total: number) => void;
  request?: typeof fetch;
}) {
  const formats = [...new Set(options.formats)];
  if (!formats.length) throw new Error("Select at least one export format.");
  const request = options.request ?? fetch;
  const files: Record<string, Uint8Array> = {};
  const entries: ArchiveEntry[] = [];
  let totalBytes = 0;
  for (const design of options.designs) {
    if (!/^[a-zA-Z0-9-]+$/.test(design.id)) throw new Error("Invalid design identifier in export.");
    for (const format of formats) {
      const path = `designs/${design.id}.${format}`;
      const base = { designId: design.id, seed: design.seed, provenance: normaliseDesignProvenance(design.provenance), format, path };
      let bytes: Uint8Array<ArrayBuffer>;
      try {
        const response = await request(`/api/designs/${design.id}/export/${format}`, { signal: AbortSignal.timeout(30_000) });
        if (!response.ok) throw new Error(`Download returned HTTP ${response.status}`);
        bytes = new Uint8Array(await response.arrayBuffer());
        if (!bytes.length) throw new Error("Downloaded file is empty");
      } catch (error) {
        entries.push({ ...base, status: "failed", error: error instanceof Error ? error.message : "Download failed" });
        options.onProgress?.(entries.length, options.designs.length * formats.length);
        continue;
      }
      totalBytes += bytes.length;
      if (totalBytes > 128 * 1024 * 1024) {
        throw new Error("This archive exceeds the 128 MB browser export limit. Export individual jobs instead.");
      }
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const sha256 = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
      files[path] = bytes;
      entries.push({ ...base, status: "exported", bytes: bytes.length, sha256 });
      options.onProgress?.(entries.length, options.designs.length * formats.length);
    }
  }
  const failed = entries.filter((entry) => entry.status === "failed").length;
  const completeDesigns = options.designs.filter((design) =>
    entries.filter((entry) => entry.designId === design.id && entry.status === "exported").length === formats.length,
  ).length;
  const manifest = {
    schemaVersion: "papercrane-archive-v1",
    scope: options.scope,
    scopeId: options.scopeId,
    snapshotAt: options.snapshotAt,
    generatedAt: new Date().toISOString(),
    complete: failed === 0,
    requestedDesigns: options.designs.length,
    completeDesigns,
    requestedFiles: entries.length,
    exportedFiles: entries.length - failed,
    failedFiles: failed,
    notes: [
      "Records created after snapshotAt are excluded. Existing records may change while files are fetched.",
      "Origin records execution provenance. Scientific validation is separate; unknown origins remain unverified.",
      "Archive completeness tracks requested files. Model accuracy and computational reproducibility require separate verification.",
    ],
    files: entries,
  };
  files["manifest.json"] = strToU8(JSON.stringify(manifest, null, 2));
  return { bytes: zipSync(files, { level: 0 }), manifest };
}
