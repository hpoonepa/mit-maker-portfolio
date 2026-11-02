import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkflowId } from "@papercrane/types";
import { WorkflowPicker } from "./WorkflowPicker";

afterEach(cleanup);

describe("WorkflowPicker", () => {
  it("shows all three goals and selects an available workflow", () => {
    const onSelect = vi.fn();
    const available = new Set<WorkflowId>([
      "binder-screen",
      "binder-standard",
      "binder-high-confidence",
    ]);
    render(
      <WorkflowPicker
        selectedId={null}
        availableIds={available}
        onSelect={onSelect}
      />,
    );

    expect(screen.getAllByRole("button")).toHaveLength(3);
    fireEvent.click(
      screen.getByRole("button", { name: /Binder design \+ validation/ }),
    );
    expect(onSelect).toHaveBeenCalledWith("binder-standard");
  });

  it("disables a workflow with an unavailable stage", () => {
    render(
      <WorkflowPicker
        selectedId={null}
        availableIds={new Set<WorkflowId>(["binder-screen"])}
        onSelect={vi.fn()}
      />,
    );

    expect(
      screen
        .getByRole("button", { name: /High-confidence binder campaign/ })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
});
