/**
 * Amino-acid 3-letter to 1-letter mapping for the SequencePanel.
 *
 * Kept separate from `lib/pdb/aa.ts` because that module is consumed by the
 * lightweight PDB text parser (which only knows canonical residues). The Mol*
 * structure stream emits PTMs (MSE, SEC, histidine tautomers, etc.) that we
 * still want to render as their parent letter, so we keep a wider table here.
 */

export const AA_3_TO_1: Record<string, string> = {
  ALA: "A", ARG: "R", ASN: "N", ASP: "D", CYS: "C", GLU: "E",
  GLN: "Q", GLY: "G", HIS: "H", ILE: "I", LEU: "L", LYS: "K",
  MET: "M", PHE: "F", PRO: "P", SER: "S", THR: "T", TRP: "W",
  TYR: "Y", VAL: "V",
  // Common nonstandard / modified residues that appear in deposited PDBs.
  SEC: "U", PYL: "O", MSE: "M",
  // Histidine tautomers (CHARMM/AMBER force-field aliases).
  HSE: "H", HSD: "H", HSP: "H",
};

export const aa3to1 = (aa3: string): string =>
  AA_3_TO_1[aa3?.toUpperCase()] ?? "X";
