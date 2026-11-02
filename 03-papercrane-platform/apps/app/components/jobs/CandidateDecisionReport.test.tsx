import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const queryState: { current: Record<string, unknown> } = {
  current: { isLoading: true, isFetching: false, isError: false },
};
const queryEnabled = { current: false };

vi.mock("@/lib/trpc/client", () => ({
  trpc: {
    designs: {
      decisionReport: {
        useQuery: (
          _input: unknown,
          options: { enabled?: boolean },
        ) => {
          queryEnabled.current = options.enabled ?? true;
          return queryState.current;
        },
      },
    },
  },
}));

vi.mock("@/lib/utils", () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(" "),
}));

import { CandidateDecisionReport } from "./CandidateDecisionReport";

function candidate(seed: number) {
  return {
    decisionRank: seed,
    designId: `design-${seed}`,
    seed,
    recommendation: seed === 1 ? "advance" : "review",
    confidence: "medium",
    provenance: "real",
    reason: "Computational evidence",
    metaScore: {
      score: 0.9 - seed / 100,
      coverage: 0.62,
      version: "llm-prior-v2-platform.1",
      contributions: [{ label: "min ipSAE" }, { label: "interface residues" }],
    },
  };
}

function report(count = 10) {
  return {
    methodology: { scorerVersion: "llm-prior-v2-platform.1" },
    summary: {
      candidatesEvaluated: count,
      candidatesAvailable: count,
      truncated: false,
      advance: 1,
      review: count - 1,
      hold: 0,
      insufficientData: 0,
      nextStep: "Inspect the advance set before selecting experiments.",
    },
    candidates: Array.from({ length: count }, (_value, index) => candidate(index + 1)),
  };
}

describe("CandidateDecisionReport", () => {
  afterEach(cleanup);

  beforeEach(() => {
    queryState.current = { isLoading: true, isFetching: false, isError: false };
    queryEnabled.current = false;
  });

  it("runs the real selector query before revealing the decision report", () => {
    queryState.current = {
      isLoading: false,
      isFetching: false,
      isError: false,
      data: report(),
    };

    render(<CandidateDecisionReport jobId="job-1" />);

    expect(queryEnabled.current).toBe(false);
    expect(
      screen.getByRole("heading", { name: /rank this job's candidates/i }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /score candidates/i }));

    expect(queryEnabled.current).toBe(true);
    expect(screen.getByText("Binder selection report")).toBeTruthy();
    expect(screen.getByText("Lead candidate")).toBeTruthy();
    expect(screen.getAllByText("Seed 1").length).toBeGreaterThan(0);
    expect(screen.getByText(/No wet-lab evidence/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /show all 10 candidates/i })).toBeTruthy();
  });

  it("expands beyond the top eight candidates", () => {
    queryState.current = {
      isLoading: false,
      isFetching: false,
      isError: false,
      data: report(),
    };
    render(<CandidateDecisionReport jobId="job-1" />);
    fireEvent.click(screen.getByRole("button", { name: /score candidates/i }));

    expect(screen.queryByText("Seed 10")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /show all 10 candidates/i }));
    expect(screen.getAllByText("Seed 10").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /show top 8/i })).toBeTruthy();
  });

  it("shows clear live stages while the selector request is running", () => {
    queryState.current = {
      isLoading: true,
      isFetching: true,
      isError: false,
    };
    render(<CandidateDecisionReport jobId="job-1" />);

    fireEvent.click(screen.getByRole("button", { name: /score candidates/i }));

    expect(screen.getByRole("region", { name: /binder selector running/i })).toBeTruthy();
    expect(screen.getByRole("progressbar", { name: /binder selection progress/i })).toBeTruthy();
    expect(screen.getByText("Reading candidate metrics")).toBeTruthy();
    expect(screen.getByText("Applying the versioned prior")).toBeTruthy();
    expect(screen.getByText("Building the shortlist")).toBeTruthy();
  });
});
