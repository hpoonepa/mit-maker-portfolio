// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MatchSetup, recommendedProfile } from "./MatchSetup";
import { jsonResponse, renderApp } from "../../test-utils";

const emptyPlayingArea = { revision: 0, sourceSha256: "a".repeat(64), frameSize: { width: 1920, height: 1080 }, points: null, purpose: "player_detection_only" };

const points = [
  { label: "front-left", image: { x: 240, y: 160 }, court: { xM: 0, yM: 0 } },
  { label: "front-right", image: { x: 1680, y: 160 }, court: { xM: 6.4, yM: 0 } },
  { label: "back-left", image: { x: 360, y: 980 }, court: { xM: 0, yM: 9.75 } },
  { label: "back-right", image: { x: 1560, y: 980 }, court: { xM: 6.4, yM: 9.75 } },
];

const calibration = {
  revision: 3,
  proxyId: "proxy-1",
  frameSize: { width: 1920, height: 1080 },
  keypoints: points,
  result: {
    calibrated: true,
    capabilities: { imageSpace: true, floorPosition: true, movementDistance: true, speed: false },
    conditionNumber: 12,
    confidence: 0.94,
    courtToImage: null,
    imageToCourt: null,
    inlierMask: [true, true, true, true],
    maxErrorPx: 4.2,
    parameterCovariance: null,
    residualsPx: [1, 2, 3, 4],
    rmsErrorPx: 2.7,
    warnings: ["speed_requires_timestamp_map"],
  },
};

const detail = {
  id: "match-1",
  title: "League night",
  metadata: { playerOne: "Mina", playerTwo: "Inez" },
  assets: [{ id: "proxy-1", kind: "proxy", byteSize: 500, durationUs: 180000000, timestampIndexAvailable: false }],
  updatedAt: "2026-08-25T12:00:00Z",
  version: 2,
  preparationState: "prepared",
  quality: { availability: "unavailable", warnings: [] },
  latestJob: null,
  latestReport: null,
  calibrationRevision: 3,
  modelQuality: [],
};
const appleSiliconHealth = {
  status: "degraded",
  version: "1.0.0",
  ffmpeg: { status: "ready" },
  worker: {
    status: "ready",
    architecture: "arm64",
    nativeAppleSilicon: true,
    mpsAvailable: true,
  },
  models: { status: "ready", assets: [] },
};


function routeSetup() {
  Object.defineProperty(window.navigator, "platform", { configurable: true, value: "MacIntel" });
  Object.defineProperty(window.navigator, "userAgent", { configurable: true, value: "x86_64" });
  return renderApp(
    <Routes>
      <Route path="/matches/:matchId/setup" element={<MatchSetup />} />
      <Route path="/matches/:matchId/processing" element={<h1>Processing destination</h1>} />
    </Routes>,
    "/matches/match-1/setup",
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("match setup", () => {
  it.each(["original", "inverted"] as const)("starts %s tracking from a saved playing area when automatic calibration refuses", async (ballInputMode) => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/player-roi")) return Promise.resolve(jsonResponse({ ...emptyPlayingArea, revision: 1, points: [{ x: 374, y: 384 }, { x: 902, y: 384 }, { x: 1075, y: 719 }, { x: 202, y: 719 }] }));
      if (url.endsWith("/calibration/propose")) return Promise.resolve(jsonResponse({ code: "unreliable_proposal", message: "No reliable court", details: null, requestId: "test" }, 422));
      if (url.endsWith("/jobs") && init?.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({ profile: "maximum", ballInputMode });
        return Promise.resolve(jsonResponse({ id: "job-1", matchId: "match-1", profile: "maximum", progress: null, requestedState: null, stage: null, stageState: null, state: "queued", createdAt: "2026-08-25T12:00:00Z", updatedAt: "2026-08-25T12:00:00Z", heartbeatAt: null, version: 1, currentRangeStartUs: null, currentRangeEndUs: null, failureCode: null }, 201));
      }
      if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
      if (url === "/api/v1/health") return Promise.resolve(jsonResponse(appleSiliconHealth));
      return Promise.resolve(jsonResponse({ ...detail, calibrationRevision: null }));
    }));
    routeSetup();
    await screen.findByText("Playing area saved");
    expect(screen.getByRole("radio", { name: "Standard" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Dark ball on light court" })).not.toBeChecked();
    if (ballInputMode === "inverted") fireEvent.click(screen.getByRole("radio", { name: "Dark ball on light court" }));
    fireEvent.click(screen.getByText("Court calibration (optional)"));
    const video = screen.getByLabelText("Match calibration video");
    Object.defineProperty(video, "videoWidth", { configurable: true, value: 1920 });
    Object.defineProperty(video, "videoHeight", { configurable: true, value: 1080 });
    fireEvent.loadedMetadata(video);
    fireEvent.click(screen.getByRole("button", { name: "Propose at current frame" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No reliable proposal");
    fireEvent.click(screen.getByRole("button", { name: "Start tracking" }));
    expect(await screen.findByRole("heading", { name: "Processing destination" })).toBeInTheDocument();
    expect(calls.some((call) => call.startsWith("PUT ") && call.endsWith("/calibration"))).toBe(false);
  });

  it("recommends Maximum on arm64 and explains unavailable speed without hiding other capabilities", async () => {
    expect(recommendedProfile("MacIntel", "arm64")).toBe("maximum");
    expect(recommendedProfile("MacIntel", "x86_64")).toBe("balanced");
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/player-roi")) return Promise.resolve(jsonResponse(emptyPlayingArea));
        if (url.endsWith("/calibration")) return Promise.resolve(jsonResponse(calibration));
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(appleSiliconHealth));
        if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
        return Promise.resolve(jsonResponse(detail));
      }),
    );
    routeSetup();

    expect(await screen.findByRole("heading", { name: "Calibrate the court" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Maximum/ })).toBeChecked();
    expect(screen.getByLabelText("Court quality")).toHaveTextContent("Ready to analyse");
    expect(screen.getByLabelText("Court quality")).toHaveTextContent("94% confidence");
    expect(screen.getByText("RMS 2.7 px")).toBeInTheDocument();
    expect(screen.getByText("4 of 4 inliers")).toBeInTheDocument();
    expect(screen.getByText(/Speed unavailable because this proxy has no verified timestamp map/)).toBeInTheDocument();
    expect(screen.getByText("Floor position available")).toBeInTheDocument();
    const stage = screen.getByLabelText("Match calibration video").closest(".video-stage") as HTMLElement;
    const requestFullscreen = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(stage, "requestFullscreen", { configurable: true, value: requestFullscreen });
    fireEvent.click(screen.getByRole("button", { name: "Fullscreen court editor" }));
    expect(requestFullscreen).toHaveBeenCalledOnce();
  });

  it("keeps first-time calibration actionable from video proposal through revision-zero save", async () => {
    let savedBody: unknown = null;
    let calibrationGets = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/player-roi")) return Promise.resolve(jsonResponse(emptyPlayingArea));
        if (url.endsWith("/calibration/propose")) {
          return Promise.resolve(jsonResponse({
            confidence: 0.91,
            intersectionCount: 4,
            lineCount: 6,
            visibleSurfaces: ["floor"],
            warnings: [],
            keypoints: points,
          }));
        }
        if (url.endsWith("/calibration") && init?.method === "PUT") {
          savedBody = JSON.parse(String(init.body));
          return Promise.resolve(jsonResponse(calibration));
        }
        if (url.endsWith("/calibration")) {
          calibrationGets += 1;
          return Promise.resolve(jsonResponse({
            code: "calibration_not_found",
            message: "match has no saved calibration",
            details: null,
            requestId: "missing",
          }, 404));
        }
        if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(appleSiliconHealth));
        return Promise.resolve(jsonResponse({ ...detail, calibrationRevision: null }));
      }),
    );
    routeSetup();

    fireEvent.click(await screen.findByText("Court calibration (optional)"));
    const video = await screen.findByLabelText("Match calibration video");
    expect(calibrationGets).toBe(0);
    Object.defineProperty(video, "videoWidth", { configurable: true, value: 1920 });
    Object.defineProperty(video, "videoHeight", { configurable: true, value: 1080 });
    Object.defineProperty(video, "currentTime", { configurable: true, value: 12 });
    fireEvent.loadedMetadata(video);
    fireEvent.click(screen.getByRole("button", { name: "Propose at current frame" }));
    expect(await screen.findByRole("button", { name: "Move front-left calibration point" })).toBeInTheDocument();
    const editorVideo = screen.getByLabelText("Match calibration video") as HTMLVideoElement;
    Object.defineProperty(editorVideo, "videoWidth", { configurable: true, value: 1920 });
    Object.defineProperty(editorVideo, "videoHeight", { configurable: true, value: 1080 });
    fireEvent.loadedMetadata(editorVideo);
    expect(editorVideo.currentTime).toBe(12);
    fireEvent.click(screen.getByRole("button", { name: "Save court" }));
    await waitFor(() => expect(savedBody).toEqual(expect.objectContaining({
      expectedRevision: 0,
      frameSize: { width: 1920, height: 1080 },
    })));
  });

  it("keeps local edits on revision conflict and offers an explicit reload", async () => {
    let saveAttempted = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/player-roi")) return Promise.resolve(jsonResponse(emptyPlayingArea));
        if (url.endsWith("/calibration") && init?.method === "PUT") {
          saveAttempted = true;
          return Promise.resolve(
            jsonResponse(
              { code: "calibration_revision_conflict", message: "conflict", details: null, requestId: "conflict" },
              409,
            ),
          );
        }
        if (url.endsWith("/calibration")) return Promise.resolve(jsonResponse(calibration));
        if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(appleSiliconHealth));
        return Promise.resolve(jsonResponse(detail));
      }),
    );
    routeSetup();
    await screen.findByRole("heading", { name: "Calibrate the court" });
    fireEvent.keyDown(screen.getByRole("button", { name: "Move front-left calibration point" }), {
      key: "ArrowRight",
    });
    fireEvent.click(screen.getByRole("button", { name: "Save court" }));

    await waitFor(() => expect(saveAttempted).toBe(true));
    expect(await screen.findByText("A newer calibration was saved")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload saved calibration" })).toBeEnabled();
    expect(screen.getByText(/Unsaved manual edits retained/)).toBeInTheDocument();
  });

  it.each([
    ["original", "maximum", "maximum"],
    ["inverted", "maximum", "maximum"],
    ["inverted", "fast", "balanced"],
  ] as const)("starts %s analysis from %s with supported profile %s", async (ballInputMode, initialProfile, expectedProfile) => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/player-roi")) return Promise.resolve(jsonResponse(emptyPlayingArea));
        if (url.endsWith("/jobs") && init?.method === "POST") {
          expect(JSON.parse(String(init.body))).toEqual({ profile: expectedProfile, ballInputMode });
          return Promise.resolve(
            jsonResponse({
              id: "job-1",
              matchId: "match-1",
              profile: "maximum",
              progress: null,
              requestedState: null,
              stage: null,
              stageState: null,
              state: "queued",
              createdAt: "2026-08-25T12:00:00Z",
              updatedAt: "2026-08-25T12:00:00Z",
              heartbeatAt: null,
              version: 1,
              currentRangeStartUs: null,
              currentRangeEndUs: null,
              failureCode: null,
            }, 201),
          );
        }
        if (url.endsWith("/calibration")) return Promise.resolve(jsonResponse(calibration));
        if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(appleSiliconHealth));
        return Promise.resolve(jsonResponse(detail));
      }),
    );
    routeSetup();
    const start = await screen.findByRole("button", { name: "Start analysis" });
    expect(screen.getByRole("radio", { name: "Standard" })).toBeChecked();
    const fast = screen.getByRole("radio", { name: /^Fast/ });
    expect(fast).toBeEnabled();
    if (initialProfile === "fast") fireEvent.click(fast);
    if (ballInputMode === "inverted") {
      fireEvent.click(screen.getByRole("radio", { name: "Dark ball on light court" }));
      expect(fast).toBeDisabled();
      expect(screen.getByText("Dark-ball tracking requires Balanced or Maximum.")).toBeInTheDocument();
      if (initialProfile === "fast") expect(screen.getByRole("radio", { name: /^Balanced/ })).toBeChecked();
    }
    fireEvent.click(start);
    expect(await screen.findByRole("heading", { name: "Processing destination" })).toBeInTheDocument();
  });
  it("distinguishes missing timestamp evidence from calibration-limited speed", async () => {
    const timestampedDetail = {
      ...detail,
      assets: [{ ...detail.assets[0], timestampIndexAvailable: true }],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/player-roi")) return Promise.resolve(jsonResponse(emptyPlayingArea));
        if (url.endsWith("/calibration")) return Promise.resolve(jsonResponse(calibration));
        if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(appleSiliconHealth));
        return Promise.resolve(jsonResponse(timestampedDetail));
      }),
    );
    routeSetup();
    expect(await screen.findByText(/Speed unavailable because calibration did not validate/)).toBeInTheDocument();
  });

  it("retains the automatic proposal independently across a saved cache update", async () => {
    const proposedPoints = points.map((point, index) => index === 0
      ? { ...point, image: { x: 360, y: point.image.y } }
      : point);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/player-roi")) return Promise.resolve(jsonResponse(emptyPlayingArea));
        if (url.endsWith("/calibration/propose")) {
          return Promise.resolve(jsonResponse({
            confidence: 0.9,
            intersectionCount: 4,
            lineCount: 6,
            visibleSurfaces: ["floor"],
            warnings: [],
            keypoints: proposedPoints,
          }));
        }
        if (url.endsWith("/calibration") && init?.method === "PUT") {
          return Promise.resolve(jsonResponse(calibration));
        }
        if (url.endsWith("/calibration")) return Promise.resolve(jsonResponse(calibration));
        if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(appleSiliconHealth));
        return Promise.resolve(jsonResponse(detail));
      }),
    );
    routeSetup();
    await screen.findByRole("heading", { name: "Calibrate the court" });
    fireEvent.click(screen.getByRole("button", { name: "Propose at current frame" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save court" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Save court" }));
    await waitFor(() => {
      const save = screen.getByRole("button", { name: "Save court" });
      expect(save).toHaveTextContent("Save court");
      expect(save).toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Reset to automatic proposal" }));
    expect(screen.getByRole("button", { name: "Move front-left calibration point" }).querySelector(".calibration-handle")).toHaveAttribute("cx", "360");
  });

  it("makes unknown model readiness finite and prevents starting", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/player-roi")) return Promise.resolve(jsonResponse(emptyPlayingArea));
        if (url === "/api/v1/models") return Promise.reject(new Error("offline"));
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(appleSiliconHealth));
        if (url.endsWith("/calibration")) return Promise.resolve(jsonResponse(calibration));
        return Promise.resolve(jsonResponse(detail));
      }),
    );
    routeSetup();
    expect(await screen.findByRole("heading", { name: "Model readiness unavailable" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry model readiness" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Start analysis" })).toBeDisabled();
  });

});
