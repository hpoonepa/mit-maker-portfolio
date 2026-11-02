import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DesignDetail } from "./DesignDetail";
vi.mock("next/dynamic", () => ({ default: () => () => <div data-testid="structure-viewer" /> }));
vi.mock("@/components/annotations/StarButton", () => ({ StarButton: () => null }));
vi.mock("@/components/annotations/TagChips", () => ({ TagChips: () => null }));
vi.mock("@/components/annotations/CommentThread", () => ({ CommentThread: () => null }));
vi.mock("@/lib/trpc/client", () => ({ trpc: { annotations: { listByDesign: { useQuery: () => ({}) } }, members: { list: { useQuery: () => ({}) } } } }));
afterEach(cleanup);
const props = { designId: "result-1", seed: 103, sequence: "MKT", length: 3, metrics: { score: 0.8022, recovery: 0.5526 }, jobId: "job-1", provenance: "real" };
it("does not render a fake structure or invented secondary structure for sequence output", () => {
  render(<DesignDetail {...props} tool="proteinmpnn" structureUrl="https://example.org/sequence.cif" />);
  expect(screen.getByText("55.26%")).toBeTruthy();
  expect(screen.queryByTestId("structure-viewer")).toBeNull();
  expect(screen.queryByRole("link", { name: /^CIF$/ })).toBeNull();
  expect(screen.queryByText(/meta-score|DSSP|6X1A/i)).toBeNull();
});
it("only renders the coordinate viewer when a coordinate tool has an artifact", () => {
  const view = render(<DesignDetail {...props} tool="boltz2" structureUrl={null} />);
  expect(screen.queryByTestId("structure-viewer")).toBeNull();
  view.rerender(<DesignDetail {...props} tool="boltz2" structureUrl="https://example.org/result.cif" />);
  expect(screen.getByTestId("structure-viewer")).toBeTruthy();
  expect(screen.getByRole("link", { name: /^CIF$/ })).toBeTruthy();
});
