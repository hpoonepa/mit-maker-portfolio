import { describe, expect, it } from "vitest";

import {
  parameterFieldsFromJsonSchema,
  resolvedParameterDefaults,
} from "./jsonSchemaParams";

describe("JSON Schema parameter projection", () => {
  const schema = {
    type: "object",
    required: ["seeds", "params"],
    properties: {
      seeds: { type: "array", items: { type: "integer" } },
      params: {
        type: "object",
        required: ["exhaustiveness"],
        properties: {
          targetPdb: { type: "string" },
          exhaustiveness: {
            type: "integer",
            minimum: 1,
            maximum: 128,
            default: 8,
          },
          mode: { type: "string", enum: ["fast", "accurate"] },
          alignmentType: { type: "integer", enum: [0, 1, 2] },
          boxSize: {
            type: "array",
            minItems: 3,
            maxItems: 3,
            items: { type: "number", minimum: 5, maximum: 100 },
          },
          enabled: { type: "boolean", default: true },
        },
      },
    },
  };

  it("projects supported fields and omits canonical wizard input", () => {
    const fields = parameterFieldsFromJsonSchema(schema, {
      exhaustiveness: 12,
      boxSize: [22, 22, 22],
    });

    expect(fields.map((field) => field.key)).toEqual([
      "exhaustiveness",
      "mode",
      "alignmentType",
      "boxSize",
      "enabled",
    ]);
    expect(fields[0]).toMatchObject({
      kind: "integer",
      required: true,
      default: 12,
      min: 1,
      max: 128,
    });
    expect(fields[2]).toMatchObject({
      kind: "enum",
      options: [
        { value: 0, label: "0" },
        { value: 1, label: "1" },
        { value: 2, label: "2" },
      ],
    });
    expect(fields[3]).toMatchObject({
      kind: "array-number",
      default: [22, 22, 22],
      minItems: 3,
      maxItems: 3,
    });
  });

  it("uses schema defaults but lets manifest defaults win", () => {
    expect(
      resolvedParameterDefaults(schema, {
        exhaustiveness: 16,
        mode: "accurate",
        num_designs: 10,
        num_seq_per_target: 8,
      }),
    ).toEqual({
      exhaustiveness: 16,
      mode: "accurate",
      enabled: true,
    });
  });
});
