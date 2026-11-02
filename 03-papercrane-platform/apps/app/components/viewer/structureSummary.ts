import type { Model } from "molstar/lib/mol-model/structure";
import { aa3to1 } from "@/lib/viewer/aminoAcids";
import type { RepresentationStyle, SequencePanelChain } from "./types";

export interface StructureSummary {
  chains: SequencePanelChain[];
  atomCount: number;
  residueCount: number;
  /** Mol* backbone gaps between consecutive, present polymer residues. */
  backboneBreaks: number;
}

export function summarizeModel(model: Model): StructureSummary {
  const h = model.atomicHierarchy;
  const byChain = new Map<string, SequencePanelChain>();
  const offsets = h.residueAtomSegments.offsets;
  for (let r = 0; r < h.residues._rowCount; r++) {
    const firstAtom = offsets[r]!;
    const chainIndex = h.chainAtomSegments.index[firstAtom]!;
    const chainId = h.chains.auth_asym_id.value(chainIndex);
    // Mol* stores residue names on atoms, not on the residues table.
    const aa3 = h.atoms.label_comp_id.value(firstAtom).toUpperCase();
    const residue = {
      resi: h.residues.auth_seq_id.value(r),
      aa3,
      aa: aa3to1(aa3),
    };
    const chain = byChain.get(chainId);
    if (chain) chain.residues.push(residue);
    else byChain.set(chainId, { chainId, residues: [residue] });
  }

  let backboneBreaks = 0;
  const gaps = model.atomicRanges.gapRanges;
  for (let i = 0; i < gaps.length; i += 2) {
    const a = gaps[i]!;
    const b = gaps[i + 1]!;
    const r1 = h.residueAtomSegments.index[a]!;
    const r2 = h.residueAtomSegments.index[b]!;
    // Missing residues in experimental structures are not malformed bonds.
    if (
      h.chainAtomSegments.index[a] === h.chainAtomSegments.index[b] &&
      h.residues.label_seq_id.value(r2) ===
        h.residues.label_seq_id.value(r1) + 1
    ) {
      backboneBreaks++;
    }
  }
  return {
    chains: [...byChain.values()],
    atomCount: h.atoms._rowCount,
    residueCount: h.residues._rowCount,
    backboneBreaks,
  };
}

export function defaultRepresentation(
  summary: StructureSummary | null,
): RepresentationStyle {
  return summary && summary.backboneBreaks > 0 ? "atoms" : "cartoon";
}
