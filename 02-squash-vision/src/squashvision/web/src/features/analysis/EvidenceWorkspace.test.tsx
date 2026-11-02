// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { jsonResponse, renderApp } from "../../test-utils";
import { EvidenceWorkspace } from "./EvidenceWorkspace";
import { sourceFrameAt } from "./VideoOverlay";
import { indexPlayback, playbackAt, type PlaybackTimeline } from "./playback-model";

const durationUs = 24_966_667;
const frames = [{ proxyTimestampUs: 24_933_333, sourceTimestampUs: 24_960_000, sourceFrameIndex: 624 }];
const index = indexPlayback({
  reportRevision: 2, predictionRevision: 2, calibrationRevision: 1, calibrationAvailable: true, calibrationReason: null,
  startUs: 0, endUs: 120_000_000, durationUs: 25_000_000, ballSpeedMethod: "court_scaled_image_speed",
  players: [{ playerId: "A", baselineDistanceM: 0, baselineTrackedSeconds: 0 }, { playerId: "B", baselineDistanceM: null, baselineTrackedSeconds: 0 }],
  playerSamples: [{ playerId: "A", timestampUs: 24_960_000, proxyTimestampUs: 24_933_333, proxyEndTimestampUs: durationUs, sourceFrameIndex: 624, position: [2.4, 6.4], cumulativeDistanceM: 26.4, trackedSeconds: 14.4, positionReason: null }],
  ballSpeeds: [], contacts: [], landingCount: 0, landingReason: null, limitations: [],
} satisfies PlaybackTimeline);
const originalRequestFrame = Object.getOwnPropertyDescriptor(HTMLVideoElement.prototype, "requestVideoFrameCallback");
const originalCancelFrame = Object.getOwnPropertyDescriptor(HTMLVideoElement.prototype, "cancelVideoFrameCallback");

beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ startUs: 0, endUs: 40_000_000, items: frames })));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  for (const [name, descriptor] of [["requestVideoFrameCallback", originalRequestFrame], ["cancelVideoFrameCallback", originalCancelFrame]] as const) {
    if (descriptor) Object.defineProperty(HTMLVideoElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLVideoElement.prototype, name);
  }
});

function Harness() {
  const [time, setTime] = useState(24_933_333);
  const [playing, setPlaying] = useState(true);
  const videoRef = useRef<HTMLVideoElement>(null);
  const statusRef = useRef<HTMLOutputElement>(null);
  const frame = sourceFrameAt(frames, time, false);
  const position = frame ? playbackAt(index, time).players[0].position : null;
  return <EvidenceWorkspace
    matchId="match" reportRevision={2} evidenceLoading={false} currentTimeUs={time} durationUs={durationUs}
    playing={playing} playbackError={null} playbackRate={1} nearestStep={false} videoSize={{ width: 1280, height: 720 }}
    videoRef={videoRef} selectedStatusRef={statusRef} players={[]} balls={[]} events={[]}
    windowRange={{ startUs: 0, endUs: durationUs }} selectedEvent={null} selectedEventId={null}
    inspector={null} overlayControlsElement={null} setOverlayControlsElement={() => undefined}
    statsSidecar={<><output data-testid="clock">{time}</output><output data-testid="position">{position?.join(",") ?? "unavailable"}</output></>}
    onLoadedMetadata={() => undefined} onTimeUpdate={setTime} onRateChange={() => undefined} onPlayingChange={setPlaying}
    onPlaybackError={() => undefined} onTogglePlayback={() => undefined} onStepEvidence={() => undefined}
    onSeekTimeline={setTime} onScrub={setTime}
  />;
}

it.each(["timeUpdate", "ended"] as const)("retains the final mapped frame when %s reports the container's later end", (event) => {
  renderApp(<Harness />);
  const video = screen.getByLabelText("Match video evidence") as HTMLVideoElement;
  video.currentTime = 25.008;
  fireEvent[event](video);
  expect(screen.getByTestId("clock")).toHaveTextContent("24966666");
  expect(screen.getByTestId("position")).toHaveTextContent("2.4,6.4");
  if (event === "ended") expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
});

it("keeps frame callbacks inside the final half-open frame interval", () => {
  const callbacks = new Map<number, VideoFrameRequestCallback>();
  let nextId = 0;
  Object.defineProperty(HTMLVideoElement.prototype, "requestVideoFrameCallback", { configurable: true, value: (callback: VideoFrameRequestCallback) => { callbacks.set(++nextId, callback); return nextId; } });
  Object.defineProperty(HTMLVideoElement.prototype, "cancelVideoFrameCallback", { configurable: true, value: (id: number) => callbacks.delete(id) });
  renderApp(<Harness />);
  act(() => {
    for (const callback of [...callbacks.values()]) callback(0, { mediaTime: 24.966667 } as VideoFrameCallbackMetadata);
  });
  expect(screen.getByTestId("clock")).toHaveTextContent("24966666");
  expect(screen.getByTestId("position")).toHaveTextContent("2.4,6.4");
});

it("scrubs to the last valid video instant at the slider endpoint", () => {
  renderApp(<Harness />);
  fireEvent.change(screen.getByRole("slider", { name: "Match playback position" }), { target: { value: "24.966667" } });
  expect(screen.getByTestId("clock")).toHaveTextContent("24966666");
  expect(screen.getByTestId("position")).toHaveTextContent("2.4,6.4");
});

it("leaves an interior tracking gap unavailable instead of holding the final frame", () => {
  renderApp(<Harness />);
  const video = screen.getByLabelText("Match video evidence") as HTMLVideoElement;
  video.currentTime = 12;
  fireEvent.timeUpdate(video);
  expect(screen.getByTestId("clock")).toHaveTextContent("12000000");
  expect(screen.getByTestId("position")).toHaveTextContent("unavailable");
});
