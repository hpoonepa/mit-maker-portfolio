import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, it, expect } from "vitest";

import {
  formatBytes,
  hasValidExtension,
  limitForTier,
  SIZE_LIMIT_FREE_BYTES,
  SIZE_LIMIT_PRO_BYTES,
  validateStructureFile,
} from "./validate";

const HERE = dirname(fileURLToPath(import.meta.url));
const fixture = (name: string) =>
  readFileSync(join(HERE, "__fixtures__", name), "utf8");

describe("hasValidExtension", () => {
  it("accepts known structure extensions (case-insensitive)", () => {
    for (const name of ["a.pdb", "b.PDB", "c.ent", "d.cif", "e.mmcif", "F.MmCif"]) {
      expect(hasValidExtension(name)).toBe(true);
    }
  });

  it("rejects anything else", () => {
    for (const name of ["foo.txt", "bar", "baz.json", "virus.exe"]) {
      expect(hasValidExtension(name)).toBe(false);
    }
  });
});

describe("limitForTier", () => {
  it("picks the correct cap per tier", () => {
    expect(limitForTier("free")).toBe(SIZE_LIMIT_FREE_BYTES);
    expect(limitForTier("pro")).toBe(SIZE_LIMIT_PRO_BYTES);
  });
});

describe("formatBytes", () => {
  it("formats bytes, KB and MB", () => {
    expect(formatBytes(500)).toBe("500 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("validateStructureFile", () => {
  const text = fixture("small.pdb");
  const size = Buffer.byteLength(text, "utf8");

  it("accepts a good PDB under the free cap", () => {
    const result = validateStructureFile(text, size, "free", "small.pdb");
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.parsed.chains).toHaveLength(1);
      expect(result.sizeBytes).toBe(size);
    }
  });

  it("rejects empty files", () => {
    const result = validateStructureFile("", 0, "free", "empty.pdb");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe("empty");
  });

  it("rejects files past the tier cap", () => {
    const result = validateStructureFile(
      text,
      SIZE_LIMIT_FREE_BYTES + 1,
      "free",
      "small.pdb",
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe("too_large");
  });

  it("allows the same oversized file on pro tier if under pro cap", () => {
    const proSize = SIZE_LIMIT_FREE_BYTES + 1;
    const result = validateStructureFile(text, proSize, "pro", "small.pdb");
    expect(result.ok).toBe(true);
  });

  it("rejects wrong extension", () => {
    const result = validateStructureFile(text, size, "free", "weird.json");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe("bad_extension");
  });

  it("rejects content that is not a structure", () => {
    const junk = "Lorem ipsum dolor sit amet, consectetur adipiscing elit.";
    const result = validateStructureFile(
      junk,
      Buffer.byteLength(junk),
      "free",
      "junk.pdb",
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe("not_structure");
  });

  it("rejects structures with no parseable chains", () => {
    // Valid ATOM header sniff but too short to actually parse any residue.
    const partial = "ATOM  \nATOM  \n";
    const result = validateStructureFile(
      partial,
      Buffer.byteLength(partial),
      "free",
      "partial.pdb",
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.code).toBe("no_chains");
  });
});
