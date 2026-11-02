// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { jsonResponse } from "../../test-utils";
import { usePlaybackTimeline } from "./playback-data";
import type { PlaybackTimeline } from "./playback-model";

const frameMap = { startUs: 0, endUs: 20_000_000, items: [{ proxyTimestampUs: 1_000_000, sourceTimestampUs: 1_020_000, sourceFrameIndex: 25 }] };
const timeline: PlaybackTimeline = {
  reportRevision: 2, predictionRevision: 2, calibrationRevision: 1, calibrationAvailable: true, calibrationReason: null,
  startUs: 0, endUs: 120_000_000, durationUs: 10_000_000, ballSpeedMethod: "court_scaled_image_speed",
  players: [{ playerId: "A", baselineDistanceM: 0, baselineTrackedSeconds: 0 }, { playerId: "B", baselineDistanceM: null, baselineTrackedSeconds: 0 }],
  playerSamples: [{ playerId: "A", timestampUs: 1_020_000, proxyTimestampUs: 1_000_000, proxyEndTimestampUs: 1_033_333, sourceFrameIndex: 25, position: [1, 2], cumulativeDistanceM: 2, trackedSeconds: .2, positionReason: null }],
  ballSpeeds: [], contacts: [], landingCount: 0, landingReason: null, limitations: [],
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function renderPlayback(timeUs = 1_000_000) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return renderHook(({ currentTimeUs }) => usePlaybackTimeline("match", 2, currentTimeUs, 1), { wrapper, initialProps: { currentTimeUs: timeUs } });
}

it("stops loading when the fetched frame map confirms an interior tracking gap", async () => {
  let resolveMap!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { resolveMap = resolve; })));
  const { result } = renderPlayback(1_500_000);
  expect(result.current.loading).toBe(true);
  await act(async () => { resolveMap(jsonResponse(frameMap)); });
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.snapshot).toBeNull();
  expect(result.current.data).toBeNull();
  expect(result.current.error).toBe(false);
});

it("keeps loading while mapped tracking data is pending, then exposes the current position", async () => {
  let resolveTimeline!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("frame-map")
    ? Promise.resolve(jsonResponse(frameMap))
    : new Promise<Response>((resolve) => { resolveTimeline = resolve; })));
  const { result } = renderPlayback();
  await waitFor(() => expect(resolveTimeline).toBeDefined());
  expect(result.current.loading).toBe(true);
  expect(result.current.snapshot).toBeNull();
  await act(async () => { resolveTimeline(jsonResponse(timeline)); });
  await waitFor(() => expect(result.current.snapshot?.players[0].position).toEqual([1, 2]));
  expect(result.current.loading).toBe(false);
});

it("does not display cached tracking data or a loading state inside an unmapped gap", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => jsonResponse(url.includes("frame-map") ? frameMap : timeline)));
  const { result, rerender } = renderPlayback();
  await waitFor(() => expect(result.current.snapshot?.players[0].position).toEqual([1, 2]));
  rerender({ currentTimeUs: 1_500_000 });
  expect(result.current.snapshot).toBeNull();
  expect(result.current.data).toBeNull();
  expect(result.current.loading).toBe(false);
});
