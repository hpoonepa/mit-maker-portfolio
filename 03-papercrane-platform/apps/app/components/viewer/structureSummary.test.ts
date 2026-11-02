import { describe, expect, it } from "vitest";
import { CIF } from "molstar/lib/mol-io/reader/cif";
import { trajectoryFromMmCIF } from "molstar/lib/mol-model-formats/structure/mmcif";
import { defaultRepresentation, summarizeModel } from "./structureSummary";
import { chainColor, BINDER_COLOR, TARGET_COLOR } from "./palette";

// Parse real mmCIF columns through Mol*, rather than mocking its hierarchy.
async function modelFixture({ broken = false, missing = false } = {}) {
  const columns = ["group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id", "label_asym_id", "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y", "Cartn_z", "occupancy", "B_iso_or_equiv", "auth_seq_id", "auth_asym_id", "pdbx_PDB_model_num"];
  const atoms: string[] = [];
  for (let r = 0; r < 3; r++) {
    const resi = r + 1 + (missing && r > 0 ? 1 : 0);
    const origin = r * 4.2 + (broken && r === 1 ? 25 : 0);
    for (const [name, offset] of [["N", 0], ["CA", 1.4], ["C", 2.9], ["O", 3.2]] as const) {
      atoms.push(`ATOM ${atoms.length + 1} ${name === "CA" ? "C" : name} ${name} . ALA Z 1 ${resi} ? ${origin + offset} 0 0 1 70 ${100 + resi} Z 1`);
    }
  }
  const text = `data_test\nloop_\n${columns.map(c => `_atom_site.${c}`).join("\n")}\n${atoms.join("\n")}\n#\n`;
  const parsed = await CIF.parse(text).run();
  if (parsed.isError) throw new Error(parsed.message);
  const trajectory = await trajectoryFromMmCIF(parsed.result.blocks[0]!).run();
  return trajectory.representative;
}

describe("structure summary from Mol* coordinates", () => {
  it("reads residue names from the atomic table and keeps author chain/residue IDs", async () => {
    const summary = summarizeModel(await modelFixture());
    expect(summary.atomCount).toBe(12);
    expect(summary.residueCount).toBe(3);
    expect(summary.chains).toEqual([{ chainId: "Z", residues: [101, 102, 103].map(resi => ({ resi, aa3: "ALA", aa: "A" })) }]);
    expect(summary.backboneBreaks).toBe(0);
    expect(defaultRepresentation(summary)).toBe("cartoon");
  });

  it("detects discontinuous coordinates and chooses atoms without changing the model", async () => {
    const model = await modelFixture({ broken: true });
    const before = Array.from(model.atomicConformation.x);
    const summary = summarizeModel(model);
    expect(summary.backboneBreaks).toBeGreaterThan(0);
    expect(defaultRepresentation(summary)).toBe("atoms");
    expect(Array.from(model.atomicConformation.x)).toEqual(before);
  });

  it("does not label genuinely missing residues as broken geometry", async () => {
    const summary = summarizeModel(await modelFixture({ missing: true }));
    expect(summary.backboneBreaks).toBe(0);
    expect(defaultRepresentation(summary)).toBe("cartoon");
  });

  it("colors explicit assignments without assuming that A is target or B is binder", () => {
    expect(chainColor(0, "Z", ["Z"], [])).toBe(TARGET_COLOR);
    expect(chainColor(0, "Z", [], ["Z"])).toBe(BINDER_COLOR);
    expect(chainColor(0, "Z", [], [])).not.toBe(chainColor(1, "A", [], []));
  });
});
