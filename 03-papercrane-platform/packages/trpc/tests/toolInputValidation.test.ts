import { describe, expect, it } from "vitest";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { validateToolParameters } from "../src/config/toolInputValidation.js";

const wrappedSchema = {
  type: "object",
  required: ["seeds", "params"],
  properties: {
    seeds: { type: "array", items: { type: "integer" } },
    params: {
      type: "object",
      additionalProperties: false,
      properties: {
        exhaustiveness: { type: "integer", minimum: 1, maximum: 128 },
        mode: { type: "string", enum: ["fast", "accurate"] },
        sequences: {
          type: "array",
          items: { type: "string", pattern: "^[A-Z]+$" },
        },
      },
    },
  },
};

describe("tool input validation", () => {
  it("accepts every checked-in manifest's own default parameters", () => {
    const toolsDir = path.resolve(__dirname, "..", "..", "..", "tools");
    const failures: string[] = [];

    for (const toolId of readdirSync(toolsDir)) {
      const manifestPath = path.join(toolsDir, toolId, "manifest.json");
      if (!existsSync(manifestPath)) continue;
      const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as {
        inputSchema: string;
        defaultParams?: Record<string, unknown>;
      };
      const schemaPath = path.join(toolsDir, toolId, manifest.inputSchema);
      const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as unknown;
      const result = validateToolParameters(schema, manifest.defaultParams, {});
      if (!result.valid) {
        failures.push(`${toolId}: ${result.message ?? "invalid defaults"}`);
      }
    }

    expect(failures).toEqual([]);
  });

  it("validates merged defaults and user overrides", () => {
    expect(
      validateToolParameters(
        wrappedSchema,
        { exhaustiveness: 8, mode: "fast" },
        { exhaustiveness: 32 },
      ),
    ).toEqual({ valid: true });

    expect(
      validateToolParameters(
        wrappedSchema,
        { exhaustiveness: 8 },
        { exhaustiveness: 256 },
      ),
    ).toMatchObject({
      valid: false,
      message: expect.stringContaining("<= 128"),
    });
  });

  it("ignores canonical platform fields but rejects unknown advanced fields", () => {
    expect(
      validateToolParameters(
        wrappedSchema,
        {},
        {
          targetPdb: "1ABC",
          targetId: "owned-target",
          exhaustiveness: 16,
        },
      ),
    ).toEqual({ valid: true });

    expect(
      validateToolParameters(wrappedSchema, {}, { mysteryFlag: true }),
    ).toMatchObject({
      valid: false,
      message: expect.stringContaining("unsupported parameter 'mysteryFlag'"),
    });
  });

  it("validates canonical adapter inputs when the parameter schema declares them", () => {
    expect(
      validateToolParameters(wrappedSchema, {}, { sequences: ["ACDEFG"] }),
    ).toEqual({ valid: true });
    expect(
      validateToolParameters(wrappedSchema, {}, { sequences: ["not-protein"] }),
    ).toMatchObject({ valid: false });
  });

  it("rejects worker-owned transport fields", () => {
    expect(
      validateToolParameters(
        wrappedSchema,
        {},
        {
          _papercrane: { artifactUploads: { spoofed: true } },
        },
      ),
    ).toEqual({
      valid: false,
      message:
        "Invalid tool parameters: '_papercrane' is managed by Paper Crane.",
    });
    expect(
      validateToolParameters(wrappedSchema, {}, { prevOutput: {} }),
    ).toMatchObject({ valid: false });
    expect(
      validateToolParameters(wrappedSchema, {}, { num_designs: 99 }),
    ).toMatchObject({
      valid: false,
      message: expect.stringContaining("'num_designs' is managed"),
    });
    expect(
      validateToolParameters(wrappedSchema, {}, { num_seq_per_target: 8 }),
    ).toMatchObject({ valid: false });
  });

  it("supports direct tool-parameter schemas", () => {
    const direct = {
      type: "object",
      additionalProperties: false,
      properties: { noise_scale: { type: "number", minimum: 0, maximum: 2 } },
    };
    expect(validateToolParameters(direct, { noise_scale: 1 }, {})).toEqual({
      valid: true,
    });
    expect(
      validateToolParameters(direct, {}, { noise_scale: -1 }),
    ).toMatchObject({
      valid: false,
    });
  });

  it("supports draft 2020-12 schemas", () => {
    const schema2020 = {
      $schema: "https://json-schema.org/draft/2020-12/schema",
      type: "object",
      properties: {
        range: {
          type: "array",
          prefixItems: [{ type: "number" }, { type: "number" }],
          items: false,
        },
      },
    };
    expect(validateToolParameters(schema2020, {}, { range: [1, 2] })).toEqual({
      valid: true,
    });
    expect(
      validateToolParameters(schema2020, {}, { range: [1, 2, 3] }),
    ).toMatchObject({ valid: false });
  });

  it("keeps root definitions available to wrapped parameter refs", () => {
    const withDefinition = {
      type: "object",
      properties: {
        params: {
          type: "object",
          properties: {
            referenceSequences: {
              type: "array",
              items: { $ref: "#/definitions/sequenceRecord" },
            },
          },
        },
      },
      definitions: {
        sequenceRecord: {
          type: "object",
          required: ["sequence"],
          properties: { sequence: { type: "string", minLength: 6 } },
        },
      },
    };

    expect(
      validateToolParameters(
        withDefinition,
        {},
        {
          referenceSequences: [{ sequence: "ACDEFG" }],
        },
      ),
    ).toEqual({ valid: true });
    expect(
      validateToolParameters(
        withDefinition,
        {},
        {
          referenceSequences: [{ sequence: "BAD" }],
        },
      ),
    ).toMatchObject({ valid: false });
  });

  it("skips legacy path-only schemas", () => {
    expect(
      validateToolParameters({ $ref: "schemas/input.json" }, {}, {}),
    ).toEqual({ valid: true, skipped: true });
  });

  it("fails closed when an embedded catalog schema is malformed", () => {
    expect(
      validateToolParameters(
        {
          type: "object",
          properties: { value: { $ref: "#/definitions/missing" } },
        },
        {},
        { value: 1 },
      ),
    ).toMatchObject({ valid: false, configurationError: true });
  });
});
