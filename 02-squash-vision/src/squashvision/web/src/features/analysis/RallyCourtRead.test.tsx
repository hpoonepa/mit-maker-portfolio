// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => cleanup());

import type { components } from "../../api/types.generated";
import { RallyCourtRead, buildContactPath, mapCourtPoint } from "./RallyCourtRead";

type ShotDetail = components["schemas"]["ShotDetail"];

const shots: ShotDetail[] = [
  { id: "shot-1", timestampUs: 1_000_000, predictionRevision: 1, rallyId: "rally-1", hitter: "near", shotKind: "drive", isVolley: false, outcome: "in_play", contact: [0, 0] as [number, number], speedMS: null, speedUnavailableReason: null, sourceEvidenceIds: ["evidence-1"] },
  { id: "shot-2", timestampUs: 2_000_000, predictionRevision: 1, rallyId: "rally-1", hitter: "far", shotKind: "drop", isVolley: true, outcome: "winner", contact: null, speedMS: null, speedUnavailableReason: null, sourceEvidenceIds: [] },
  { id: "shot-3", timestampUs: 3_000_000, predictionRevision: 1, rallyId: "rally-1", hitter: "near", shotKind: "kill", isVolley: false, outcome: "error", contact: [6.4, 9.75] as [number, number], speedMS: null, speedUnavailableReason: null, sourceEvidenceIds: [] },
];

describe("RallyCourtRead", () => {
  it("places the front-left origin at the top and back wall at the bottom", () => {
    expect(mapCourtPoint([0, 0])).toEqual({ x: 0, y: 0 });
    expect(mapCourtPoint([3.2, 4.875])).toEqual({ x: 320, y: 487.5 });
    expect(mapCourtPoint([6.4, 9.75])).toEqual({ x: 640, y: 975 });
  });

  it("breaks contact paths across missing contacts", () => {
    expect(buildContactPath(shots)).toEqual([["shot-1"], ["shot-3"]]);
  });

  it("leads with the measured outcome and offers direct rally playback", () => {
    const onSeekShot = vi.fn();
    render(<RallyCourtRead rally={{ id: "rally-1", ordinal: 1, startUs: 1_000_000, endUs: 3_000_000, timingAvailable: true, outcome: "error", reviewStatus: "pending", sourceEvidenceIds: ["rally-evidence"], representativeEventId: "representative-1" }} shots={shots} selectedShotId="shot-3" onSeekShot={onSeekShot} onPlayEvidence={onSeekShot} />);
    expect(screen.getByRole("heading", { name: "ERROR · A · KILL" })).toBeInTheDocument();
    expect(screen.getByText(/contact path—not ball flight/i)).toBeInTheDocument();
    expect(screen.getByText("Front wall")).toBeInTheDocument();
    expect(screen.getByText("Back court")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Play Rally 1 evidence.*0:01.000–0:03.000/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Play Rally 1 evidence/i }));
    expect(onSeekShot).toHaveBeenCalledWith("representative-1");
    fireEvent.click(screen.getAllByRole("button", { name: /Shot 1.*DRIVE/i })[1]);
    expect(onSeekShot).toHaveBeenCalledWith("evidence-1");
  });
  it("supports Enter and Space activation on positioned SVG points", () => {
    const onSeekShot = vi.fn();
    render(<RallyCourtRead rally={{ id: "rally-1", ordinal: 1, startUs: 0, endUs: 1_000_000, timingAvailable: true, outcome: "in_play", reviewStatus: "not_required", sourceEvidenceIds: [] }} shots={[shots[0]]} onSeekShot={onSeekShot} />);
    const point = screen.getAllByRole("button", { name: /Shot 1.*DRIVE/i })[0];
    fireEvent.keyDown(point, { key: "Enter" });
    fireEvent.keyDown(point, { key: " " });
    expect(onSeekShot).toHaveBeenNthCalledWith(1, "evidence-1");
    expect(onSeekShot).toHaveBeenNthCalledWith(2, "evidence-1");
  });

  it("keeps textual sequence and actions when calibrated contacts are unavailable", () => {
    render(<RallyCourtRead rally={{ id: "rally-2", ordinal: 2, startUs: null, endUs: null, timingAvailable: false, outcome: null, reviewStatus: "not_required", sourceEvidenceIds: [] }} shots={shots.map((shot) => ({ ...shot, contact: null }))} onSeekShot={vi.fn()} />);
    expect(screen.getByText(/Court contact path unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /accessible shot sequence/i })).toBeInTheDocument();
    expect(screen.getByText(/Timing unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Outcome unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Shot 2.*DROP/i })).toBeInTheDocument();
  });

  it("does not turn a measured zero coordinate into unavailable", () => {
    render(<RallyCourtRead rally={{ id: "rally-1", ordinal: 1, startUs: 0, endUs: 1_000_000, timingAvailable: true, outcome: "in_play", reviewStatus: "not_required", sourceEvidenceIds: [] }} shots={[shots[0]]} onSeekShot={vi.fn()} />);
    expect(screen.getByRole("img", { name: /contact path for rally 1/i })).toBeInTheDocument();
    expect(screen.queryByText(/contact path unavailable/i)).not.toBeInTheDocument();
  });

  it("draws direction only for consecutive positioned contacts", () => {
    const consecutive = [
      shots[0],
      { ...shots[2], id: "shot-2-positioned", contact: [2.4, 5] as [number, number], timestampUs: 2_000_000 },
    ];
    const { container } = render(<RallyCourtRead rally={{ id: "rally-1", ordinal: 1, startUs: 0, endUs: 2_000_000, timingAvailable: true, outcome: "winner", reviewStatus: "accepted", sourceEvidenceIds: [] }} shots={consecutive} onSeekShot={vi.fn()} />);
    expect(container.querySelector("polyline[marker-end]")).not.toBeNull();
  });
});
