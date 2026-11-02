// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CourtOverlayEditor,
  clientPointToImage,
  videoContentRect,
} from "./CourtOverlayEditor";

const proposal = [
  { label: "front-left", image: { x: 240, y: 160 }, court: { xM: 0, yM: 0 } },
  { label: "front-right", image: { x: 1680, y: 160 }, court: { xM: 6.4, yM: 0 } },
];

afterEach(cleanup);

describe("court calibration overlay", () => {
  it("maps pointer coordinates through object-fit letterboxing at any size", () => {
    const content = videoContentRect(
      { left: 100, top: 40, width: 800, height: 600 },
      { width: 1920, height: 1080 },
    );
    expect(content).toEqual({ left: 100, top: 115, width: 800, height: 450 });
    expect(clientPointToImage({ x: 500, y: 340 }, content, { width: 1920, height: 1080 })).toEqual({
      x: 960,
      y: 540,
    });
    expect(clientPointToImage({ x: 0, y: 0 }, content, { width: 1920, height: 1080 })).toEqual({
      x: 0,
      y: 0,
    });
  });

  it("gives labeled handles precise arrow and shift-arrow keyboard edits", () => {
    const onChange = vi.fn();
    render(
      <CourtOverlayEditor
        frameSize={{ width: 1920, height: 1080 }}
        keypoints={proposal}
        proposalKeypoints={proposal}
        onChange={onChange}
        videoSrc="/api/v1/matches/match-1/media/proxy"
      />,
    );

    const handle = screen.getByRole("button", { name: "Move front-left calibration point" });
    const stage = handle.closest(".video-stage");
    expect(stage).toHaveAttribute("data-dragging", "false");
    fireEvent.pointerDown(handle);
    expect(stage).toHaveAttribute("data-dragging", "true");
    fireEvent.pointerUp(handle);
    expect(stage).toHaveAttribute("data-dragging", "false");
    const hitTarget = handle.querySelector(".calibration-hit-target");
    const sourceRadius = Number(hitTarget?.getAttribute("r"));
    expect(sourceRadius * 2 * (320 / 1920)).toBeGreaterThanOrEqual(44);
    expect(handle).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(handle, { key: "Escape" });
    expect(handle).toHaveAttribute("aria-pressed", "false");
    fireEvent.keyDown(handle, { key: "Enter" });
    expect(handle).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ image: { x: 241, y: 160 } }),
      proposal[1],
    ]);
    fireEvent.keyDown(handle, { key: "ArrowDown", shiftKey: true });
    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ image: { x: 240, y: 170 } }),
      proposal[1],
    ]);
  });

  it("distinguishes automatic proposals from edited manual evidence and can reset", () => {
    const onChange = vi.fn();
    const manual = [{ ...proposal[0], image: { x: 250, y: 160 } }, proposal[1]];
    render(
      <CourtOverlayEditor
        frameSize={{ width: 1920, height: 1080 }}
        keypoints={manual}
        proposalKeypoints={proposal}
        onChange={onChange}
        videoSrc="/api/v1/matches/match-1/media/proxy"
      />,
    );

    expect(screen.getByTestId("proposal-court-lines")).toHaveAttribute("data-line-style", "dashed");
    expect(screen.getByTestId("manual-court-lines")).toHaveAttribute("data-line-style", "solid");
    fireEvent.click(screen.getByRole("button", { name: "Reset to automatic proposal" }));
    expect(onChange).toHaveBeenCalledWith(proposal);
  });
});
