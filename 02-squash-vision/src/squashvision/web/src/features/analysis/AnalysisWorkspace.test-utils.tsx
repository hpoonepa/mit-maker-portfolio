// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { jsonResponse } from "../../test-utils";
import { AnalysisWorkspace } from "./AnalysisWorkspace";
import { trackingStatsFixture } from "./tracking-stats.test-utils";

export const baseReport = report(4);
export const match = {
  id: "match-1", title: "League night", metadata: { playerOne: "Mina", playerTwo: "Inez" },
  assets: [{ id: "proxy-1", kind: "proxy", byteSize: 500, durationUs: 180_000_000, timestampIndexAvailable: true }],
  updatedAt: "2026-08-25T12:00:00Z", version: 2, preparationState: "prepared",
  quality: { availability: "available", warnings: [] },
  latestJob: { id: "job-1", matchId: "match-1", profile: "maximum", progress: { completedChunks: 10, plannedChunks: 10, fraction: 1 }, requestedState: null, stage: "report", stageState: "completed", state: "completed", createdAt: "2026-08-25T12:00:00Z", updatedAt: "2026-08-25T12:05:00Z", heartbeatAt: "2026-08-25T12:05:00Z", version: 4, currentRangeStartUs: null, currentRangeEndUs: null, failureCode: null },
  latestReport: { revision: 4, predictionRevision: 7, calibrationRevision: 3, createdAt: "2026-08-25T12:05:00Z", sectionHashes: {} },
  calibrationRevision: 3, modelQuality: [],
};

export const timeline = {
  predictionRevision: 7, nextCursor: null,
  items: [
    { id: "shot-1", kind: "shot", timestampUs: 12_250_000, evidenceIds: ["shot-1"], observationLinks: { ball: "ball-1" }, summary: { hitter: "near", shot_type: "drive", outcome: "winner", confidence: 0.9, source_timestamp_us: 12_255_000 } },
    { id: "error-1", kind: "error", timestampUs: 15_000_000, endUs: 15_200_000, evidenceIds: ["error-1"], observationLinks: {}, summary: { reviewRequired: true, reviewStatus: "pending", confidence: 0.3, issue: "outcome", probabilities: { error: 0.7, continuation: 0.3 }, reasons: ["late wall contact"], provenance: "observed", sourceTimestampUs: 15_005_000, invalidatedSections: ["overview", "shots", "errors", "head_to_head", "coaching", "review"], invalidatedStats: ["winner_count", "shot_outcomes"] } },
  ],
};

export function setupAnalysisTestEnvironment(): void {
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  vi.stubGlobal("IntersectionObserver", class { constructor(callback: IntersectionObserverCallback) { callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver); } observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } root = null; rootMargin = "0px"; thresholds = [0]; });
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ clearRect: vi.fn(), save: vi.fn(), restore: vi.fn(), scale: vi.fn(), translate: vi.fn(), beginPath: vi.fn(), rect: vi.fn(), ellipse: vi.fn(), arc: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(), fill: vi.fn(), fillText: vi.fn(), setLineDash: vi.fn() } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
}

export function teardownAnalysisTestEnvironment(): void {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  sessionStorage.clear();
}

export function renderWorkspace(revision?: number) {
  const path = revision === undefined ? "/matches/match-1/analysis" : `/matches/match-1/analysis?revision=${revision}`;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  const router = createMemoryRouter([{ path: "/matches/:matchId/analysis", element: <AnalysisWorkspace /> }], { initialEntries: [path] });
  return { client, router, ...render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>) };
}

export function installFetch(
  requests: Array<{ url: string; signal?: AbortSignal | null }>,
  correction?: () => Response | Promise<Response>,
  reviewResponse?: (url: string) => Response | Promise<Response>,
  revisionResponse?: (revision: number) => Response | Promise<Response>,
  conflictResponse?: () => Response | Promise<Response>,
  resolutionResponse?: (url: string, init?: RequestInit) => Response | Promise<Response>,
  historyResponse?: (url: string) => Response | Promise<Response>,
  timelineResponse?: (url: string) => Response | Promise<Response>,
  playerResponse?: (url: string) => Response | Promise<Response>,
  ballResponse?: (url: string) => Response | Promise<Response>,
) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    requests.push({ url, signal: init?.signal });
    if (url === "/api/v1/matches/match-1") return Promise.resolve(jsonResponse(match));
    if (url.includes("/media/frame-map?")) return Promise.resolve(jsonResponse({ startUs: queryNumber(url, "startUs"), endUs: queryNumber(url, "endUs"), items: [{ proxyTimestampUs: 0, sourceTimestampUs: 0, sourceFrameIndex: 0 }] }));
    if (url === "/api/v1/matches/match-1/reports/latest") return Promise.resolve(jsonResponse(baseReport));
    if (/\/reports\/\d+\/shot-review$/.test(url)) return Promise.resolve(jsonResponse({version:0,reportRevision:Number(url.split("/").at(-2)),shots:[],wallCalibration:null}));
    if (url === "/api/v1/matches/match-1/calibration") return Promise.resolve(jsonResponse(null));
    if (/\/reports\/\d+\/tracking-stats$/.test(url)) return Promise.resolve(jsonResponse(trackingStatsFixture({ reportRevision: Number(url.split("/").at(-2)) })));
    if (url.includes("/tracking-timeline?")) return Promise.resolve(jsonResponse({ reportRevision: Number(url.split("/").at(-2)), predictionRevision: 7, calibrationRevision: null, calibrationAvailable: false, calibrationReason: "No calibration", startUs: queryNumber(url, "startUs"), endUs: queryNumber(url, "endUs"), durationUs: 180_000_000, ballSpeedMethod: "court_scaled_image_speed", players: [{ playerId: "A", baselineDistanceM: null, baselineTrackedSeconds: 0 }, { playerId: "B", baselineDistanceM: null, baselineTrackedSeconds: 0 }], playerSamples: [], ballSpeeds: [], contacts: [], landingCount: 0, landingReason: null, limitations: [] }));
    if (url === "/api/v1/matches/match-1/reports" || url.startsWith("/api/v1/matches/match-1/reports?")) return Promise.resolve(historyResponse?.(url) ?? jsonResponse({ items: [summary(4), summary(3)], nextCursor: null }));
    if (/\/reports\/\d+$/.test(url)) { const revision = Number(url.split("/").pop()); return Promise.resolve(revisionResponse?.(revision) ?? jsonResponse(report(revision))); }
    if (url.includes("/timeline?")) {
      if (timelineResponse !== undefined) return Promise.resolve(timelineResponse(url));
      const revision = queryNumber(url, "revision");
      return Promise.resolve(jsonResponse(revision >= 5 ? { ...timeline, items: timeline.items.map((item) => item.id === "error-1" ? { ...item, summary: { ...item.summary, reviewStatus: "accepted" } } : item) } : timeline));
    }
    if (url.includes("/observations/players?")) return Promise.resolve(playerResponse?.(url) ?? jsonResponse({ artifact: artifact("players"), startUs: queryNumber(url, "startUs"), endUs: queryNumber(url, "endUs"), nextCursor: null, items: [] }));
    if (url.includes("/observations/ball?")) return Promise.resolve(ballResponse?.(url) ?? jsonResponse({ artifact: artifact("ball"), startUs: queryNumber(url, "startUs"), endUs: queryNumber(url, "endUs"), nextCursor: null, items: [] }));
    if (url.includes("/review-items?")) return Promise.resolve(reviewResponse?.(url) ?? jsonResponse(reviewPage(queryNumber(url, "revision"))));
    if (url.includes("/evidence/")) return Promise.resolve(jsonResponse({ id: "shot-off-window", kind: "shot", timestampUs: 90_000_000, endUs: null, evidenceIds: ["report-off-window"], observationLinks: null, summary: { shotKind: "drive", hitter: "near", outcome: "winner" } }));
    if (url.endsWith("/corrections") && init?.method === "POST") return Promise.resolve(correction?.() ?? jsonResponse(report(5)));
    if (url.endsWith("/exports") && init?.method === "POST") return Promise.resolve(jsonResponse({
      id: "export-1",
      matchId: "match-1",
      revision: 4,
      state: "completed",
      selection: { formats: ["html", "json", "csv"], evidenceIds: ["report-off-window"], evidenceDurationSeconds: 6, includeOriginal: true },
      relativePath: "exports/export-1.zip",
      byteSize: 2048,
      sha256: "a".repeat(64),
    }));
    if (url.includes("/correction-conflicts/") && url.endsWith("/resolve")) return Promise.resolve(resolutionResponse?.(url, init) ?? jsonResponse(report(6)));
    if (url.endsWith("/correction-conflicts")) return Promise.resolve(conflictResponse?.() ?? jsonResponse({ conflicts: [] }));
    throw new Error(`unexpected request: ${url}`);
  }));
}

export function artifact(kind: string) {
  return {
    availability: "available",
    jobId: "job-1",
    modelManifestIds: [`${kind}-model`],
    sourceManifestIds: [`${kind}-source`],
    stage: kind === "players" ? "players" : "ball",
    warnings: [],
  };
}

export function queryNumber(url: string, name: string): number {
  return Number(new URL(url, "http://local").searchParams.get(name));
}

export function summary(revision: number) {
  return { revision, predictionRevision: 7, calibrationRevision: 3, createdAt: new Date(Date.UTC(2026, 7, 25, 12, 0, revision)).toISOString(), sectionHashes: {} };
}

export function report(revision: number) {
  const payloads: Record<string, Record<string, unknown>> = {
    overview: { rally_count: 1, timed_rally_count: 1, shot_count: 1, winner_count: 1, reviewed_error_count: 0, active_duration_s: 8, rest_duration_s: null, work_rest_ratio: { available: false, reason: "no_rest_duration" }, average_rally_s: 8, longest_rally_s: 8, review_completion: { available: true, value: 0 }, evidence_quality: { available: true, value: 1 } },
    review: { candidate_count: 1, reviewed_count: 0, pending_ids: ["error-1"] },
  };
  const sections: Record<string, { schemaVersion: number; payload: Record<string, unknown>; evidenceIds: string[]; hash: string; dependencyHash: string }> = {};
  for (const name of ["overview", "shots", "rallies", "movement", "errors", "trajectory", "head_to_head", "coaching", "review"]) {
    sections[name] = { schemaVersion: 1, payload: payloads[name] ?? { availability: { available: false, reason: "insufficient_sample" } }, evidenceIds: name === "overview" ? ["report-off-window"] : [], hash: `${name}-${revision}`, dependencyHash: `${name}-dependency-${revision}` };
  }
  return { matchId: "match-1", revision, predictionRevision: 7, calibrationRevision: 3, sections };
}

export function reviewPage(reportRevision: number) {
  return {
    reportRevision,
    nextCursor: null,
    items: [{
      id: "error-1", targetType: "error_candidate", kind: "tracking", timestampUs: 15_000_000, endUs: 15_200_000,
      confidence: 0.3, issue: "outcome", provenance: "observed", probabilities: { error: 0.7, continuation: 0.3 },
      reasons: ["late wall contact"], evidenceIds: ["error-1"], evidenceStartTimestampUs: 14_950_000,
      evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455,
      invalidatedSections: ["overview", "shots", "errors", "head_to_head", "coaching", "review"],
      commandTargets: {
        accept: { targetType: "error_candidate", targetId: "error-1", sourceTimestampUs: 15_000_000, sourceEvidenceIds: ["error-1"], evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455 },
        reject: { targetType: "error_candidate", targetId: "error-1", sourceTimestampUs: 15_000_000, sourceEvidenceIds: ["error-1"], evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455 },
        change_outcome: { targetType: "shot", targetId: "shot-1", sourceTimestampUs: 12_255_000, sourceEvidenceIds: ["shot-1"], evidenceStartTimestampUs: 12_255_000, evidenceEndTimestampUs: 12_255_000, evidenceStartFrameIndex: 368, evidenceEndFrameIndex: 368 },
      },
      commandImpacts: {
        accept: { invalidatedSections: ["overview", "errors", "coaching", "review"], invalidatedStats: ["review_counts"] },
        reject: { invalidatedSections: ["overview", "errors", "coaching", "review"], invalidatedStats: ["review_counts"] },
        change_outcome: { invalidatedSections: ["overview", "shots", "errors", "head_to_head", "coaching", "review"], invalidatedStats: ["winner_count", "shot_outcomes"] },
      },
      reviewEntityType: "error_candidate", reviewEntityId: "error-1", reviewStatus: "pending",
      invalidatedStats: ["winner_count", "shot_outcomes"], summary: { sourceTimestampUs: 15_005_000 },
    }],
  };
}
