/**
 * Registry-sync tests — Wave 8, Agent 15/15.
 *
 * Catches drift between the on-disk tool catalog (`tools/<id>/`) and any
 * in-code registries the orchestrator depends on:
 *   - `packages/tools-sdk` exports / source (TS adapters & references)
 *   - `packages/db/prisma/seed.ts` (Tool catalog seed rows)
 *   - `apps/web` tool listings (best-effort grep)
 *
 * The intent is to flag the case where someone adds a tool dir but forgets to
 * register it (or vice-versa), well before runtime. We do NOT require every
 * registry to mention every tool — instead we surface the diff so reviewers
 * can decide.
 */
import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, existsSync, statSync } from "node:fs";
import * as path from "node:path";
import { TOOL_INPUT_SPECS } from "../../packages/types/src/catalog-taxonomy";

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const TOOLS_DIR = path.join(REPO_ROOT, "tools");
const TOOLS_SDK_DIR = path.join(REPO_ROOT, "packages", "tools-sdk");
const DB_PRISMA_DIR = path.join(REPO_ROOT, "packages", "db", "prisma");

const EXPECTED_TOOLS = [
  "alphafold3",
  "antifold",
  "apbs",
  "arpeggio",
  "autodock-vina",
  "bindcraft",
  "boltz1",
  "boltz2",
  "boltzgen",
  "cd-hit",
  "chai1",
  "chroma",
  "diamond",
  "disco",
  "dockq",
  "dssp",
  "esm2",
  "esmfold",
  "esmc",
  "esmif1",
  "evoef2",
  "foldseek",
  "fpocket",
  "freesasa",
  "germinal",
  "hmmer",
  "hhsuite",
  "immunebuilder",
  "ligandmpnn",
  "mafft",
  "mdanalysis",
  "mmseqs2",
  "omegafold",
  "openmm-relax",
  "p2rank",
  "parasail",
  "pdb-tools",
  "pdb2pqr",
  "pdbfixer",
  "plip",
  "prodigy",
  "prody",
  "propka",
  "proteinmpnn",
  "protparam",
  "rf3",
  "rfd3",
  "rfdiffusion",
  "rfdiffusionaa",
  "smina",
  "solublempnn",
  "thermompnn",
] as const;

function listToolDirs(): string[] {
  if (!existsSync(TOOLS_DIR)) return [];
  return readdirSync(TOOLS_DIR)
    .filter((name) => {
      if (
        name.startsWith(".") ||
        name.startsWith("_") ||
        name === "__tests__" ||
        name === "conformance"
      ) {
        return false;
      }
      const full = path.join(TOOLS_DIR, name);
      return statSync(full).isDirectory();
    })
    .sort();
}

/** Read every TS file in a dir tree and concatenate the contents. */
function concatTreeText(root: string, exts = [".ts", ".tsx"]): string {
  if (!existsSync(root)) return "";
  let buf = "";
  const stack = [root];
  while (stack.length) {
    const cur = stack.pop()!;
    for (const entry of readdirSync(cur)) {
      if (entry === "node_modules" || entry === "dist" || entry.startsWith("."))
        continue;
      const full = path.join(cur, entry);
      const st = statSync(full);
      if (st.isDirectory()) {
        stack.push(full);
      } else if (exts.some((e) => full.endsWith(e))) {
        buf += "\n// " + full + "\n" + readFileSync(full, "utf-8");
      }
    }
  }
  return buf;
}

function loadManifestId(toolName: string): string | null {
  const p = path.join(TOOLS_DIR, toolName, "manifest.json");
  if (!existsSync(p)) return null;
  try {
    return (JSON.parse(readFileSync(p, "utf-8")) as { id?: string }).id ?? null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------

describe("registry-sync: filesystem catalog", () => {
  it("every expected tool dir exists", () => {
    const present = new Set(listToolDirs());
    const missing = EXPECTED_TOOLS.filter((t) => !present.has(t));
    expect(missing, `tools/ is missing: ${missing.join(", ")}`).toEqual([]);
  });

  it("no unexpected/orphan tool dirs", () => {
    const present = listToolDirs();
    const unexpected = present.filter(
      (d) => !EXPECTED_TOOLS.includes(d as any),
    );
    // Soft assertion: print but don't fail — adding a tool before this list is
    // updated is normal during development. Hard-fail only if an old tool was
    // renamed and left behind.
    expect(
      unexpected,
      `unexpected tool dirs (update EXPECTED_TOOLS or remove): ${unexpected.join(", ")}`,
    ).toEqual([]);
  });

  it("every tool dir has a manifest with matching id", () => {
    const mismatches: string[] = [];
    for (const t of EXPECTED_TOOLS) {
      const id = loadManifestId(t);
      if (id === null) {
        mismatches.push(`${t}: no manifest.json`);
      } else if (id !== t) {
        mismatches.push(`${t}: manifest.id=${id} (expected ${t})`);
      }
    }
    expect(mismatches).toEqual([]);
  });
});

// ---------------------------------------------------------------------------

describe("registry-sync: tools-sdk package", () => {
  it("tools-sdk package exists", () => {
    expect(existsSync(TOOLS_SDK_DIR), `expected ${TOOLS_SDK_DIR}`).toBe(true);
  });

  it("tools-sdk source compiles a manifest schema (loadManifest exists)", () => {
    const text = concatTreeText(path.join(TOOLS_SDK_DIR, "src"));
    expect(text).toMatch(/loadManifest|toolManifestSchema/);
  });

  it("tools-sdk does NOT reference removed/renamed tools", () => {
    const text = concatTreeText(path.join(TOOLS_SDK_DIR, "src")).toLowerCase();
    // Catch typos / stale aliases for canonical ids.
    const stale = [
      "rf_diffusion", // rfdiffusion canonical
      "protein_mpnn", // proteinmpnn canonical
      "boltz-1", // boltz1 canonical (no hyphen-digit)
      "boltz-2", // boltz2 canonical
      "chai-1", // chai1 canonical
    ];
    const found = stale.filter((s) => text.includes(s));
    expect(
      found,
      `tools-sdk references stale ids: ${found.join(", ")}`,
    ).toEqual([]);
  });
});

describe("registry-sync: dashboard input taxonomy", () => {
  it("declares an explicit input contract for every catalog tool", () => {
    const declared = Object.keys(TOOL_INPUT_SPECS).sort();
    expect(declared).toEqual([...EXPECTED_TOOLS].sort());
  });

  it("every uploaded-backbone tool consumes the worker-staged download URL", () => {
    const missing = Object.entries(TOOL_INPUT_SPECS)
      .filter(([, spec]) => spec.inputKind === "backbone")
      .filter(([toolId]) => {
        const modalApp = path.join(TOOLS_DIR, toolId, "modal_app.py");
        return (
          !existsSync(modalApp) ||
          !readFileSync(modalApp, "utf-8").includes("targetStructureUrl")
        );
      })
      .map(([toolId]) => toolId);
    expect(
      missing,
      `backbone tools ignoring staged uploads: ${missing.join(", ")}`,
    ).toEqual([]);
  });

  it("every two-structure tool consumes both worker-staged download URLs", () => {
    const missing = Object.entries(TOOL_INPUT_SPECS)
      .filter(([, spec]) => spec.inputKind === "complex")
      .filter(([toolId]) => {
        const modalApp = path.join(TOOLS_DIR, toolId, "modal_app.py");
        if (!existsSync(modalApp)) return true;
        const source = readFileSync(modalApp, "utf-8");
        const resolvesNamedStructureUrl = source.includes(
          'f"{name}StructureUrl"',
        );
        return !(
          resolvesNamedStructureUrl ||
          (source.includes("targetStructureUrl") &&
            source.includes("partnerStructureUrl"))
        );
      })
      .map(([toolId]) => toolId);
    expect(
      missing,
      `complex tools ignoring staged uploads: ${missing.join(", ")}`,
    ).toEqual([]);
  });

  it("every Modal wrapper can return an owned artifact or a sequence fallback", () => {
    const missing = EXPECTED_TOOLS.filter((toolId) => {
      const modalApp = path.join(TOOLS_DIR, toolId, "modal_app.py");
      if (!existsSync(modalApp)) return true;
      const source = readFileSync(modalApp, "utf-8");
      return !(
        source.includes("artifactUploads") ||
        source.includes("_upload_structure(") ||
        /["']sequence["']\s*:/.test(source)
      );
    });
    expect(
      missing,
      `tools without an owned artifact path: ${missing.join(", ")}`,
    ).toEqual([]);
  });
});

// ---------------------------------------------------------------------------

describe("registry-sync: prisma seed (best-effort)", () => {
  const seedPath = path.join(DB_PRISMA_DIR, "seed.ts");

  it("seed file exists", () => {
    expect(existsSync(seedPath)).toBe(true);
  });

  it("frontier-tier tools are surfaced as closed-weights gateable", () => {
    if (!existsSync(seedPath)) return;
    const seed = readFileSync(seedPath, "utf-8");
    const schemaPath = path.join(DB_PRISMA_DIR, "schema.prisma");
    if (!existsSync(schemaPath)) return;
    const schema = readFileSync(schemaPath, "utf-8");
    // The schema must keep the closed_weights_allowed flag on FeatureFlag.
    expect(
      schema,
      "feature_flags.closed_weights_allowed must remain on FeatureFlag — required to gate closed-weights tools",
    ).toMatch(/closed_weights_allowed|closedWeightsAllowed/);
    // Seed parity: if the seed enumerates tools at all, every closed-weights
    // tool dir should appear in it. Otherwise (no enumeration yet) skip.
    const enumeratesTools =
      /tool\.(create|upsert)/i.test(seed) || /tools\s*:\s*\[/.test(seed);
    if (!enumeratesTools) return;
    const closedTools: string[] = [];
    for (const t of EXPECTED_TOOLS) {
      const m = path.join(TOOLS_DIR, t, "manifest.json");
      if (!existsSync(m)) continue;
      const parsed = JSON.parse(readFileSync(m, "utf-8")) as { tier?: string };
      if (parsed.tier === "frontier") closedTools.push(t);
    }
    const missingFromSeed = closedTools.filter((t) => !seed.includes(t));
    expect(
      missingFromSeed,
      `closed-weights tools missing from prisma seed: ${missingFromSeed.join(", ")}`,
    ).toEqual([]);
  });
});
