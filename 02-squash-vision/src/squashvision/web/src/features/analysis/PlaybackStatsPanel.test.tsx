// @vitest-environment jsdom
// Checks running measurements, court-map switches and exact marker seeking.
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "../../test-utils";
import { PlaybackStatsPanel } from "./PlaybackStatsPanel";
import { usePlaybackTimeline } from "./playback-data";
import { decodePlaybackTimeline, indexPlayback, playbackAt } from "./playback-model";
import type { PlaybackContact, PlaybackTimeline } from "./playback-model";
import type { ReviewShot } from "./shot-model";
import { automaticShots, mergeShots } from "./shot-model";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function contact(id: string, proxyTimestampUs: number, kind: PlaybackContact["kind"] = "floor"): PlaybackContact {
  return { id, kind, timestampUs: proxyTimestampUs + 20_000, proxyTimestampUs, sourceFrameIndex: 1, confidence: .7, hitter: kind === "racket" ? "A" : null, hitterConfidence: .8, shotHitter: kind === "front_wall" ? "B" : "A", shotContactId: kind === "racket" ? id : "prior-racket", shotHitterConfidence: .8, ballImagePosition: [200, 400], imageWidth: 1280, imageHeight: 720, playerPosition: kind === "racket" ? [1, 2] : null, floorPosition: kind === "floor" ? [3, 6] : null, wallImageFraction: kind === "front_wall" ? .75 : null, wallPosition: null, positionReason: null, provenance: "motion_impact_estimate", reviewRequired: true, timingUncertaintyUs: 40_000 };
}
function shot(id: string, timeUs: number, hitter: ReviewShot["hitter"] = "A", position: [number, number] = [3, 6]): ReviewShot {
  return {id,contactUs:timeUs-500_000,hitter,type:"drive",origin:"reviewed",confidence:.8,contactImage:null,playerPosition:[1,2],opponentPosition:null,wall:null,landing:{timeUs,image:null,position},notes:""};
}
function timeline(): PlaybackTimeline {
  return {
    reportRevision: 2, predictionRevision: 2, calibrationRevision: 1, calibrationAvailable: true, calibrationReason: null,
    startUs: 0, endUs: 10_000_000, durationUs: 10_000_000, ballSpeedMethod: "court_scaled_image_speed",
    players: [{ playerId: "A", baselineDistanceM: 1, baselineTrackedSeconds: .1 }, { playerId: "B", baselineDistanceM: null, baselineTrackedSeconds: 0 }],
    playerSamples: [
      { playerId: "A", timestampUs: 1_020_000, proxyTimestampUs: 1_000_000, proxyEndTimestampUs: 1_033_333, sourceFrameIndex: 25, position: [1, 2], cumulativeDistanceM: 2, trackedSeconds: .2, positionReason: null },
      { playerId: "A", timestampUs: 2_020_000, proxyTimestampUs: 2_000_000, proxyEndTimestampUs: 2_033_333, sourceFrameIndex: 50, position: [2, 3], cumulativeDistanceM: 3, trackedSeconds: .4, positionReason: null },
    ],
    ballSpeeds: [{ timestampUs: 1_020_000, intervalStartUs: 980_000, proxyTimestampUs: 1_000_000, proxyEndTimestampUs: 1_033_333, sourceFrameIndex: 25, speedMps: 10 }],
    contacts: [contact("floor-1", 1_000_000), contact("wall-1", 2_000_000, "front_wall"), contact("racket-1", 3_000_000, "racket")],
    landingCount: 1, landingReason: null, limitations: [],
  };
}

describe("synchronized playback stats", () => {
  it("shows only past cumulative distance, uses window baselines, and rolls back on rewind", () => {
    const index = indexPlayback(timeline());
    expect(playbackAt(index, 999_999).players[0].distanceM).toBe(1);
    expect(playbackAt(index, 1_000_000).players[0].distanceM).toBe(2);
    expect(playbackAt(index, 2_100_000).players[0].distanceM).toBe(3);
    expect(playbackAt(index, 1_000_000).players[0].distanceM).toBe(2);
    expect(playbackAt(index, 2_100_000).players[1].distanceM).toBeNull();
  });

  it("expires speed and feet exactly at the end of the displayed source frame", () => {
    const index = indexPlayback(timeline());
    expect(playbackAt(index, 999_999).speedMps).toBeNull();
    expect(playbackAt(index, 1_000_000).speedMps).toBe(10);
    expect(playbackAt(index, 1_033_332).players[0].position).toEqual([1, 2]);
    expect(playbackAt(index, 1_033_333).speedMps).toBeNull();
    expect(playbackAt(index, 1_033_333).players[0].position).toBeNull();
    expect(playbackAt(index, 1_033_333).players[0].distanceM).toBe(2);
  });

  it("hides future impacts, uses actual image coordinates, and removes the highlight after250ms", () => {
    const index = indexPlayback(timeline());
    expect(playbackAt(index, 999_999).contacts).toHaveLength(0);
    const at = playbackAt(index, 1_000_000);
    expect(at.contacts.map((c) => c.id)).toEqual(["floor-1"]);
    expect(at.impactMarker).toEqual({ imagePosition: [200, 400], sourceWidth: 1280, sourceHeight: 720, kind: "floor", timestampUs: 1_000_000 });
    expect(playbackAt(index, 1_250_000).impactMarker).toBeNull();
    expect(playbackAt(index, 0).contacts).toHaveLength(0);
  });

  it("never plots hitter feet as a floor landing", () => {
    const data = timeline();
    const index = indexPlayback(data);
    const seek = vi.fn();
    const shots = [shot("floor-1",1_000_000),{...shot("wall-only",2_000_000),landing:null,wall:{timeUs:2_000_000,image:null,position:[2,1] as [number,number]}}];
    const view = (time: number) => <PlaybackStatsPanel shots={shots} data={data} snapshot={playbackAt(index, time)} currentTimeUs={time} loading={false} error={false} onRetry={vi.fn()} onSeek={seek} />;
    const rendered = render(view(1_000_000));
    fireEvent.click(screen.getByRole("button",{name:"Floor bounces"}));
    const floor = screen.getByRole("button", { name: /^Estimated floor landing at/ });
    expect(floor.querySelector("circle:last-child")).toHaveAttribute("cx", "300");
    expect(floor.querySelector("circle:last-child")).toHaveAttribute("cy", "600");
    expect(floor).toHaveAccessibleName(/X 3.00 m · Y 6.00 m/);
    expect(floor.querySelector("title")).toHaveTextContent("X 3.00 m · Y 6.00 m");
    fireEvent.keyDown(floor, { key: "Enter" });
    expect(seek).toHaveBeenCalledWith(1_000_000);
    expect(screen.queryByRole("button", { name: /^Front wall at/ })).not.toBeInTheDocument();
    rendered.rerender(view(3_000_000));
    expect(document.querySelectorAll(".playback-stats__landing")).toHaveLength(1);
    expect(document.querySelector(".playback-stats__racket")).not.toBeInTheDocument();
    expect(document.querySelector(".playback-stats__player-dot")).not.toBeInTheDocument();
    expect(document.querySelector(".playback-stats__player-trail")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Front wall at/ })).not.toBeInTheDocument();
    rendered.rerender(view(0));
    expect(document.querySelectorAll(".playback-stats__landing")).toHaveLength(0);
    expect(screen.queryByText("No impacts yet")).not.toBeInTheDocument();
  });

  it("shows only assigned landings in two courts with accurate shot totals", () => {
    const data = timeline();
    data.contacts.push({ ...contact("floor-a2", 1_500_000), floorPosition: [2, 4] });
    data.contacts.push({ ...contact("floor-b", 2_500_000), shotHitter: "B", floorPosition: [4, 7] });
    data.contacts.push({ ...contact("unassigned-floor", 3_100_000), shotHitter: null, shotContactId: null, shotHitterConfidence: 0 });
    const seek = vi.fn();
    const shots=[shot("floor-1",1_000_000),shot("floor-a2",1_500_000,"A",[2,4]),shot("floor-b",2_500_000,"B",[4,7]),shot("unassigned-floor",3_100_000,null)];
    render(<PlaybackStatsPanel shots={shots} data={data} snapshot={playbackAt(indexPlayback(data), 3_100_000)} currentTimeUs={3_100_000} loading={false} error={false} onRetry={vi.fn()} onSeek={seek} />);
    fireEvent.click(screen.getByRole("button",{name:"Floor bounces"}));
    const a = screen.getByRole("region", { name: "Player A landings" });
    const b = screen.getByRole("region", { name: "Player B landings" });
    expect(within(a).getAllByRole("button", { name: /^Estimated floor landing at/ })).toHaveLength(2);
    const landingB = within(b).getByRole("button", { name: /^Estimated floor landing at/ });
    expect(landingB).toHaveAttribute("data-shot-id", "floor-b");
    expect(landingB.querySelector("circle:last-child")).toHaveAttribute("cx", "400");
    expect(landingB.querySelector("circle:last-child")).toHaveAttribute("cy", "700");
    expect(a.querySelectorAll('[data-shot-id="unassigned-floor"]')).toHaveLength(0);
    expect(b.querySelectorAll('[data-shot-id="unassigned-floor"]')).toHaveLength(0);
    fireEvent.keyDown(landingB, { key: " " });
    expect(seek).toHaveBeenCalledWith(2_500_000);
    fireEvent.click(landingB);
    expect(seek).toHaveBeenLastCalledWith(2_500_000);
    for (const marker of document.querySelectorAll(".playback-stats__landing circle:last-child")) expect(marker).toHaveAttribute("r", "16");
    expect(within(a).getByText("2 shots")).toBeInTheDocument();
    expect(within(b).getByText("1 shot")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText("Details")).not.toBeInTheDocument();
    expect(screen.queryByText("Estimated from video")).not.toBeInTheDocument();
    expect(document.querySelector(".playback-stats__activity")).not.toBeInTheDocument();
    expect(screen.getByTestId("live-distance-A")).toHaveTextContent("3.0m");
    expect(screen.getByTestId("live-ball-speed")).toHaveTextContent("—m/s");
  });

  it("plots the same corrected player, position and timing as the score, replacing rejected detections", () => {
    const data=timeline();
    data.contacts=[
      {...contact("r1",1_000_000,"racket"),hitter:"B"},
      {...contact("old-floor",2_000_000),shotContactId:"r1",shotHitter:"B",floorPosition:[4,6]},
      {...contact("r2",4_000_000,"racket"),hitter:"B"},
      {...contact("false-floor",5_000_000),shotContactId:"r2",shotHitter:"B"},
    ];
    const corrected={...shot("r1",2_100_000,"A",[.2,7.2]),contactUs:1_000_000};
    const noBounce={...shot("r2",5_000_000,"B"),contactUs:4_000_000,landing:null};
    const added=shot("missed-shot",7_000_000,"B",[6,2]);
    const shots=mergeShots(automaticShots(data),[corrected,noBounce,added]);
    const seek=vi.fn();
    const view=(time:number)=><PlaybackStatsPanel shots={shots} data={data} snapshot={playbackAt(indexPlayback(data),time)} currentTimeUs={time} loading={false} error={false} onRetry={vi.fn()} onSeek={seek}/>;
    const rendered=render(view(2_050_000));
    fireEvent.click(screen.getByRole("button",{name:"Floor bounces"}));
    expect(document.querySelectorAll(".playback-stats__landing")).toHaveLength(0);
    rendered.rerender(view(2_100_000));
    const a=screen.getByRole("region",{name:"Player A landings"});
    const marker=within(a).getByRole("button");
    expect(marker).toHaveAttribute("data-shot-id","r1");
    expect(marker.querySelector("circle:last-child")).toHaveAttribute("cx","20");
    expect(marker.querySelector("circle:last-child")).toHaveAttribute("cy","720");
    fireEvent.click(marker);
    expect(seek).toHaveBeenCalledWith(2_100_000);
    rendered.rerender(view(8_000_000));
    expect(document.querySelectorAll(".playback-stats__landing")).toHaveLength(2);
    expect(within(screen.getByRole("region",{name:"Player B landings"})).getByRole("button")).toHaveAttribute("data-shot-id","missed-shot");
    expect(document.querySelector('[data-shot-id="r2"]')).toBeNull();
    rendered.rerender(view(0));
    expect(document.querySelectorAll(".playback-stats__landing")).toHaveLength(0);
  });

  it("accounts for every shot on the front wall without fabricating equal floor-bounce totals", () => {
    const shots=[
      {...shot("a1",1_000_000,"A"),landing:null,wall:{timeUs:800_000,image:null,position:[.2,1] as [number,number]}},
      {...shot("b1",2_000_000,"B"),wall:{timeUs:1_800_000,image:null,position:[6,1.5] as [number,number]}},
      {...shot("a2",3_000_000,"A"),landing:null,wall:{timeUs:2_800_000,image:null,position:[2,3] as [number,number]}},
      {...shot("b2",4_000_000,"B"),wall:{timeUs:3_800_000,image:null,position:[4,2] as [number,number]}},
    ];
    const seek=vi.fn();
    const view=(time:number)=><PlaybackStatsPanel shots={shots} data={timeline()} snapshot={null} currentTimeUs={time} loading={false} error={false} onRetry={vi.fn()} onSeek={seek}/>;
    const rendered=render(view(4_000_000));
    expect(screen.getByRole("button",{name:"Front wall"})).toHaveAttribute("aria-pressed","true");
    expect(screen.getAllByText("2 shots")).toHaveLength(2);
    expect(document.querySelectorAll('.playback-stats__wall-impact')).toHaveLength(4);
    const marker=screen.getByRole("button",{name:/Front-wall impact.*Player A.*X 0.20/});
    expect(marker.querySelector("circle:last-child")).toHaveAttribute("cx","20");
    expect(Number(marker.querySelector("circle:last-child")!.getAttribute("cy"))).toBeCloseTo(357);
    fireEvent.click(marker);
    expect(seek).toHaveBeenCalledWith(800_000);
    fireEvent.click(screen.getByRole("button",{name:"Floor bounces"}));
    expect(screen.getAllByText("2 shots")).toHaveLength(2);
    expect(document.querySelector('[data-court-player="A"]')!.querySelectorAll('.playback-stats__landing')).toHaveLength(0);
    expect(document.querySelector('[data-court-player="B"]')!.querySelectorAll('.playback-stats__landing')).toHaveLength(2);
    expect(screen.getByText("0 of 2 shots plotted")).toBeInTheDocument();
    rendered.rerender(view(0));
    expect(screen.getAllByText("0 shots")).toHaveLength(2);
    expect(document.querySelectorAll('.playback-stats__landing')).toHaveLength(0);
  });

  it("rejects mixed speed methods, invalid intervals, and floor positions attached to racket hits", () => {
    const data = timeline();
    expect(decodePlaybackTimeline(data)).toEqual(data);
    expect(() => decodePlaybackTimeline({ ...data, ballSpeedMethod: "floor_projection" })).toThrow();
    expect(() => decodePlaybackTimeline({ ...data, ballSpeeds: [{ ...data.ballSpeeds[0], proxyEndTimestampUs: 1_000_000 }] })).toThrow();
    expect(() => decodePlaybackTimeline({ ...data, contacts: [{ ...data.contacts[2], floorPosition: [1, 2] }] })).toThrow();
    expect(() => decodePlaybackTimeline({ ...data, contacts: [{ ...data.contacts[0], shotHitter: "C" }] })).toThrow();
    expect(() => decodePlaybackTimeline({ ...data, contacts: [{ ...data.contacts[0], shotContactId: null }] })).toThrow();
  });

  it("queries the source-time window using exact proxy mapping rather than equating the clocks", async () => {
    const data = { ...timeline(), startUs: 90_000_000, endUs: 210_000_000, durationUs: 220_000_000 };
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      requests.push(url);
      return Promise.resolve(jsonResponse(url.includes("frame-map") ? { startUs: 0, endUs: 20_000_000, items: [{ proxyTimestampUs: 5_000_000, sourceTimestampUs: 125_000_000, sourceFrameIndex: 3125 }] } : data));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => usePlaybackTimeline("match", 2, 5_000_000, 1), { wrapper });
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());
    expect(requests.find((url) => url.includes("tracking-timeline"))).toContain("startUs=90000000&endUs=210000000");
  });
});
