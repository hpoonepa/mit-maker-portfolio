import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JobWizard } from "./JobWizard";

const steps = [
  { id: "tools", label: "Tools" },
  { id: "review", label: "Review & run" },
];

describe("JobWizard", () => {
  afterEach(cleanup);

  it("shows a clear submission handoff instead of only disabling the button", () => {
    render(
      <JobWizard
        steps={steps}
        currentIndex={1}
        onBack={vi.fn()}
        onNext={vi.fn()}
        nextLabel="Launch 8 designs"
        busy
      >
        <p>Review content</p>
      </JobWizard>,
    );

    expect(screen.getByRole("status").textContent).toContain(
      "Submitting your run",
    );
    expect(screen.getByRole("button", { name: /submitting/i })).toBeTruthy();
    expect(screen.getByText(/live progress will open automatically/i)).toBeTruthy();
  });
});
