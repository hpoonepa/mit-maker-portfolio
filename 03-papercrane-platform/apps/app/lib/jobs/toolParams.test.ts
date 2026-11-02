import { describe, expect, it } from "vitest";

import {
  mergeToolParams,
  parseToolParamsJson,
  serializeToolParams,
} from "./toolParams";

describe("tool parameters", () => {
  it("accepts an object and treats empty input as defaults", () => {
    expect(parseToolParamsJson('{"temperature":0.2}')).toEqual({
      value: { temperature: 0.2 },
      error: null,
    });
    expect(parseToolParamsJson("  ")).toEqual({ value: {}, error: null });
  });

  it("rejects malformed and non-object JSON", () => {
    expect(parseToolParamsJson("[")).toMatchObject({ value: null });
    expect(parseToolParamsJson("[]")).toEqual({
      value: null,
      error: "Parameters must be a JSON object.",
    });
  });

  it("formats catalog defaults for the editor", () => {
    expect(serializeToolParams({ temperature: 0.2 })).toBe(
      '{\n  "temperature": 0.2\n}',
    );
    expect(serializeToolParams(undefined)).toBe("{}");
  });

  it("does not let advanced values replace canonical job input", () => {
    expect(
      mergeToolParams(
        { targetId: "spoofed", temperature: 0.4 },
        { targetId: "owned-target" },
      ),
    ).toEqual({ targetId: "owned-target", temperature: 0.4 });
  });

  it("drops worker-owned transport fields from advanced input", () => {
    expect(
      mergeToolParams(
        {
          _papercrane: { artifactUploads: { spoofed: true } },
          seeds: [999],
          numDesigns: 999,
          num_designs: 999,
          num_seq_per_target: 999,
          temperature: 0.2,
        },
        { targetPdb: "1ABC" },
      ),
    ).toEqual({ targetPdb: "1ABC", temperature: 0.2 });
  });
});
