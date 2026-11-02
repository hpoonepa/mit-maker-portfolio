import { describe, it, expect } from "vitest";
import {
  CATALOG_CATEGORY_KEYS,
  CATALOG_CATEGORIES,
  COMBO_CARDS,
  toCatalogCategory,
  catalogCategoryLabel,
  combosForCategory,
  toolInputSpec,
  jobInputKind,
  jobLigandRequirement,
  TOOL_INPUT_SPECS,
  type CatalogCategoryKey,
} from "../src/catalog-taxonomy";

describe("catalog taxonomy — categories", () => {
  it("defines exactly the four functional buckets", () => {
    expect(CATALOG_CATEGORY_KEYS).toEqual([
      "binder-design",
      "sequence-design",
      "structure-prediction",
      "scoring",
    ]);
  });

  it("has one metadata entry per key, in ascending order, with labels", () => {
    expect(CATALOG_CATEGORIES).toHaveLength(CATALOG_CATEGORY_KEYS.length);
    const keys = CATALOG_CATEGORIES.map((c) => c.key);
    expect(new Set(keys).size).toBe(keys.length);
    const orders = CATALOG_CATEGORIES.map((c) => c.order);
    expect(orders).toEqual([...orders].sort((a, b) => a - b));
    for (const c of CATALOG_CATEGORIES) {
      expect(c.label.length).toBeGreaterThan(0);
      expect(c.tagline.length).toBeGreaterThan(0);
    }
  });
});

describe("catalog taxonomy — toCatalogCategory", () => {
  const cases: Array<[string, CatalogCategoryKey]> = [
    // binder-design: backbone generators + composites + utility, all vocabs
    ["backbone", "binder-design"],
    ["backbone-generation", "binder-design"],
    ["backbone_generation", "binder-design"],
    ["composite", "binder-design"],
    ["binder-design", "binder-design"],
    ["binder_design", "binder-design"],
    ["utility", "binder-design"],
    // sequence-design: MPNN family
    ["sequence", "sequence-design"],
    ["sequence-design", "sequence-design"],
    ["sequence_design", "sequence-design"],
    // structure-prediction
    ["structure", "structure-prediction"],
    ["structure-prediction", "structure-prediction"],
    ["structure_prediction", "structure-prediction"],
    // scoring
    ["ranking", "scoring"],
    ["validation", "scoring"],
    ["embedding_scoring", "scoring"],
    ["embedding-scoring", "scoring"],
    ["scoring", "scoring"],
  ];

  it.each(cases)("maps %s → %s", (raw, expected) => {
    expect(toCatalogCategory(raw)).toBe(expected);
  });

  it("is case-insensitive", () => {
    expect(toCatalogCategory("BACKBONE")).toBe("binder-design");
    expect(toCatalogCategory("Structure")).toBe("structure-prediction");
  });

  it("defaults unknown categories to binder-design (never drops)", () => {
    expect(toCatalogCategory("nonsense")).toBe("binder-design");
    expect(toCatalogCategory("")).toBe("binder-design");
  });

  it("catalogCategoryLabel resolves to the section label", () => {
    expect(catalogCategoryLabel("backbone")).toBe("Binder design");
    expect(catalogCategoryLabel("sequence")).toBe("Sequence design");
    expect(catalogCategoryLabel("structure")).toBe("Structure prediction");
    expect(catalogCategoryLabel("ranking")).toBe("Embeddings & scoring");
  });
});

describe("catalog taxonomy — combo cards", () => {
  it("ships the two curated binder-design combos as coming_soon", () => {
    expect(COMBO_CARDS).toHaveLength(2);
    for (const combo of COMBO_CARDS) {
      expect(combo.category).toBe("binder-design");
      expect(combo.status).toBe("coming_soon");
      expect(combo.stages.length).toBeGreaterThanOrEqual(2);
      // id follows the compose() `a+b` convention over the stage slugs
      expect(combo.id).toBe(combo.stages.join("+"));
    }
  });

  it("references real tool slugs in stages", () => {
    const known = new Set([
      "rfdiffusion",
      "rfdiffusionaa",
      "proteinmpnn",
      "ligandmpnn",
    ]);
    for (const combo of COMBO_CARDS) {
      for (const stage of combo.stages) expect(known.has(stage)).toBe(true);
    }
  });

  it("combosForCategory returns combos only for their bucket", () => {
    expect(combosForCategory("binder-design")).toHaveLength(2);
    expect(combosForCategory("sequence-design")).toHaveLength(0);
    expect(combosForCategory("structure-prediction")).toHaveLength(0);
    expect(combosForCategory("scoring")).toHaveLength(0);
  });
});

describe("catalog taxonomy — tool input specs", () => {
  it("maps each tool to the input kind its schema requires", () => {
    expect(toolInputSpec("rfdiffusion").inputKind).toBe("target");
    expect(toolInputSpec("bindcraft").inputKind).toBe("target");
    expect(toolInputSpec("boltzgen").inputKind).toBe("target");
    expect(toolInputSpec("rfd3").inputKind).toBe("target");
    expect(toolInputSpec("disco").inputKind).toBe("sequences");
    expect(toolInputSpec("proteinmpnn").inputKind).toBe("backbone");
    expect(toolInputSpec("ligandmpnn").inputKind).toBe("backbone");
    expect(toolInputSpec("antifold").inputKind).toBe("backbone");
    expect(toolInputSpec("thermompnn").inputKind).toBe("backbone");
    expect(toolInputSpec("pdbfixer").inputKind).toBe("backbone");
    expect(toolInputSpec("esmif1").inputKind).toBe("backbone");
    expect(toolInputSpec("evoef2").inputKind).toBe("backbone");
    expect(toolInputSpec("openmm-relax").inputKind).toBe("backbone");
    expect(toolInputSpec("p2rank").inputKind).toBe("backbone");
    expect(toolInputSpec("freesasa").inputKind).toBe("backbone");
    expect(toolInputSpec("autodock-vina").inputKind).toBe("backbone");
    expect(toolInputSpec("plip").inputKind).toBe("backbone");
    expect(toolInputSpec("dssp").inputKind).toBe("backbone");
    expect(toolInputSpec("fpocket").inputKind).toBe("backbone");
    expect(toolInputSpec("mdanalysis").inputKind).toBe("backbone");
    expect(toolInputSpec("pdb2pqr").inputKind).toBe("backbone");
    expect(toolInputSpec("propka").inputKind).toBe("backbone");
    expect(toolInputSpec("apbs").inputKind).toBe("backbone");
    expect(toolInputSpec("smina").inputKind).toBe("backbone");
    expect(toolInputSpec("prody").inputKind).toBe("backbone");
    expect(toolInputSpec("pdb-tools").inputKind).toBe("backbone");
    expect(toolInputSpec("prodigy").inputKind).toBe("backbone");
    expect(toolInputSpec("arpeggio").inputKind).toBe("backbone");
    expect(toolInputSpec("boltz2").inputKind).toBe("complex");
    expect(toolInputSpec("chai1").inputKind).toBe("complex");
    expect(toolInputSpec("alphafold3").inputKind).toBe("complex");
    expect(toolInputSpec("foldseek").inputKind).toBe("complex");
    expect(toolInputSpec("dockq").inputKind).toBe("complex");
    expect(toolInputSpec("rf3").inputKind).toBe("sequences");
    expect(toolInputSpec("esmfold").inputKind).toBe("sequences");
    expect(toolInputSpec("omegafold").inputKind).toBe("sequences");
    expect(toolInputSpec("immunebuilder").inputKind).toBe("sequences");
    // boltz1 is structure-prediction category but takes raw sequences
    expect(toolInputSpec("boltz1").inputKind).toBe("sequences");
    expect(toolInputSpec("esm2").inputKind).toBe("sequences");
    expect(toolInputSpec("esmc").inputKind).toBe("sequences");
    expect(toolInputSpec("mmseqs2").inputKind).toBe("sequences");
    expect(toolInputSpec("hmmer").inputKind).toBe("sequences");
    expect(toolInputSpec("mafft").inputKind).toBe("sequences");
    expect(toolInputSpec("protparam").inputKind).toBe("sequences");
    expect(toolInputSpec("parasail").inputKind).toBe("sequences");
    expect(toolInputSpec("cd-hit").inputKind).toBe("sequences");
    expect(toolInputSpec("diamond").inputKind).toBe("sequences");
    expect(toolInputSpec("hhsuite").inputKind).toBe("sequences");
  });

  it("records ligand support per tool", () => {
    expect(toolInputSpec("ligandmpnn").ligand).toBe("required");
    expect(toolInputSpec("boltzgen").ligand).toBe("optional");
    expect(toolInputSpec("rfdiffusionaa").ligand).toBe("optional");
    expect(toolInputSpec("rfd3").ligand).toBe("optional");
    expect(toolInputSpec("disco").ligand).toBe("optional");
    expect(toolInputSpec("rf3").ligand).toBe("optional");
    expect(toolInputSpec("autodock-vina").ligand).toBe("required");
    expect(toolInputSpec("plip").ligand).toBe("optional");
    expect(toolInputSpec("foldseek").ligand).toBe("none");
    expect(toolInputSpec("p2rank").ligand).toBe("none");
    expect(toolInputSpec("freesasa").ligand).toBe("none");
    expect(toolInputSpec("smina").ligand).toBe("required");
    expect(toolInputSpec("dssp").ligand).toBe("none");
    expect(toolInputSpec("fpocket").ligand).toBe("none");
    expect(toolInputSpec("mdanalysis").ligand).toBe("none");
    expect(toolInputSpec("pdb2pqr").ligand).toBe("none");
    expect(toolInputSpec("propka").ligand).toBe("none");
    expect(toolInputSpec("apbs").ligand).toBe("none");
    expect(toolInputSpec("prody").ligand).toBe("none");
    expect(toolInputSpec("pdb-tools").ligand).toBe("none");
    expect(toolInputSpec("prodigy").ligand).toBe("none");
    expect(toolInputSpec("arpeggio").ligand).toBe("none");
    expect(toolInputSpec("dockq").ligand).toBe("none");
    expect(toolInputSpec("proteinmpnn").ligand).toBe("none");
    expect(toolInputSpec("boltz2").ligand).toBe("none");
  });

  it("only target-kind tools use hotspots", () => {
    for (const [slug, spec] of Object.entries(TOOL_INPUT_SPECS)) {
      if (spec.needsHotspots) {
        expect(spec.inputKind, `${slug} needsHotspots`).toBe("target");
      }
    }
  });

  it("defaults unknown tools to target / no-ligand", () => {
    expect(toolInputSpec("made-up-tool")).toEqual({
      inputKind: "target",
      needsHotspots: false,
      ligand: "none",
    });
  });

  it("jobInputKind reflects the (single) shared kind of the selection", () => {
    expect(jobInputKind([])).toBeNull();
    expect(jobInputKind(["proteinmpnn"])).toBe("backbone");
    expect(jobInputKind(["boltz2", "chai1"])).toBe("complex");
    expect(jobInputKind(["esm2", "esmc"])).toBe("sequences");
  });

  it("jobLigandRequirement takes the strongest requirement across tools", () => {
    expect(jobLigandRequirement([])).toBe("none");
    expect(jobLigandRequirement(["proteinmpnn"])).toBe("none");
    expect(jobLigandRequirement(["proteinmpnn", "ligandmpnn"])).toBe(
      "required",
    );
    expect(jobLigandRequirement(["rfdiffusion", "boltzgen"])).toBe("optional");
  });
});
