// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProcessingView } from "./ProcessingView";
import { jsonResponse, renderApp } from "../../test-utils";

class FakeEventSource extends EventTarget {
  static current: FakeEventSource | null = null;
  readonly url: string;
  closed = false;

  constructor(url: string | URL) {
    super();
    this.url = String(url);
    FakeEventSource.current = this;
  }

  close() {
    this.closed = true;
  }

  snapshot(job: unknown) {
    this.dispatchEvent(
      new MessageEvent("job.snapshot", { data: JSON.stringify({ eventVersion: 1, job }) }),
    );
  }
}

const runningJob = {
  id: "job-1",
  matchId: "match-1",
  profile: "maximum",
  progress: { completedChunks: 5, plannedChunks: 10, fraction: 0.5 },
  requestedState: null,
  stage: "ball",
  stageState: "running",
  state: "running",
  createdAt: "2026-08-25T12:00:00Z",
  updatedAt: "2026-08-25T12:05:00Z",
  heartbeatAt: "2026-08-25T12:05:00Z",
  version: 3,
  currentRangeStartUs: 12_000_000,
  currentRangeEndUs: 18_000_000,
  failureCode: null,
};

function matchWith(job: unknown, reportRevision: number | null = null, warnings: string[] = []) {
  return {
    id: "match-1",
    title: "League night",
    metadata: { playerOne: "Mina", playerTwo: "Inez" },
    assets: [{ id: "proxy-1", kind: "proxy", byteSize: 500, durationUs: 180000000, timestampIndexAvailable: true }],
    updatedAt: "2026-08-25T12:00:00Z",
    version: 2,
    preparationState: "prepared",
    quality: { availability: reportRevision === null ? "partial" : "available", warnings },
    latestJob: job,
    latestReport:
      reportRevision === null
        ? null
        : { revision: reportRevision, predictionRevision: 7, calibrationRevision: 3, createdAt: "2026-08-25T12:00:00Z", sectionHashes: {} },
    calibrationRevision: 3,
    modelQuality: [],
  };
}

function renderProcessing(detail: unknown, jobResponse: unknown = runningJob) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/matches/match-1") return Promise.resolve(jsonResponse(detail));
      if (url === "/api/v1/jobs/job-1") return Promise.resolve(jsonResponse(jobResponse));
      if (url.includes("/pause") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ ...runningJob, version: 4, state: "paused", stageState: null }));
      }
      if (url.includes("/resume") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ ...runningJob, version: 5 }));
      }
      if (url.includes("/cancel") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ ...runningJob, version: 6, state: "cancelled", stageState: null }));
      }
      if (url.includes("/retry") && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          ...runningJob,
          version: 5,
          state: "queued",
          stage: null,
          stageState: null,
          failureCode: null,
        }));
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
  return renderApp(
    <Routes>
      <Route path="/matches/:matchId/processing" element={<ProcessingView />} />
    </Routes>,
    "/matches/match-1/processing",
  );
}

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("confirm", vi.fn(() => true));
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  FakeEventSource.current = null;
});

describe("durable processing", () => {
  it("renders only derived progress, exact stages, stream snapshots, and state-valid controls", async () => {
    const view = renderProcessing(matchWith(runningJob, 2, ["low_ball_confidence"]));

    expect(await screen.findByRole("heading", { name: "Ball tracking" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Analysis progress" })).toHaveAttribute("aria-valuenow", "50");
    expect(screen.getByText("5 of 10 processing chunks complete")).toBeInTheDocument();
    expect(screen.getByLabelText("Processing overview")).toHaveTextContent("Preparation");
    expect(screen.getByLabelText("Processing overview")).toHaveTextContent("Read the play");
    expect(screen.getByLabelText("Processing overview")).toHaveTextContent("Build the journal");
    const details = screen.getByText("Stage information").closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(details).toHaveTextContent(`Job ${runningJob.id}`);
    expect(screen.queryByText(/ETA/i)).not.toBeInTheDocument();
    expect(screen.getByText("0:12–0:18 match time")).toBeInTheDocument();
    for (const stage of ["Prepare", "Calibration", "Players", "Ball", "Events", "Classification", "Report"]) {
      expect(screen.getByText(stage)).toBeInTheDocument();
    }
    expect(screen.getByText("low_ball_confidence")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open partial analysis" })).toHaveAttribute(
      "href",
      "/matches/match-1/analysis?revision=2",
    );
    expect(screen.getByRole("navigation", { name: "Match workflow" })).toBeInTheDocument();
    expect(screen.queryByTestId("courtline-marker")).not.toBeInTheDocument();

    FakeEventSource.current?.snapshot({ ...runningJob, version: 4, state: "paused", stageState: null });
    expect(await screen.findByRole("button", { name: "Resume analysis" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Resume analysis" }));
    expect(await screen.findByRole("button", { name: "Pause analysis" })).toBeEnabled();

    const source = FakeEventSource.current;
    view.unmount();
    expect(source?.closed).toBe(true);
  });

  it("ignores stale SSE after a mutation and refetches match evidence on a newer snapshot", async () => {
    const view = renderProcessing(matchWith(runningJob));
    await screen.findByRole("heading", { name: "Ball tracking" });
    view.client.setQueryData(["jobs", "job-1"], {
      ...runningJob,
      version: 5,
      state: "paused",
      stageState: null,
    });
    expect(await screen.findByRole("button", { name: "Resume analysis" })).toBeEnabled();
    const matchCallsBefore = vi.mocked(fetch).mock.calls.filter(([input]) => String(input) === "/api/v1/matches/match-1").length;

    FakeEventSource.current?.snapshot({ ...runningJob, version: 4 });
    expect(screen.getByRole("button", { name: "Resume analysis" })).toBeEnabled();
    FakeEventSource.current?.snapshot({ ...runningJob, version: 6, stage: "events" });
    expect(await screen.findByRole("heading", { name: "Detecting events" })).toBeInTheDocument();
    await waitFor(() => {
      const matchCallsAfter = vi.mocked(fetch).mock.calls.filter(([input]) => String(input) === "/api/v1/matches/match-1").length;
      expect(matchCallsAfter).toBeGreaterThan(matchCallsBefore);
    });
  });

  it("closes terminal streams and renders the persisted failure code with a next action", async () => {
    renderProcessing(matchWith(runningJob));
    await screen.findByRole("heading", { name: "Ball tracking" });
    const source = FakeEventSource.current;
    source?.snapshot({
      ...runningJob,
      version: 4,
      state: "failed",
      stageState: "failed",
      failureCode: "ball_model_failed",
    });
    expect(await screen.findByText("ball_model_failed")).toBeInTheDocument();
    expect(screen.getByText(/Check local model readiness/)).toBeInTheDocument();
    expect(source?.closed).toBe(true);
    source?.dispatchEvent(new Event("error"));
    expect(screen.queryByText("Live updates interrupted")).not.toBeInTheDocument();
  });

  it("renders a null-stage queued job as waiting rather than media preparation", async () => {
    const queued = {
      ...runningJob,
      state: "queued",
      stage: null,
      stageState: null,
      progress: null,
      currentRangeStartUs: null,
      currentRangeEndUs: null,
    };
    renderProcessing(matchWith(queued), queued);
    expect(await screen.findByRole("heading", { name: "Waiting for worker" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Preparing media" })).not.toBeInTheDocument();
  });
  it("distinguishes finalizing and withholds progress without a published chunk plan", async () => {
    const finalizing = {
      ...runningJob,
      stage: "report",
      progress: { completedChunks: 0, plannedChunks: 0, fraction: 0.9 },
    };
    renderProcessing(matchWith(finalizing), finalizing);
    const heading = await screen.findByRole("heading", { name: "Finalizing analysis" });
    expect(heading.closest("header")).toHaveAttribute("data-state", "finalizing");
    expect(screen.queryByRole("progressbar", { name: "Analysis progress" })).not.toBeInTheDocument();
    expect(screen.getByText(/No progress estimate is available yet/i)).toBeInTheDocument();
  });

  it("retries the same failed job, opens a new stream, and reaches analysis", async () => {
    renderProcessing(matchWith(runningJob));
    await screen.findByRole("heading", { name: "Ball tracking" });
    const failedSource = FakeEventSource.current;
    failedSource?.snapshot({
      ...runningJob,
      version: 4,
      state: "failed",
      stageState: "failed",
      failureCode: "worker_runtime_error",
    });
    fireEvent.click(await screen.findByRole("button", { name: "Retry analysis" }));

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v1/jobs/job-1/retry",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(await screen.findByRole("heading", { name: "Waiting for worker" })).toBeInTheDocument();
    await waitFor(() => expect(FakeEventSource.current).not.toBe(failedSource));
    const retriedSource = FakeEventSource.current;
    expect(retriedSource?.url).toBe("/api/v1/jobs/job-1/events");

    retriedSource?.snapshot({
      ...runningJob,
      version: 6,
      state: "completed",
      stage: "report",
      stageState: "completed",
      progress: { completedChunks: 10, plannedChunks: 10, fraction: 1 },
      failureCode: null,
    });
    expect(await screen.findByRole("link", { name: "View analysis" })).toHaveAttribute(
      "href",
      "/matches/match-1/analysis",
    );
  });

  it("makes interruption, cancellation, failure, retry, and completion finite and actionable", async () => {
    renderProcessing(matchWith(runningJob));
    await screen.findByRole("heading", { name: "Ball tracking" });
    FakeEventSource.current?.dispatchEvent(new Event("error"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Live updates interrupted");
    expect(screen.getByRole("button", { name: "Reload job snapshot" })).toBeEnabled();

    FakeEventSource.current?.snapshot({ ...runningJob, version: 4, state: "failed", stageState: "failed", failureCode: "processing_failed" });
    expect(await screen.findByRole("heading", { name: "Analysis stopped safely" })).toBeInTheDocument();
    expect(screen.getByText(/processing_failed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry analysis" })).toBeEnabled();

  });

  it("renders cancelled and completed snapshots as terminal actions", async () => {
    const cancelled = { ...runningJob, state: "cancelled", stageState: null, version: 4 };
    const cancelledView = renderProcessing(matchWith(cancelled), cancelled);
    expect(await screen.findByText("Analysis cancelled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry analysis" })).toBeEnabled();
    cancelledView.unmount();
    vi.unstubAllGlobals();
    FakeEventSource.current = null;
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("confirm", vi.fn(() => true));
    const completed = {
      ...runningJob,
      state: "completed",
      stage: "report",
      stageState: "completed",
      version: 4,
      progress: { completedChunks: 10, plannedChunks: 10, fraction: 1 },
    };
    renderProcessing(matchWith(completed, 2), completed);
    expect(await screen.findByRole("heading", { name: "Analysis complete" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "View analysis" })).toHaveAttribute(
      "href",
      "/matches/match-1/analysis",
    );
  });
});
