import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ParamsEditor, validateParams, type ParamField } from "./ParamsEditor";

describe("ParamsEditor", () => {
  it("preserves numeric enum values and fractional input for integer validation", () => {
    const onChange = vi.fn();
    const schema: ParamField[] = [
      {
        kind: "enum",
        key: "mode",
        label: "Mode",
        options: [
          { value: 1, label: "Fast" },
          { value: 2, label: "Accurate" },
        ],
      },
      { kind: "integer", key: "count", label: "Count" },
    ];
    render(
      <ParamsEditor
        schema={schema}
        value={{ mode: 1, count: 2 }}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("Mode"), {
      target: { value: "2" },
    });
    expect(onChange).toHaveBeenLastCalledWith({ mode: 2, count: 2 });

    fireEvent.change(screen.getByLabelText("Count"), {
      target: { value: "2.5" },
    });
    expect(onChange).toHaveBeenLastCalledWith({ mode: 1, count: 2.5 });
    expect(validateParams(schema, { mode: 1, count: 2.5 })).toEqual({
      count: "Count must be an integer",
    });

    fireEvent.change(screen.getByLabelText("Count"), {
      target: { value: "" },
    });
    expect(onChange).toHaveBeenLastCalledWith({ mode: 1, count: undefined });
  });

  it("validates primitive types, exclusive ranges, list sizes, and required objects", () => {
    const schema: ParamField[] = [
      {
        kind: "number",
        key: "temperature",
        label: "Temperature",
        exclusiveMin: 0,
        exclusiveMax: 1,
      },
      {
        kind: "array-string",
        key: "chains",
        label: "Chains",
        minItems: 1,
        maxItems: 2,
      },
      {
        kind: "object",
        key: "sampling",
        label: "Sampling",
        required: true,
        fields: [],
      },
    ];

    expect(
      validateParams(schema, {
        temperature: 1,
        chains: "A",
      }),
    ).toEqual({
      temperature: "Temperature must be < 1",
      chains: "Chains must be a list",
      sampling: "Sampling is required",
    });
  });
});
