// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MatchLibrary } from "./MatchLibrary";
import { jsonResponse, renderApp } from "../../test-utils";

const readyHealth = {
  status: "ready",
  version: "1.0.0",
  ffmpeg: { status: "ready" },
  worker: { status: "ready", architecture: "arm64", nativeAppleSilicon: true, mpsAvailable: true },
  models: { status: "ready", assets: [] },
};

const missingModel = {
  name: "ball",
  filename: "ball.pt",
  requestedRevision: "tracknet-v3",
  resolvedRevision: null,
  sha256: null,
  byteSize: 125000000,
  declaredLicense: "Apache-2.0",
  required: true,
  compatibilityVersion: 1,
  state: "missing",
  downloadedAt: null,
  errorCode: null,
  sourceLabel: "Hugging Face · linfeng302/RacketVision-Models",
};

function mockApi(matches: unknown, models: unknown[] = []) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/health") return Promise.resolve(jsonResponse(readyHealth));
      if (url === "/api/v1/models/ball/ensure" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ ...missingModel, state: "ready" }));
      }
      if (url === "/api/v1/models/pose/ensure" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          code: "model_download_failed",
          message: "model failed",
          details: null,
          requestId: "model-failure",
        }, 503));
      }
      if (url === "/api/v1/models") return Promise.resolve(jsonResponse(models));
      if (url.startsWith("/api/v1/matches")) {
        if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
        return Promise.resolve(jsonResponse(matches));
      }
      throw new Error(`unexpected request: ${url}`);
    }),
  );
}

function matchSummary(index: number) {
  return {
    id: `match-${index}`,
    title: `Match ${index}`,
    metadata: { playerOne: "A", playerTwo: "B", playedOn: "2026-08-25", score: null },
    updatedAt: "2026-08-25T12:00:00Z",
    version: 1,
    preparationState: "prepared",
    processing: { state: "not_started" },
    quality: { availability: "complete", warnings: [] },
    latestReport: null,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("match ledger", () => {
  it("turns an empty library into an actionable local ingest state", async () => {
    mockApi({ items: [], nextCursor: null }, [missingModel]);
    renderApp(<MatchLibrary />);

    expect(await screen.findByRole("heading", { name: "Start with a match video" })).toBeInTheDocument();
    expect(screen.getAllByText(/MP4, MOV, M4V, or WebM/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/stays on this device/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/3 hours/i).length).toBeGreaterThan(0);
    expect(screen.getByText("ball.pt")).toBeInTheDocument();
    expect(screen.getByText(/Apache-2.0/)).toBeInTheDocument();
    expect(screen.getByText("Hugging Face · linfeng302/RacketVision-Models")).toBeInTheDocument();
    const install = screen.getByRole("button", { name: "Install local models" });
    expect(install).toBeEnabled();
    fireEvent.click(install);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v1/models/ball/ensure",
      expect.objectContaining({ method: "POST" }),
    ));
  });
  it("opens populated libraries as one compact Matches workspace with a single import action", async () => {
    const running = {
      ...matchSummary(1),
      title: "League final",
      processing: {
        state: "running",
        jobId: "job-1",
        stage: "ball",
        profile: "maximum",
        updatedAt: "2026-08-25T12:00:00Z",
      },
    };
    mockApi({ items: [running], nextCursor: null });
    renderApp(<MatchLibrary />);

    expect(await screen.findByRole("heading", { name: "Matches" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Match dashboard" })).not.toBeInTheDocument();
    const ledger = screen.getByRole("region", { name: "Match library" });
    expect(await within(ledger).findByRole("listitem", { name: "League final match" })).toHaveAttribute("data-featured", "true");
    expect(screen.getAllByRole("link", { name: "Import video" })).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Dashboard status" })).not.toBeInTheDocument();
    const readiness = screen.getByText("System status").closest("details");
    expect(readiness).not.toHaveAttribute("open");
    expect(ledger.compareDocumentPosition(readiness as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("settles API failure with a retry instead of a permanent loader", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    renderApp(<MatchLibrary />);

    expect(await screen.findByText("Matches could not load")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry loading matches" })).toBeEnabled();
    expect(screen.queryByText(/Loading matches/)).not.toBeInTheDocument();
  });

  it.each(["inverted", undefined] as const)("waits for saved job settings and preserves %s ball contrast on reanalysis", async (ballInputMode) => {
    const summary = { ...matchSummary(1), processing: { state: "completed", profile: "maximum" } };
    const previousJob = {
      id: "job-1", matchId: summary.id, profile: "maximum", ballInputMode,
      progress: null, requestedState: null, stage: "report", stageState: "completed", state: "completed",
      createdAt: summary.updatedAt, updatedAt: summary.updatedAt, heartbeatAt: null, version: 1,
      currentRangeStartUs: null, currentRangeEndUs: null, failureCode: null,
    };
    const savedMatch = { ...summary, assets: [], latestJob: previousJob, calibrationRevision: null, modelQuality: [] };
    let resolveDetail!: () => void;
    const detailReady = new Promise<void>((resolve) => { resolveDetail = resolve; });
    const postedBodies: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/health") return Promise.resolve(jsonResponse(readyHealth));
      if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
      if (url === "/api/v1/matches?limit=100") return Promise.resolve(jsonResponse({ items: [summary], nextCursor: null }));
      if (url === `/api/v1/matches/${summary.id}`) return detailReady.then(() => jsonResponse(savedMatch));
      if (url === `/api/v1/matches/${summary.id}/reanalyze` && init?.method === "POST") {
        postedBodies.push(JSON.parse(String(init.body)));
        return Promise.resolve(jsonResponse({ ...previousJob, id: "job-2", state: "queued" }, 201));
      }
      throw new Error(`unexpected request: ${url}`);
    }));
    renderApp(<MatchLibrary />);
    const row = await screen.findByRole("listitem", { name: "Match 1 match" });
    fireEvent.click(within(row).getByText("More options"));
    const reanalyze = within(row).getByRole("button", { name: "Reanalyze" });
    fireEvent.click(reanalyze);
    await waitFor(() => expect(reanalyze).toBeDisabled());
    expect(postedBodies).toEqual([]);
    resolveDetail();
    await waitFor(() => expect(postedBodies).toEqual([{ profile: "maximum", ballInputMode: ballInputMode ?? "original" }]));
  });

  it("keeps failed matches visible with direct recovery and delete actions", async () => {
    const page = {
      nextCursor: null,
      items: [
        {
          id: "match-failed",
          title: "Club final",
          metadata: { playerOne: "Nadia", playerTwo: "Priya", playedOn: "2026-08-24", score: "2-3" },
          updatedAt: "2026-08-25T12:00:00Z",
          version: 4,
          preparationState: "prepared",
          processing: { state: "failed", jobId: "job-1", stage: "ball", profile: "maximum", updatedAt: "2026-08-25T12:00:00Z" },
          quality: { availability: "partial", warnings: ["ball_tracking_failed"] },
          latestReport: null,
        },
      ],
    };
    let deleted = false;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(readyHealth));
        if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
        if (url.startsWith("/api/v1/matches")) {
          if (init?.method === "DELETE") {
            deleted = true;
            return Promise.resolve(new Response(null, { status: 204 }));
          }
          return Promise.resolve(jsonResponse(deleted ? { items: [], nextCursor: null } : page));
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    vi.stubGlobal("confirm", vi.fn(() => true));
    renderApp(<MatchLibrary />);

    const row = await screen.findByRole("listitem", { name: /Club final/ });
    expect(screen.getByText("Import a match video").closest("details")).not.toHaveAttribute("open");
    const liveRegion = screen.getByRole("status");
    expect(liveRegion).toBeEmptyDOMElement();
    expect(within(row).getByText("Failed at ball")).toBeInTheDocument();
    expect(within(row).getByText("Ball tracking failed")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Resume" })).toHaveAttribute(
      "href",
      "/matches/match-failed/processing",
    );
    fireEvent.click(within(row).getByText("More options"));
    expect(within(row).getByRole("button", { name: "Reanalyze" })).toBeEnabled();
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Match deleted")).toBeInTheDocument();
    expect(liveRegion).toHaveTextContent("Match deleted");
    expect(liveRegion).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("listitem", { name: /Club final/ })).not.toBeInTheDocument());
  });
  it("refetches model and health truth even when one required ensure fails", async () => {
    const pose = {
      ...missingModel,
      name: "pose",
      filename: "pose.pt",
      sourceLabel: "GitHub · ultralytics/assets · v8.3.0",
    };
    mockApi({ items: [], nextCursor: null }, [missingModel, pose]);
    renderApp(<MatchLibrary />);
    fireEvent.click(await screen.findByRole("button", { name: "Install local models" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Model install stopped");
    await waitFor(() => {
      const modelReads = vi.mocked(fetch).mock.calls.filter(([input]) => String(input) === "/api/v1/models").length;
      const healthReads = vi.mocked(fetch).mock.calls.filter(([input]) => String(input) === "/api/v1/health").length;
      expect(modelReads).toBeGreaterThan(1);
      expect(healthReads).toBeGreaterThan(1);
    });
  });

  it("waits for every model ensure before refreshing truth after a mixed outcome", async () => {
    const pose = {
      ...missingModel,
      name: "pose",
      filename: "pose.pt",
      sourceLabel: "GitHub · ultralytics/assets · v8.3.0",
    };
    let ballReady = false;
    let ballRequested = false;
    let resolveBall = (): void => {};
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/v1/health") return Promise.resolve(jsonResponse(readyHealth));
        if (url === "/api/v1/models") {
          return Promise.resolve(jsonResponse([
            ballReady ? { ...missingModel, state: "ready" } : missingModel,
            pose,
          ]));
        }
        if (url === "/api/v1/models/ball/ensure" && init?.method === "POST") {
          return new Promise<Response>((resolve) => {
            ballRequested = true;
            resolveBall = () => {
              ballReady = true;
              resolve(jsonResponse({ ...missingModel, state: "ready" }));
            };
          });
        }
        if (url === "/api/v1/models/pose/ensure" && init?.method === "POST") {
          return Promise.resolve(jsonResponse({
            code: "model_download_failed",
            message: "model failed",
            details: null,
            requestId: "model-failure",
          }, 503));
        }
        if (url.startsWith("/api/v1/matches")) {
          return Promise.resolve(jsonResponse({ items: [], nextCursor: null }));
        }
        throw new Error(`unexpected request: ${url}`);
      }),
    );
    renderApp(<MatchLibrary />);
    fireEvent.click(await screen.findByRole("button", { name: "Install local models" }));
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v1/models/pose/ensure",
      expect.objectContaining({ method: "POST" }),
    ));
    expect(screen.getByRole("button", { name: "Installing local models…" })).toBeDisabled();
    expect(ballRequested).toBe(true);
    resolveBall();
    expect(await screen.findByRole("alert")).toHaveTextContent("Model install stopped");
    const ballRow = screen.getByText("ball.pt").closest("li");
    expect(ballRow).not.toBeNull();
    await waitFor(() => expect(within(ballRow as HTMLLIElement).getByText("ready")).toBeInTheDocument());
  });


  it("loads matches beyond the first 100 with the server-issued signed cursor", async () => {
    const cursor = "signed.page-one_abc-123";
    const firstPage = Array.from({ length: 100 }, (_, index) => matchSummary(index + 1));
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/health") return Promise.resolve(jsonResponse(readyHealth));
      if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
      if (url === "/api/v1/matches?limit=100") {
        return Promise.resolve(jsonResponse({ items: firstPage, nextCursor: cursor }));
      }
      if (url === `/api/v1/matches?limit=100&cursor=${cursor}`) {
        return Promise.resolve(jsonResponse({ items: [matchSummary(101)], nextCursor: null }));
      }
      if (url.startsWith("/api/v1/matches/")) return Promise.reject(new Error("detail unavailable"));
      throw new Error(`unexpected request: ${url}`);
    }));
    renderApp(<MatchLibrary />);

    const loadMore = await screen.findByRole("button", { name: "Load more matches" });
    fireEvent.click(loadMore);

    expect(await screen.findByRole("listitem", { name: "Match 101 match" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem", { name: /Match \d+ match/ })).toHaveLength(101);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      `/api/v1/matches?limit=100&cursor=${cursor}`,
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("stops on a repeated signed cursor and keeps the partial ledger visible", async () => {
    const cursor = "signed.repeated-cursor";
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/health") return Promise.resolve(jsonResponse(readyHealth));
      if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
      if (url === "/api/v1/matches?limit=100") {
        return Promise.resolve(jsonResponse({ items: [matchSummary(1)], nextCursor: cursor }));
      }
      if (url === `/api/v1/matches?limit=100&cursor=${cursor}`) {
        return Promise.resolve(jsonResponse({ items: [matchSummary(2)], nextCursor: cursor }));
      }
      if (url.startsWith("/api/v1/matches/")) return Promise.reject(new Error("detail unavailable"));
      throw new Error(`unexpected request: ${url}`);
    }));
    renderApp(<MatchLibrary />);
    fireEvent.click(await screen.findByRole("button", { name: "Load more matches" }));

    expect(await screen.findByRole("listitem", { name: "Match 2 match" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/some matches could not load.*refresh the page/i);
    expect(screen.queryByRole("button", { name: "Load more matches" })).not.toBeInTheDocument();
  });

  it("keeps loaded matches and exposes retry when the next page fails", async () => {
    const cursor = "signed.next-page";
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/health") return Promise.resolve(jsonResponse(readyHealth));
      if (url === "/api/v1/models") return Promise.resolve(jsonResponse([]));
      if (url === "/api/v1/matches?limit=100") {
        return Promise.resolve(jsonResponse({ items: [matchSummary(1)], nextCursor: cursor }));
      }
      if (url === `/api/v1/matches?limit=100&cursor=${cursor}`) {
        return Promise.resolve(jsonResponse({
          code: "cursor_invalid",
          message: "cursor rejected",
          details: null,
          requestId: "next-page",
        }, 422));
      }
      if (url.startsWith("/api/v1/matches/")) return Promise.reject(new Error("detail unavailable"));
      throw new Error(`unexpected request: ${url}`);
    }));
    renderApp(<MatchLibrary />);
    fireEvent.click(await screen.findByRole("button", { name: "Load more matches" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/additional matches unavailable/i);
    expect(screen.getByRole("listitem", { name: "Match 1 match" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry loading matches" })).toBeEnabled();
  });
});
