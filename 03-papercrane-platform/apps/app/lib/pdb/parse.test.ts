import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, it, expect } from "vitest";

import {
  findInvalidResidues,
  largestChain,
  looksLikeCif,
  looksLikePdb,
  parseCif,
  parsePdb,
  parseStructure,
} from "./parse";

const HERE = dirname(fileURLToPath(import.meta.url));
const fixture = (name: string) =>
  readFileSync(join(HERE, "__fixtures__", name), "utf8");

describe("looksLikePdb / looksLikeCif", () => {
  it("recognises a PDB fixture", () => {
    const text = fixture("small.pdb");
    expect(looksLikePdb(text)).toBe(true);
    expect(looksLikeCif(text)).toBe(false);
  });

  it("recognises an mmCIF payload", () => {
    const cif = [
      "data_XYZ",
      "_entry.id 1ABC",
      "loop_",
      "_atom_site.group_PDB",
      "_atom_site.label_comp_id",
      "_atom_site.auth_asym_id",
      "_atom_site.auth_seq_id",
      "ATOM MET A 1",
    ].join("\n");
    expect(looksLikeCif(cif)).toBe(true);
    expect(looksLikePdb(cif)).toBe(false);
  });

  it("rejects junk", () => {
    expect(looksLikePdb("not a structure")).toBe(false);
    expect(looksLikeCif("not a structure")).toBe(false);
  });
});

describe("parsePdb (small.pdb fixture)", () => {
  const text = fixture("small.pdb");
  const parsed = parsePdb(text);

  it("detects PDB format", () => {
    expect(parsed.format).toBe("pdb");
  });

  it("carries title through", () => {
    expect(parsed.title).toBe("TINY FIXTURE FOR PARSER TESTS");
  });

  it("extracts exactly one chain (A)", () => {
    expect(parsed.chains).toHaveLength(1);
    expect(parsed.chains[0]?.id).toBe("A");
  });

  it("collapses multi-atom residues to one entry", () => {
    const chain = parsed.chains[0]!;
    // Fixture: 5 residues × 4 atoms each = 20 ATOM lines.
    expect(chain.residues).toHaveLength(5);
  });

  it("maps three-letter codes to the correct single-letter sequence", () => {
    expect(parsed.chains[0]?.sequence).toBe("MAGVK");
  });

  it("preserves author residue numbers in order", () => {
    const ids = parsed.chains[0]?.residues.map((r) => r.authSeqId);
    expect(ids).toEqual([1, 2, 3, 4, 5]);
  });
});

describe("parsePdb (synthetic edge cases)", () => {
  it("skips HETATM records", () => {
    const text = [
      "ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  9.67           N",
      "HETATM    2  O   HOH A 100      10.000  10.000  10.000  1.00 20.00           O",
      "ATOM      3  CA  MET A   1      26.266  25.413   2.842  1.00 10.38           C",
    ].join("\n");
    const parsed = parsePdb(text);
    expect(parsed.chains).toHaveLength(1);
    expect(parsed.chains[0]?.residues).toHaveLength(1);
  });

  it("separates chains A and B", () => {
    const text = [
      "ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  9.67           N",
      "ATOM      2  N   GLY A   2      27.340  24.430   2.614  1.00  9.67           N",
      "ATOM      3  N   ALA B   1      27.340  24.430   2.614  1.00  9.67           N",
    ].join("\n");
    const parsed = parsePdb(text);
    expect(parsed.chains.map((c) => c.id)).toEqual(["A", "B"]);
    expect(parsed.chains[0]?.sequence).toBe("MG");
    expect(parsed.chains[1]?.sequence).toBe("A");
  });

  it("treats unknown three-letter codes as 'X'", () => {
    const text =
      "ATOM      1  N   XYZ A   1      27.340  24.430   2.614  1.00  9.67           N";
    const parsed = parsePdb(text);
    expect(parsed.chains[0]?.residues[0]?.oneLetter).toBe("X");
  });

  it("drops non-primary altLocs", () => {
    // altLoc lives at column 17 (0-indexed: 16). Keep primary ' '/'A',
    // drop anything else (e.g. 'B'). All three rows reference residue 1
    // on chain A, so after the altLoc filter we should see exactly one.
    const text = [
      "ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  9.67           N",
      "ATOM      2  N  AMET A   1      27.340  24.430   2.614  1.00  9.67           N",
      "ATOM      3  N  BMET A   1      27.340  24.430   2.614  1.00  9.67           N",
    ].join("\n");
    const parsed = parsePdb(text);
    expect(parsed.chains[0]?.residues).toHaveLength(1);
  });

  it("skips malformed lines without throwing", () => {
    const text = [
      "ATOM this line is too short",
      "ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  9.67           N",
    ].join("\n");
    expect(() => parsePdb(text)).not.toThrow();
  });
});

describe("parseCif", () => {
  const cif = [
    "data_TEST",
    "_entry.id 1ABC",
    "loop_",
    "_atom_site.group_PDB",
    "_atom_site.label_comp_id",
    "_atom_site.auth_asym_id",
    "_atom_site.auth_seq_id",
    "_atom_site.label_alt_id",
    "ATOM MET A 1 .",
    "ATOM MET A 1 .", // duplicate atom row, same residue
    "ATOM GLY A 2 .",
    "HETATM HOH A 99 .", // should be ignored
    "ATOM ALA B 1 .",
  ].join("\n");

  const parsed = parseCif(cif);

  it("picks up the PDB id", () => {
    expect(parsed.pdbId).toBe("1ABC");
  });

  it("extracts chains and sequences", () => {
    expect(parsed.chains.map((c) => c.id)).toEqual(["A", "B"]);
    expect(parsed.chains[0]?.sequence).toBe("MG");
    expect(parsed.chains[1]?.sequence).toBe("A");
  });

  it("ignores HETATM rows", () => {
    const chainA = parsed.chains.find((c) => c.id === "A");
    expect(chainA?.residues).toHaveLength(2);
  });
});

describe("parseStructure (auto-detect)", () => {
  it("delegates to parsePdb for PDB", () => {
    expect(parseStructure(fixture("small.pdb")).format).toBe("pdb");
  });

  it("delegates to parseCif for mmCIF", () => {
    const cif = [
      "data_X",
      "loop_",
      "_atom_site.group_PDB",
      "_atom_site.label_comp_id",
      "_atom_site.auth_asym_id",
      "_atom_site.auth_seq_id",
      "ATOM ALA A 1",
    ].join("\n");
    expect(parseStructure(cif).format).toBe("cif");
  });

  it("throws on unknown input", () => {
    expect(() => parseStructure("hello world")).toThrow();
  });
});

describe("largestChain + findInvalidResidues", () => {
  const parsed = parsePdb(fixture("small.pdb"));

  it("returns the only chain when there is just one", () => {
    expect(largestChain(parsed)?.id).toBe("A");
  });

  it("flags residue numbers not present in the chain", () => {
    const chain = parsed.chains[0]!;
    expect(findInvalidResidues(chain, [1, 2, 3])).toEqual([]);
    expect(findInvalidResidues(chain, [1, 999])).toEqual([999]);
  });
});
