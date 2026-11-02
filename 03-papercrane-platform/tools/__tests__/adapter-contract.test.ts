/**
 * Adapter contract tests — Wave 8, Agent 15/15.
 *
 * For every tool in `tools/<name>/`, assert the adapter directory has the
 * required surface: a manifest, a Python adapter entrypoint, JSON Schema
 * input/output files, and a README. Closed-weights tools must also be
 * surfaced behind the `frontier` tier so the orchestrator's feature-flag
 * gate (`closed_weights_allowed`) can enforce access.
 *
 * Notes:
 *   - The repo currently uses `manifest.json` + `adapter.py` (run inside a
 *     Docker container). The Wave 8 spec also references future
 *     `papercrane.toml` + `modal_app.py` Modal entrypoints; the tests below
 *     accept EITHER layout so this suite stays green during the migration.
 *   - We never invoke the tools themselves — pure static checks.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, existsSync, statSync } from "node:fs";
import * as path from "node:path";
import Ajv from "ajv";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";

const TOOLS_DIR = path.resolve(__dirname, "..");

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

type ToolName = (typeof EXPECTED_TOOLS)[number];

interface ManifestShape {
  id?: string;
  version?: string;
  tier?: string;
  license?: string;
  compute?: { gpu?: string; memoryGb?: number };
  inputSchema?: string;
  outputSchema?: string;
  defaultParams?: Record<string, unknown>;
  // Spec parity (optional — only populated in newer manifests):
  closed_weights?: boolean;
}

function readJsonIfExists(p: string): any | null {
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, "utf-8"));
}

function existsAsFile(p: string): boolean {
  return existsSync(p) && statSync(p).isFile();
}

/**
 * Find the manifest file. Prefer `manifest.json` (current layout); fall back
 * to `papercrane.toml` if/when the Modal-native layout lands. We do not
 * parse TOML here — its presence is enough to claim spec parity.
 */
function locateManifest(toolDir: string): {
  jsonPath: string | null;
  tomlPath: string | null;
} {
  const jsonPath = path.join(toolDir, "manifest.json");
  const tomlPath = path.join(toolDir, "papercrane.toml");
  return {
    jsonPath: existsAsFile(jsonPath) ? jsonPath : null,
    tomlPath: existsAsFile(tomlPath) ? tomlPath : null,
  };
}

/**
 * Find the adapter module. Either `adapter.py` (current) or `modal_app.py`
 * (Wave 8 spec).
 */
function locateAdapter(toolDir: string): {
  adapterPy: string | null;
  modalAppPy: string | null;
} {
  const adapterPy = path.join(toolDir, "adapter.py");
  const modalAppPy = path.join(toolDir, "modal_app.py");
  return {
    adapterPy: existsAsFile(adapterPy) ? adapterPy : null,
    modalAppPy: existsAsFile(modalAppPy) ? modalAppPy : null,
  };
}

function buildAjv(edition: "draft7" | "2020") {
  const Options = edition === "2020" ? Ajv2020 : Ajv;
  const ajv = new Options({
    strict: false,
    allErrors: true,
    allowUnionTypes: true,
  });
  addFormats(ajv);
  return ajv;
}

const ajvDraft7 = buildAjv("draft7");
const ajv2020 = buildAjv("2020");

function compileSchema(schema: Record<string, unknown>) {
  const dialect = typeof schema.$schema === "string" ? schema.$schema : "";
  return dialect.includes("2020-12")
    ? ajv2020.compile(schema)
    : ajvDraft7.compile(schema);
}

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function parameterSchema(schema: Record<string, unknown>) {
  const properties = isJsonObject(schema.properties)
    ? schema.properties
    : undefined;
  const params =
    properties && isJsonObject(properties.params)
      ? properties.params
      : undefined;
  if (!params || params.type !== "object") {
    const direct = { ...schema };
    delete direct.$id;
    return direct;
  }
  return {
    ...params,
    ...(typeof schema.$schema === "string" ? { $schema: schema.$schema } : {}),
    ...(isJsonObject(schema.definitions)
      ? { definitions: schema.definitions }
      : {}),
    ...(isJsonObject(schema.$defs) ? { $defs: schema.$defs } : {}),
  };
}

// ---------------------------------------------------------------------------
// Per-tool sweep
// ---------------------------------------------------------------------------

describe("tool adapter contract", () => {
  it("tools/ directory exists", () => {
    expect(existsSync(TOOLS_DIR), `expected tools dir at ${TOOLS_DIR}`).toBe(
      true,
    );
  });

  describe.each(EXPECTED_TOOLS)("tool: %s", (toolId: ToolName) => {
    const toolDir = path.join(TOOLS_DIR, toolId);

    it("directory exists", () => {
      expect(existsSync(toolDir), `expected ${toolDir}`).toBe(true);
    });

    it("has a manifest (manifest.json or papercrane.toml)", () => {
      const { jsonPath, tomlPath } = locateManifest(toolDir);
      expect(
        jsonPath ?? tomlPath,
        `${toolId}: needs either manifest.json or papercrane.toml in ${toolDir}`,
      ).toBeTruthy();
    });

    it("manifest declares required [tool] fields", () => {
      const { jsonPath } = locateManifest(toolDir);
      if (!jsonPath) {
        // toml-only branch: skip detailed asserts until a TOML parser lands.
        return;
      }
      const m = readJsonIfExists(jsonPath) as ManifestShape;
      expect(m, `${toolId}: manifest must be parseable JSON`).toBeTruthy();
      expect(m.id, `${toolId}: manifest.id missing`).toBe(toolId);
      expect(m.version, `${toolId}: manifest.version missing`).toBeTruthy();
      expect(m.tier, `${toolId}: manifest.tier missing`).toBeTruthy();
      expect(m.license, `${toolId}: manifest.license missing`).toBeTruthy();
      expect(
        m.compute?.gpu,
        `${toolId}: compute.gpu (vram_gb-equivalent) missing`,
      ).toBeTruthy();
      expect(
        typeof m.compute?.memoryGb,
        `${toolId}: compute.memoryGb missing`,
      ).toBe("number");
    });

    it("exposes a Python adapter entrypoint (adapter.py or modal_app.py)", () => {
      const { adapterPy, modalAppPy } = locateAdapter(toolDir);
      expect(
        adapterPy ?? modalAppPy,
        `${toolId}: needs adapter.py or modal_app.py in ${toolDir}`,
      ).toBeTruthy();
    });

    it("adapter entrypoint imports the SDK or modal", () => {
      const { adapterPy, modalAppPy } = locateAdapter(toolDir);
      if (modalAppPy) {
        const src = readFileSync(modalAppPy, "utf-8");
        expect(src, `${toolId}: modal_app.py must import modal`).toMatch(
          /\b(?:import modal|from modal import)\b/,
        );
        expect(
          src,
          `${toolId}: modal_app.py must define \`app = modal.App(...)\``,
        ).toMatch(/\bapp\s*=\s*(?:modal\.)?App\s*\(/);
      } else if (adapterPy) {
        const src = readFileSync(adapterPy, "utf-8");
        expect(
          /papercrane_sdk/.test(src) || /\bclass\s+\w+Adapter\b/.test(src),
          `${toolId}: adapter.py should reference papercrane_sdk or define an *Adapter class`,
        ).toBe(true);
      }
    });

    it("input_schema is valid JSON Schema (draft-07 or 2020-12)", () => {
      const schemaPath = path.join(toolDir, "schemas", "input.json");
      expect(
        existsSync(schemaPath),
        `${toolId}: missing schemas/input.json`,
      ).toBe(true);
      const schema = readJsonIfExists(schemaPath);
      // Compile under Ajv2020; draft-07 schemas with $schema set still compile.
      expect(
        () => compileSchema(schema),
        `${toolId}: input schema is not compilable`,
      ).not.toThrow();
    });

    it("manifest defaults conform to the tool-parameter schema", () => {
      const { jsonPath } = locateManifest(toolDir);
      if (!jsonPath) return;
      const manifest = readJsonIfExists(jsonPath) as ManifestShape;
      const schemaPath = path.join(toolDir, "schemas", "input.json");
      const schema = readJsonIfExists(schemaPath) as Record<string, unknown>;
      const paramsSchema = parameterSchema(schema);
      const validate = compileSchema(paramsSchema);
      const valid = validate(manifest.defaultParams ?? {});
      expect(
        valid,
        `${toolId}: defaultParams do not satisfy input schema: ${JSON.stringify(validate.errors)}`,
      ).toBe(true);
    });

    it("output_schema is valid JSON Schema (draft-07 or 2020-12)", () => {
      const schemaPath = path.join(toolDir, "schemas", "output.json");
      expect(
        existsSync(schemaPath),
        `${toolId}: missing schemas/output.json`,
      ).toBe(true);
      const schema = readJsonIfExists(schemaPath);
      expect(
        () => compileSchema(schema),
        `${toolId}: output schema is not compilable`,
      ).not.toThrow();
    });

    it("README.md exists", () => {
      expect(
        existsAsFile(path.join(toolDir, "README.md")),
        `${toolId}: missing README.md`,
      ).toBe(true);
    });

    it('closed-weights tools are tier="frontier"', () => {
      const { jsonPath } = locateManifest(toolDir);
      if (!jsonPath) return;
      const m = readJsonIfExists(jsonPath) as ManifestShape;
      const looksClosed =
        m.closed_weights === true ||
        existsAsFile(path.join(toolDir, "LICENSE-GATE.md"));
      if (looksClosed) {
        expect(
          m.tier,
          `${toolId}: closed-weights tools must declare tier="frontier" so feature_flags.closed_weights_allowed gates access`,
        ).toBe("frontier");
      }
    });
  });
});
