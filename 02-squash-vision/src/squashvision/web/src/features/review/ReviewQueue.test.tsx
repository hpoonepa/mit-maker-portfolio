// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReviewQueue } from "./ReviewQueue";
import type { ReviewItem } from "./review-model";

const items: ReviewItem[] = [
  {
    id: "boundary-1", targetType: "rally", kind: "rally_boundary", timestampUs: 8_000_000, endUs: 8_500_000,
    confidence: 0.35, issue: "rally_boundary", evidenceIds: ["ev-1"], provenance: "reconstructed",
    probabilities: { split: 0.65, continuous: 0.35 }, reasons: ["ball seam interrupted"],
    evidenceStartTimestampUs: 8_000_000, evidenceEndTimestampUs: 8_500_000, evidenceStartFrameIndex: 240, evidenceEndFrameIndex: 255,
    invalidatedSections: ["overview", "shots", "rallies", "errors"], invalidatedStats: ["rally_count", "shot_rally_id"], summary: {},
    commandTargets: {}, commandImpacts: {},
    reviewEntityType: "rally", reviewEntityId: "boundary-1", reviewStatus: "pending",
  },
  {
    id: "shot-1", targetType: "shot", kind: "shot", timestampUs: 12_000_000, endUs: null,
    confidence: 0.48, issue: "hitter", evidenceIds: ["ev-2"], provenance: "observed",
    probabilities: { near: 0.48, far: 0.45 }, reasons: ["occlusion"],
    evidenceStartTimestampUs: 11_950_000, evidenceEndTimestampUs: 12_050_000, evidenceStartFrameIndex: 360, evidenceEndFrameIndex: 363,
    invalidatedSections: ["shots"], invalidatedStats: ["player_shot_counts"], summary: {},
    commandTargets: {}, commandImpacts: {},
    reviewEntityType: "shot", reviewEntityId: "shot-1", reviewStatus: "pending",
  },
];

afterEach(cleanup);

describe("correction review queue", () => {
  it("shows priority evidence, provenance, probabilities, and selected-command impact", () => {
    render(<ReviewQueue items={items} currentIndex={0} reviewedCount={1} totalCount={3} activeImpact={{ invalidatedSections: ["trajectory"], invalidatedStats: ["ball_trajectory"] }} onNavigate={vi.fn()} onSeek={vi.fn()} onShortcut={vi.fn()} />);
    expect(screen.getByText("1 of 3 reviewed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "0:08.000–0:08.500" })).toBeInTheDocument();
    expect(screen.getByText("Reconstructed evidence")).toBeInTheDocument();
    expect(screen.getByText("Trajectory")).toBeInTheDocument();
    expect(screen.getByText("Ball Trajectory")).toBeInTheDocument();
    expect(screen.getByText(/split.*65%/i)).toBeInTheDocument();
  });

  it("supports visible review shortcuts only while panel focus is outside inputs", () => {
    const shortcut = vi.fn();
    const navigate = vi.fn();
    render(<ReviewQueue items={items} currentIndex={0} reviewedCount={0} totalCount={2} onNavigate={navigate} onSeek={vi.fn()} onShortcut={shortcut} />);
    const panel = screen.getByRole("region", { name: "Correction review queue" });
    panel.focus();
    for (const [key, command] of [["a", "accept"], ["r", "reject"], ["h", "cycle_hitter"], ["s", "cycle_shot"], ["o", "cycle_outcome"]]) {
      fireEvent.keyDown(panel, { key });
      expect(shortcut).toHaveBeenLastCalledWith(command);
    }
    fireEvent.keyDown(panel, { key: "]" });
    expect(navigate).toHaveBeenCalledWith(1);
    expect(screen.getByText(/A accept · R reject · H hitter · S shot · O outcome/)).toBeInTheDocument();

    const input = document.createElement("input");
    panel.append(input);
    fireEvent.keyDown(input, { key: "a" });
    expect(shortcut).toHaveBeenCalledTimes(5);
  });
});
