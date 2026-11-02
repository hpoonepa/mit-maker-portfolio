import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ResultMetrics } from "./ResultMetrics";
afterEach(cleanup);
it("explains only returned native Boltz scores and links their documentation", () => {
  render(<ResultMetrics tool="boltz2" metrics={{chain_count: 1, complex_plddt: 0.5886, complex_pde: 0.9011, ipTM: 0}} />);
  expect(screen.getByText("0.5886")).toBeTruthy();
  expect(screen.getByText("0.9011")).toBeTruthy();
  expect(screen.queryByText("ipTM")).toBeNull();
  expect(screen.queryByText("chain count")).toBeNull();
  expect(screen.getByRole("link", {name: "Boltz output documentation"}).getAttribute("href")).toContain("prediction.md#output");
  expect(screen.getByText(/Mean predicted distance error in angstroms/)).toBeTruthy();
  expect(screen.queryByText("PAE")).toBeNull();
});
