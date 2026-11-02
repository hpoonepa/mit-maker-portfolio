// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../api/types.generated";
import { ballAtSourceFrame, ballTrailSegments, ballTrailWindow, computeContainTransform, isConfidentBall, sourceFrameAt, VideoOverlay } from "./VideoOverlay";
import { jsonResponse, renderApp } from "../../test-utils";

type PlayerObservation = components["schemas"]["PlayerObservationDetail"];
type BallObservation = components["schemas"]["BallObservationDetail"];

const player = {
  ambiguityReason: null,
  ambiguous: false,
  associationConfidence: 0.9,
  box: [100, 50, 180, 230],
  calibrationProvenance: "active",
  calibrationRevision: "3",
  detectionConfidence: 0.95,
  evidence: "observed",
  evidenceEndFrameIndex: 25,
  evidenceEndTimestampUs: 1_000_000,
  evidenceStartFrameIndex: 25,
  evidenceStartTimestampUs: 1_000_000,
  feet: [140, 230],
  keypoints: Array.from({ length: 17 }, (_, index) => ({ x: 110 + index * 3, y: 70 + index * 5, confidence: 0.9 })),
  skeletonEdges: [[5, 7], [7, 9], [6, 8], [8, 10]],
  feetUncertaintyPx: 3,
  floor: [2, 4],
  floorUncertaintyM: 0.1,
  modelManifestId: "players-v1",
  playerId: "near",
  sourceFrameIndex: 25,
  sourceManifestId: "proxy-map",
  sourceTimestampUs: 1_000_000,
  timestampUs: 1_000_000,
} satisfies PlayerObservation;

const balls = [
  ball("observed", 1_000_000, "segment-a", false),
  ball("interpolated", 1_020_000, "segment-a", false),
  ball("observed", 1_040_000, "segment-b", true),
];

function ball(evidence: "observed" | "interpolated", timestampUs: number, segmentId: string, ambiguous: boolean): BallObservation {
  const candidates = Array.from({ length: ambiguous ? 2 : 1 }, (_, index) => ({ x: 610 + index * 10, y: 320 + index * 5, probability: ambiguous ? 0.4 : 0.9, covariance: [[16, 0], [0, 9]] as [[number, number], [number, number]] }));
  return {
    ambiguityReason: ambiguous ? "multiple_candidates" : null,
    ambiguous,
    candidateCount: candidates.length,
    candidates,
    covariance: [[16, 0], [0, 9]],
    device: "mps",
    deviceFallback: false,
    evidence,
    evidenceEndFrameIndex: evidence === "observed" ? 2 : 3,
    evidenceEndTimestampUs: evidence === "observed" ? timestampUs : timestampUs + 10_000,
    evidenceStartFrameIndex: evidence === "observed" ? 2 : 1,
    evidenceStartTimestampUs: evidence === "observed" ? timestampUs : timestampUs - 10_000,
    modelManifestId: "ball-v1",
    probability: ambiguous ? 0.4 : 0.9,
    segmentId,
    sourceFrameIndex: evidence === "observed" ? Math.round(timestampUs / 40_000) : null,
    sourceHeight: 1080,
    sourceManifestId: "proxy-map",
    sourceTimestampUs: evidence === "observed" ? timestampUs : null,
    sourceWidth: 1920,
    timestampUs,
    visible: true,
    x: 600 + timestampUs / 100_000,
    y: 320,
  };
}

const frameMap = { startUs: 0, endUs: 20_000_000, items: [
  { proxyTimestampUs: 1_000_000, sourceTimestampUs: 1_000_000, sourceFrameIndex: 25 },
  { proxyTimestampUs: 1_033_333, sourceTimestampUs: 1_040_000, sourceFrameIndex: 26 },
  { proxyTimestampUs: 1_066_667, sourceTimestampUs: 1_080_000, sourceFrameIndex: 27 },
] };
const arc = vi.fn();
const ellipse = vi.fn();
const rect = vi.fn();
const stroke = vi.fn();
const setLineDash = vi.fn();
const lineTo = vi.fn();
const fillText = vi.fn();
const fillRect = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(frameMap))));
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.stubGlobal("IntersectionObserver", class { constructor(private callback: IntersectionObserverCallback) { this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver); } observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } root = null; rootMargin = "0px"; thresholds = [0]; });
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), scale: vi.fn(), translate: vi.fn(),
    beginPath: vi.fn(), rect, ellipse, arc, moveTo: vi.fn(), lineTo,
    stroke, fill: vi.fn(), fillText, fillRect, setLineDash, globalAlpha: 1,
  } as unknown as CanvasRenderingContext2D);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
  arc.mockClear();
  ellipse.mockClear();
  rect.mockClear();
  stroke.mockClear();
  setLineDash.mockClear();
  lineTo.mockClear();
  fillText.mockClear();
  fillRect.mockClear();
});

describe("canvas evidence overlay", () => {
  it("maps source pixels through the contained video rectangle", () => {
    expect(computeContainTransform(1920, 1080, 1000, 1000)).toEqual({ scale: 1000 / 1920, offsetX: 0, offsetY: 218.75 });
  });
  it("maps presented proxy frames to exact source evidence instead of nearby timestamps", () => {
    expect(sourceFrameAt(frameMap.items, 1_033_334, true)).toEqual(frameMap.items[1]);
    expect(sourceFrameAt(frameMap.items, 1_020_000, true)).toBeNull();
    expect(sourceFrameAt(frameMap.items, 999_000, false)).toBeNull();
    expect(sourceFrameAt(frameMap.items, 1_200_000, false)).toBeNull();
    expect(ballAtSourceFrame(balls, 1_000_001, 25)).toBeNull();
    expect(ballAtSourceFrame(balls, 1_000_000, 26)).toBeNull();
    expect(ballAtSourceFrame(balls, 1_000_000, 25)).toBe(balls[0]);
  });
  it("limits the optional trail to250ms and never connects missing evidence or segment gaps", () => {
    const rows = [ball("observed", 750_000, "a", false), ball("observed", 800_000, "a", false), { ...ball("observed", 840_000, "a", false), visible: false }, ball("observed", 880_000, "a", false), ball("observed", 920_000, "b", false), ball("observed", 1_000_000, "b", false), ball("observed", 1_000_001, "b", false)];
    const trail = ballTrailWindow(rows, 1_000_000);
    expect(trail.map((row) => row.timestampUs)).toEqual([750_000, 800_000, 840_000, 880_000, 920_000, 1_000_000]);
    expect(ballTrailSegments(trail).map(([a, b]) => [a.timestampUs, b.timestampUs])).toEqual([[750_000, 800_000]]);
  });

  it("draws skeletons without boxes and lets player switches control both", async () => {
    renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing={false} players={[player, { ...player, playerId: "far" }]} balls={[]} />);
    await screen.findByText(/Player A observed.*Player B observed/);
    expect(lineTo).toHaveBeenCalledWith(player.keypoints[7].x, player.keypoints[7].y);
    expect(rect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Overlay options"));
    expect(screen.getByRole("checkbox", { name: "Skeleton" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Boxes" })).not.toBeChecked();
    lineTo.mockClear();
    fireEvent.click(screen.getByRole("checkbox", { name: "Player A" }));
    expect(lineTo).toHaveBeenCalledTimes(4);
    fireEvent.click(screen.getByRole("checkbox", { name: "Boxes" }));
    expect(rect).toHaveBeenCalledTimes(1);
    lineTo.mockClear();
    rect.mockClear();
    fireEvent.click(screen.getByRole("checkbox", { name: "Player B" }));
    expect(lineTo).not.toHaveBeenCalled();
    expect(rect).not.toHaveBeenCalled();
  });

  it("draws only a3px yellow dot by default, without labels, shadows, or history circles", async () => {
    renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing={false} players={[]} balls={balls} />);
    await screen.findByText(/Ball observed/);
    expect(arc).toHaveBeenLastCalledWith(balls[0].x, balls[0].y, 3, 0, Math.PI * 2);
    expect(ellipse).not.toHaveBeenCalled();
    expect(fillRect).not.toHaveBeenCalled();
    expect(fillText).not.toHaveBeenCalled();
    expect(lineTo).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Overlay options"));
    expect(screen.getByRole("checkbox", { name: "Short trail" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Uncertainty" })).not.toBeChecked();
  });

  it("makes the short trail a plain line and shows spread only when requested", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const sequence = [880_000, 920_000, 960_000, 1_000_000].map((time) => ball("observed", time, "one-segment", false));
    renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing={false} players={[]} balls={sequence} />);
    await screen.findByText(/Ball observed/);
    fireEvent.click(screen.getByText("Overlay options"));
    arc.mockClear();
    lineTo.mockClear();
    fireEvent.click(screen.getByRole("checkbox", { name: "Short trail" }));
    expect(lineTo).toHaveBeenCalledTimes(3);
    expect(arc).toHaveBeenCalledTimes(1);
    expect(fillText).not.toHaveBeenCalled();
    expect(ellipse).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Uncertainty" }));
    expect(ellipse).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["invisible", { visible: false }, /Ball not visible/],
    ["null position", { x: null }, /Ball not visible/],
    ["ambiguous", { ambiguous: true }, /Ball uncertainty/],
    ["low confidence", { probability: 0.3 }, /Ball low confidence/],
    ["estimated", { evidence: "interpolated", sourceTimestampUs: null, sourceFrameIndex: null }, /Ball reconstructed/],
  ] as const)("keeps %s evidence in status without drawing a confident dot", async (_name, overrides, status) => {
    const candidate = { ...balls[0], ...overrides } as BallObservation;
    expect(isConfidentBall(candidate)).toBe(false);
    renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing={false} players={[]} balls={[candidate]} />);
    await screen.findByText(status);
    expect(arc).not.toHaveBeenCalled();
    expect(ellipse).not.toHaveBeenCalled();
  });

  it("updates old auto-saved defaults but preserves explicit choices in versioned storage", async () => {
    sessionStorage.setItem("mosaic:overlay:match-1", JSON.stringify({ playerA: true, playerB: true, pose: false, ball: false, trajectory: true, uncertainty: true }));
    const first = renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing={false} players={[player]} balls={balls} />);
    await screen.findByText(/Player A observed/);
    fireEvent.click(screen.getByText("Overlay options"));
    expect(screen.getByRole("checkbox", { name: "Skeleton" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Ball" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Uncertainty" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Short trail" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "Boxes" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Skeleton" }));
    first.unmount();
    renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing={false} players={[player]} balls={balls} />);
    await screen.findByText(/Player A observed/);
    fireEvent.click(screen.getByText("Overlay options"));
    expect(screen.getByRole("checkbox", { name: "Boxes" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Skeleton" })).not.toBeChecked();
    expect(JSON.parse(sessionStorage.getItem("mosaic:overlay:v2:match-1") ?? "{}")).toMatchObject({ version: 2, overrides: { ball: false, boxes: true, pose: false } });
  });

  it("follows presented source frames during paused seeks and reduced motion, then cleans up", async () => {
    const video = document.createElement("video");
    video.currentTime = 1;
    let callback: VideoFrameRequestCallback | undefined;
    const requestFrame = vi.fn((next: VideoFrameRequestCallback) => { callback = next; return 7; });
    const cancelFrame = vi.fn();
    Object.defineProperty(video, "requestVideoFrameCallback", { value: requestFrame });
    Object.defineProperty(video, "cancelVideoFrameCallback", { value: cancelFrame });
    const nextBall = ball("observed", 1_080_000, "segment-c", false);
    const view = renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing={false} videoRef={{ current: video }} players={[player]} balls={[...balls, nextBall]} />);
    await screen.findByText(/Ball observed/);
    arc.mockClear();
    lineTo.mockClear();
    fireEvent.seeking(video);
    expect(screen.getByText(/Ball unavailable at this frame/)).toBeInTheDocument();
    expect(arc).not.toHaveBeenCalled();
    act(() => callback?.(0, { mediaTime: 1.033333 } as VideoFrameCallbackMetadata));
    expect(screen.getByText(/Ball uncertainty.*multiple candidates/)).toBeInTheDocument();
    expect(arc).not.toHaveBeenCalled();
    expect(lineTo).not.toHaveBeenCalled();
    act(() => callback?.(0, { mediaTime: 1.066667 } as VideoFrameCallbackMetadata));
    expect(arc).toHaveBeenLastCalledWith(nextBall.x, nextBall.y, 3, 0, Math.PI * 2);
    expect(requestFrame).toHaveBeenCalledTimes(3);
    view.unmount();
    expect(cancelFrame).toHaveBeenCalledWith(7);
  });

  it("stops fallback animation on cleanup and avoids it for reduced motion", () => {
    const requestFrame = vi.fn(() => 42);
    const cancelFrame = vi.fn();
    vi.stubGlobal("requestAnimationFrame", requestFrame);
    vi.stubGlobal("cancelAnimationFrame", cancelFrame);
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const videoRef = { current: document.createElement("video") };
    const first = renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing videoRef={videoRef} players={[player]} balls={balls} />);
    expect(requestFrame).toHaveBeenCalled();
    first.unmount();
    expect(cancelFrame).toHaveBeenCalledWith(42);
    requestFrame.mockClear();
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    renderApp(<VideoOverlay matchId="match-2" currentTimeUs={1_000_000} playing videoRef={videoRef} players={[player]} balls={balls} />);
    expect(requestFrame).not.toHaveBeenCalled();
  });

  it("cancels presented-frame work when the overlay leaves the viewport", () => {
    let observerCallback: IntersectionObserverCallback | undefined;
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) { observerCallback = callback; }
      observe() {} disconnect() {}
    });
    const video = document.createElement("video");
    const requestFrame = vi.fn(() => 12);
    const cancelFrame = vi.fn();
    Object.defineProperty(video, "requestVideoFrameCallback", { value: requestFrame });
    Object.defineProperty(video, "cancelVideoFrameCallback", { value: cancelFrame });
    renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing videoRef={{ current: video }} players={[]} balls={balls} />);
    expect(requestFrame).toHaveBeenCalledOnce();
    act(() => observerCallback?.([{ isIntersecting: false } as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(cancelFrame).toHaveBeenCalledWith(12);
  });

  it("keeps source geometry and the legend available when ball observations are absent", async () => {
    renderApp(<VideoOverlay matchId="match-1" currentTimeUs={1_000_000} playing={false} players={[player]} balls={[]} sourceWidth={1280} sourceHeight={720} />);
    await screen.findByText(/Player A observed.*Ball unavailable/);
    expect(screen.getByLabelText("Overlay legend")).toHaveTextContent("Player A");
    fireEvent.click(screen.getByText("Overlay options"));
    expect(screen.getByText(/1280 × 720 source/)).toBeVisible();
  });
});
