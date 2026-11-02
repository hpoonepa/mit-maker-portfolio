import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { normaliseProvenance, ProvenanceBadge } from "./ProvenanceBadge";

describe("unverified provenance", () => {
  it.each([undefined, null, "", "unexpected"])("does not certify missing or invalid origin %s", (value) => {
    expect(normaliseProvenance(value)).toBe("unknown");
  });
  it("shows a warning when origin is missing", () => {
    render(<ProvenanceBadge provenance={undefined} />);
    expect(screen.getByText("Unverified origin")).toBeTruthy();
  });
  it.each(["real", "synthetic", "stub"])("preserves explicitly recorded %s origin", (value) => {
    expect(normaliseProvenance(value)).toBe(value);
  });
});
