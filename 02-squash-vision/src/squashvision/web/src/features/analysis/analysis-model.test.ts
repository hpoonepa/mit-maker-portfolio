// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import { boundedObservationWindow, evidenceStep, shouldIgnorePlaybackShortcut } from "./analysis-model";

describe("analysis playback model", () => {
  it("clamps a visible observation query to the match and thirty seconds", () => {
    expect(boundedObservationWindow(4_000_000, 100_000_000)).toEqual({ startUs: 0, endUs: 20_000_000 });
    expect(boundedObservationWindow(55_000_000, 60_000_000)).toEqual({ startUs: 40_000_000, endUs: 60_000_000 });
    const middle = boundedObservationWindow(50_000_000, 100_000_000);
    expect(middle.endUs - middle.startUs).toBe(30_000_000);
  });

  it("keeps advancing frames in one cache window and buffers both sides at a boundary", () => {
    const window = boundedObservationWindow(21_000_000, 180_000_000);
    expect(boundedObservationWindow(29_999_999, 180_000_000)).toEqual(window);
    expect(window).toEqual({ startUs: 10_000_000, endUs: 40_000_000 });
    expect(boundedObservationWindow(30_000_000, 180_000_000)).toEqual({ startUs: 20_000_000, endUs: 50_000_000 });
    expect(boundedObservationWindow(-10_000, 180_000_000)).toEqual({ startUs: 0, endUs: 20_000_000 });
    expect(boundedObservationWindow(200_000_000, 180_000_000)).toEqual({ startUs: 170_000_000, endUs: 180_000_000 });
  });

  it("steps on real evidence timestamps rather than nominal frame rate", () => {
    const timestamps = [1_000_000, 1_033_400, 1_083_900];
    expect(evidenceStep(timestamps, 1_034_000, 1)).toEqual({ timestampUs: 1_083_900, exact: false });
    expect(evidenceStep(timestamps, 1_083_900, -1)).toEqual({ timestampUs: 1_033_400, exact: true });
  });

  it("never hijacks playback keys from editable or interactive controls", () => {
    const input = document.createElement("input");
    const button = document.createElement("button");
    const tab = document.createElement("div");
    tab.setAttribute("role", "tab");
    expect(shouldIgnorePlaybackShortcut(input)).toBe(true);
    expect(shouldIgnorePlaybackShortcut(button)).toBe(true);
    expect(shouldIgnorePlaybackShortcut(tab)).toBe(true);
  });
});
