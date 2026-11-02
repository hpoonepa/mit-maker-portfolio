// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse } from "../../test-utils";
import { installFetch, match, queryNumber, renderWorkspace, report, reviewPage, setupAnalysisTestEnvironment, summary, teardownAnalysisTestEnvironment, timeline } from "./AnalysisWorkspace.test-utils";

beforeEach(setupAnalysisTestEnvironment);
afterEach(teardownAnalysisTestEnvironment);

describe("evidence-first synchronized analysis workspace", () => {
  it("keeps unsaved shot edits mounted while a URL-selected report loads or fails", async () => {
    let finish: ((response:Response)=>void)|undefined;
    const pending=new Promise<Response>(resolve=>{finish=resolve;});
    installFetch([],undefined,undefined,revision=>revision===3?pending:jsonResponse(report(revision)));
    const {router}=renderWorkspace();
    await screen.findByRole("heading",{name:"League night"});
    fireEvent.click(screen.getByText("Edit shot markers"));
    const add=await screen.findByRole("button",{name:"Add shot at current frame"});
    await waitFor(()=>expect(add).toBeEnabled());
    fireEvent.click(add);
    fireEvent.change(screen.getByLabelText("Shot notes"),{target:{value:"Keep this placement review"}});
    await act(async()=>{await router.navigate("/matches/match-1/analysis?revision=3");});
    expect(screen.getByLabelText("Shot notes")).toHaveValue("Keep this placement review");
    await act(async()=>{finish?.(jsonResponse({code:"unavailable",message:"Report unavailable",requestId:"test",details:null},500));});
    expect(screen.getByLabelText("Shot notes")).toHaveValue("Keep this placement review");
  });
  it("opens a completed report neutrally and skips metadata during event navigation", async () => {
    installFetch([], undefined, undefined, undefined, undefined, undefined, undefined, () => jsonResponse({
      ...timeline,
      items: [{ id: null, kind: "observationWindow", timestampUs: 0, endUs: 30_000_000, evidenceIds: [] }, ...timeline.items],
    }));
    renderWorkspace();
    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    await screen.findByRole("button", { name: /Shot.*drive/i });

    expect(screen.getByRole("link", { name: "Analysis — current step" })).toHaveAttribute("aria-current", "step");
    expect(screen.queryByText("Publishing report")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Evidence events in this window" })).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Evidence window" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Selected · observationWindow/)).not.toBeInTheDocument();
    expect(screen.getByText("Choose a moment from the timeline or reports.")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "]" });
    expect(video.currentTime).toBe(12.25);
    expect(screen.getByRole("combobox", { name: "Evidence events in this window" })).toHaveValue("shot-1");
  });

  it("does not request reports when match detail declares that none are published", async () => {
    const reportRequests: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/matches/match-1") {
        return Promise.resolve(jsonResponse({ ...match, latestJob: null, latestReport: null }));
      }
      if (url.includes("/reports")) {
        reportRequests.push(url);
        return Promise.resolve(url.endsWith("/latest")
          ? jsonResponse({ code: "report_not_found", message: "no report", details: null, requestId: "missing" }, 404)
          : jsonResponse({ items: [], nextCursor: null }));
      }
      throw new Error(`unexpected request: ${url}`);
    }));
    renderWorkspace();

    expect(await screen.findByRole("heading", { name: "Analysis unavailable" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open setup" })).toHaveAttribute("href", "/matches/match-1/setup");
    expect(screen.getByRole("link", { name: "Open processing" })).toHaveAttribute("href", "/matches/match-1/processing");
    expect(reportRequests).toEqual([]);
  });
  it("does not request a pinned historical report when match detail declares that none are published", async () => {
    const reportRequests: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/matches/match-1") {
        return Promise.resolve(jsonResponse({ ...match, latestJob: null, latestReport: null }));
      }
      if (url.includes("/reports")) {
        reportRequests.push(url);
        return Promise.resolve(jsonResponse(report(9)));
      }
      throw new Error(`unexpected request: ${url}`);
    }));
    renderWorkspace(9);

    expect(await screen.findByRole("heading", { name: "Analysis unavailable" })).toBeInTheDocument();
    expect(reportRequests).toEqual([]);
  });
  it("lets authoritative report removal replace retained report data with the unavailable state", async () => {
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    installFetch(requests);
    const { client, router } = renderWorkspace(4);
    expect(await screen.findByRole("heading", { name: "League night" })).toBeInTheDocument();
    expect(router.state.location.search).toBe("?revision=4");
    expect(requests.some(({ url }) => url.endsWith("/reports/4"))).toBe(true);
    const reportRequestCount = requests.filter(({ url }) => url.includes("/reports")).length;

    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, signal: init?.signal });
      if (url === "/api/v1/matches/match-1") {
        return Promise.resolve(jsonResponse({ ...match, latestReport: null }));
      }
      throw new Error(`unexpected request after report removal: ${url}`);
    });
    await act(async () => {
      await client.refetchQueries({ queryKey: ["matches", "match-1"], exact: true });
    });

    expect(await screen.findByRole("heading", { name: "Analysis unavailable" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "League night" })).not.toBeInTheDocument();
    expect(requests.filter(({ url }) => url.includes("/reports"))).toHaveLength(reportRequestCount);
  });
  it("loads explicit report history and only bounded abortable evidence windows", async () => {
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    installFetch(requests);
    const { client } = renderWorkspace();
    expect(await screen.findByRole("heading", { name: "League night" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Report revision" })).not.toBeInTheDocument();
    expect(requests.some(({ url }) => url.endsWith("/reports/latest"))).toBe(true);
    expect(requests.some(({ url }) => new URL(url, "http://local").pathname.endsWith("/reports"))).toBe(true);
    expect(client.getQueryData(["matches", "match-1", "reports"])).toEqual({ items: [summary(4), summary(3)], nextCursor: null });
    await waitFor(() => {
      const evidenceRequests = requests.filter(({ url }) => /observations|timeline/.test(url));
      expect(evidenceRequests.length).toBeGreaterThanOrEqual(3);
      for (const { url, signal } of evidenceRequests) {
        const parsed = new URL(url, "http://local");
        const start = Number(parsed.searchParams.get("startUs"));
        const end = Number(parsed.searchParams.get("endUs"));
        expect(end - start).toBeLessThanOrEqual(30_000_000);
        expect(parsed.searchParams.get("cursor")).toBeNull();
        expect(signal).toBeInstanceOf(AbortSignal);
        if (url.includes("/timeline?")) {
          expect(parsed.searchParams.get("revision")).toBe("4");
          expect(parsed.searchParams.get("kinds")).toBe("rally,shot,error,contact,observationWindow");
        } else if (url.includes("/observations/")) {
          expect(parsed.searchParams.get("revision")).toBe("4");
        }
      }
    });
    expect(screen.queryByText(/full match/i)).not.toBeInTheDocument();
  });
  it("leads with one evidence workstation before reports", async () => {
    installFetch([]);
    renderWorkspace();
    const workstation = await screen.findByRole("region", { name: "Video evidence workstation" });
    const video = screen.getByLabelText("Video evidence instrument");
    const timeline = screen.getByRole("region", { name: "Evidence timeline" });
    const inspector = screen.getByRole("region", { name: "Selected evidence inspector" });
    const reports = screen.getByRole("region", { name: "Match report workspace" });

    expect(workstation).toContainElement(video);
    expect(workstation).toContainElement(timeline);
    expect(workstation).toContainElement(inspector);
    expect(workstation.compareDocumentPosition(reports) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("group", { name: "Playback transport" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Evidence frame navigation" })).toBeInTheDocument();
    const overlayOptions = screen.getByText("Overlay options").closest("details");
    expect(overlayOptions).not.toBeNull();
    expect(video.querySelector(".video-stage")?.contains(overlayOptions)).toBe(false);
  });

  it("keeps the report tablist while offering a compact grouped report picker", async () => {
    installFetch([]);
    renderWorkspace();
    const picker = await screen.findByRole("combobox", { name: "Report section" });

    expect(screen.getByRole("tablist", { name: "Analysis reports" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Evidence" })).toBeInTheDocument();
    fireEvent.change(picker, { target: { value: "movement" } });

    expect(screen.getByRole("tab", { name: "Movement" })).toHaveAttribute("aria-selected", "true");
    expect(picker).toHaveValue("movement");
  });
  it("prefetches one adjacent bounded window only through the idle scheduler", async () => {
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    vi.stubGlobal("requestIdleCallback", vi.fn((callback: IdleRequestCallback) => {
      callback({ didTimeout: false, timeRemaining: () => 50 });
      return 1;
    }));
    vi.stubGlobal("cancelIdleCallback", vi.fn());
    installFetch(requests);
    renderWorkspace();
    await screen.findByRole("heading", { name: "League night" });
    await waitFor(() => expect(requests.some(({ url }) => queryNumber(url, "startUs") === 0 && queryNumber(url, "endUs") === 30_000_000)).toBe(true));
    expect(window.requestIdleCallback).toHaveBeenCalled();
  });

  it("reuses evidence while frames advance and only requests a new bucket at the boundary", async () => {
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    installFetch(requests);
    renderWorkspace();
    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    await screen.findByRole("button", { name: /Shot.*drive/i });
    const evidenceRequests = () => requests.filter(({ url }) => /observations|timeline/.test(url));
    const initialCount = evidenceRequests().length;

    for (const time of [0.25, 1, 4, 9.99]) {
      video.currentTime = time;
      fireEvent.timeUpdate(video);
    }
    expect(evidenceRequests()).toHaveLength(initialCount);
    expect(screen.getByRole("button", { name: /Shot.*drive/i })).toBeInTheDocument();

    video.currentTime = 10;
    fireEvent.timeUpdate(video);
    await waitFor(() => expect(evidenceRequests()).toHaveLength(initialCount + 3));
    expect(evidenceRequests().slice(-3).every(({ url }) => queryNumber(url, "startUs") === 0 && queryNumber(url, "endUs") === 30_000_000)).toBe(true);
  });

  it("scrubs to any match position without moving keyboard focus out of the slider", async () => {
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    installFetch(requests);
    renderWorkspace();
    const slider = await screen.findByRole("slider", { name: "Match playback position" });
    const video = screen.getByLabelText("Match video evidence") as HTMLVideoElement;
    slider.focus();
    fireEvent.change(slider, { target: { value: "125.5" } });

    expect(video.currentTime).toBe(125.5);
    expect(slider).toHaveValue("125.5");
    expect(slider).toHaveAttribute("aria-valuetext", "2:05 of 3:00");
    expect(slider).toHaveFocus();
    await waitFor(() => expect(requests.some(({ url }) => url.includes("/timeline?") && queryNumber(url, "startUs") === 110_000_000 && queryNumber(url, "endUs") === 140_000_000)).toBe(true));
    expect(slider).toHaveFocus();
  });

  it("keeps playback and seek controls inside the fullscreen target", async () => {
    installFetch([]);
    renderWorkspace();
    const instrument = await screen.findByLabelText("Video evidence instrument");
    const requestFullscreen = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(instrument, "requestFullscreen", { value: requestFullscreen });
    fireEvent.click(screen.getByRole("button", { name: "Fullscreen evidence" }));

    expect(requestFullscreen).toHaveBeenCalledOnce();
    expect(instrument).toContainElement(screen.getByRole("button", { name: "Play" }));
    expect(instrument).toContainElement(screen.getByRole("slider", { name: "Match playback position" }));
  });

  it("reports rejected fullscreen and playback requests without losing the controls", async () => {
    installFetch([]);
    renderWorkspace();
    const instrument = await screen.findByLabelText("Video evidence instrument");
    Object.defineProperty(instrument, "requestFullscreen", { value: vi.fn().mockRejectedValue(new Error("not allowed")) });
    fireEvent.click(screen.getByRole("button", { name: "Fullscreen evidence" }));
    expect(await screen.findByText(/Fullscreen could not open/)).toBeInTheDocument();

    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new DOMException("not allowed", "NotAllowedError"));
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(await screen.findByText(/Playback could not start/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    await waitFor(() => expect(screen.queryByText(/Playback could not start/)).not.toBeInTheDocument());
  });

  it("handles keyboard play rejection and offers a retry when media fails to load", async () => {
    installFetch([]);
    renderWorkspace();
    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    vi.mocked(HTMLMediaElement.prototype.play).mockRejectedValueOnce(new Error("network unavailable"));
    fireEvent.keyDown(document, { code: "Space" });
    expect(await screen.findByText(/Playback could not start/)).toBeInTheDocument();

    fireEvent.error(video);
    expect(screen.getByRole("alert")).toHaveTextContent("The match video could not be loaded");
    const reload = vi.spyOn(video, "load").mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Reload video" }));
    expect(reload).toHaveBeenCalledOnce();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });


  it("exhausts every signed review page instead of presenting a partial queue as complete", async () => {
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    installFetch(requests, undefined, (url) => {
      const cursor = new URL(url, "http://local").searchParams.get("cursor");
      const index = cursor === null ? 0 : Number(cursor.replace("cursor-", ""));
      const page = reviewPage(4);
      const item = page.items[0];
      if (item === undefined) throw new Error("review fixture item missing");
      return jsonResponse({ ...page, nextCursor: index < 8 ? `cursor-${index + 1}` : null, items: [{ ...item, id: `error-${index}`, commandTargets: { ...item.commandTargets, accept: { ...item.commandTargets.accept, targetId: `error-${index}` }, reject: { ...item.commandTargets.reject, targetId: `error-${index}` } } }] });
    });
    renderWorkspace();
    await waitFor(() => expect(screen.getByText("1 / 9")).toBeInTheDocument());
    expect(requests.filter(({ url }) => url.includes("/review-items?"))).toHaveLength(9);
  });

  it("shows review loading without claiming the queue is clear", async () => {
    let finishReview: ((response: Response) => void) | undefined;
    const pendingReview = new Promise<Response>((resolve) => { finishReview = resolve; });
    installFetch([], undefined, () => pendingReview);
    renderWorkspace();

    await screen.findByRole("heading", { name: "League night" });
    expect(screen.getByText("Loading complete review queue…")).toHaveAttribute("role", "status");
    expect(screen.queryByText("Queue clear")).not.toBeInTheDocument();

    finishReview?.(jsonResponse(reviewPage(4)));
    expect(await screen.findByRole("button", { name: /Review error/i })).toBeInTheDocument();
  });

  it.each([
    ["network", () => Promise.reject(new TypeError("connection closed"))],
    ["decoder", () => Promise.resolve(jsonResponse({ reportRevision: 4, nextCursor: null, items: "invalid" }))],
  ])("shows an actionable review error after an initial %s failure", async (_kind, failedReview) => {
    installFetch([], undefined, failedReview);
    renderWorkspace();

    expect(await screen.findByRole("alert")).toHaveTextContent("Review queue unavailable");
    expect(screen.getByRole("button", { name: "Retry review queue" })).toBeEnabled();
    expect(screen.queryByText("Queue clear")).not.toBeInTheDocument();
  });

  it("retains partial review pages and rejects a repeated signed cursor", async () => {
    installFetch([], undefined, (url) => {
      const page = reviewPage(4);
      const cursor = new URL(url, "http://local").searchParams.get("cursor");
      return jsonResponse({ ...page, nextCursor: "signed-repeat", items: page.items.map((item) => ({ ...item, id: cursor === null ? "error-first" : "error-second", reviewEntityId: cursor === null ? "error-first" : "error-second" })) });
    });
    renderWorkspace();

    expect(await screen.findByRole("alert")).toHaveTextContent("Review queue incomplete");
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.queryByText("Queue clear")).not.toBeInTheDocument();
  });

  it("retains page-one review items when page two fails and retries to a complete queue", async () => {
    let failed = true;
    installFetch([], undefined, (url) => {
      const cursor = new URL(url, "http://local").searchParams.get("cursor");
      if (cursor === null) return jsonResponse({ ...reviewPage(4), nextCursor: "signed-page-2" });
      if (failed) return jsonResponse({ code: "review_page_failed", message: "page unavailable", requestId: "test", details: null }, 500);
      return jsonResponse({ ...reviewPage(4), items: [{ ...reviewPage(4).items[0], id: "error-2", reviewEntityId: "error-2" }] });
    });
    renderWorkspace();

    expect(await screen.findByRole("alert")).toHaveTextContent("1 review item loaded before the request failed");
    expect(screen.queryByText("Queue clear")).not.toBeInTheDocument();
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry review queue" }));
    await waitFor(() => expect(screen.getByText("1 / 2")).toBeInTheDocument());
    expect(screen.queryByText("Review queue incomplete")).not.toBeInTheDocument();
  });

  it("consumes report history beyond the first fifty signed entries", async () => {
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    installFetch(requests, undefined, undefined, undefined, undefined, undefined, (url) => {
      const cursor = new URL(url, "http://local").searchParams.get("cursor");
      return cursor === null
        ? jsonResponse({ items: Array.from({ length: 50 }, (_, index) => summary(54 - index)), nextCursor: "signed-history-2" })
        : jsonResponse({ items: [summary(4), summary(3)], nextCursor: null });
    });
    const { client } = renderWorkspace();

    expect(await screen.findByRole("heading", { name: "League night" })).toBeInTheDocument();
    expect(client.getQueryData(["matches", "match-1", "reports"])).toMatchObject({ items: expect.arrayContaining([summary(54), summary(3)]), nextCursor: null });
    const historyRequests = requests.filter(({ url }) => url.includes("/reports?"));
    expect(historyRequests).toHaveLength(2);
    expect(new URL(historyRequests[1].url, "http://local").searchParams.get("cursor")).toBe("signed-history-2");
  });

  it.each(["repeat", "error"])("retains partial report history after a page-two %s", async (failure) => {
    installFetch([], undefined, undefined, undefined, undefined, undefined, (url) => {
      const cursor = new URL(url, "http://local").searchParams.get("cursor");
      if (cursor === null) return jsonResponse({ items: [summary(4)], nextCursor: "signed-history-2" });
      return failure === "repeat"
        ? jsonResponse({ items: [summary(3)], nextCursor: "signed-history-2" })
        : jsonResponse({ code: "history_page_failed", message: "history unavailable", requestId: "test", details: null }, 500);
    });
    const { client } = renderWorkspace();

    expect(await screen.findByRole("alert")).toHaveTextContent("Report history incomplete");
    expect(client.getQueryState(["matches", "match-1", "reports"])?.error).toMatchObject({ items: expect.arrayContaining([summary(4)]) });
    expect(screen.getByRole("button", { name: "Retry report history" })).toBeEnabled();
  });

  it("keeps video, timeline, report evidence, speed, and keyboard seeking on one path", async () => {
    installFetch([]);
    renderWorkspace();
    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    fireEvent.loadedMetadata(video);
    fireEvent.click(await screen.findByRole("button", { name: /Shot.*drive/i }));
    expect(video.currentTime).toBeCloseTo(12.25);
    expect(screen.getByTestId("selected-time-status")).toHaveTextContent("0:12.250");
    fireEvent.click(screen.getByRole("button", { name: "0.5×" }));
    expect(video.playbackRate).toBe(0.5);
    expect(screen.getByRole("button", { name: "0.5×" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(document, { key: "]" });
    expect(video.currentTime).toBeCloseTo(15);
    fireEvent.keyDown(document, { key: "ArrowLeft" });
    expect(video.currentTime).toBeLessThan(15);
    const beforeTabKey = video.currentTime;
    fireEvent.click(screen.getByRole("tab", { name: "Shots" }));
    fireEvent.keyDown(screen.getByRole("tab", { name: "Shots" }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Rallies" })).toHaveAttribute("aria-selected", "true");
    expect(video.currentTime).toBe(beforeTabKey);
    expect(screen.getByRole("tablist", { name: "Analysis reports" })).toHaveClass("report-tabs");
  });
  it("resolves report evidence outside the visible window through the bounded public lookup", async () => {
    installFetch([]);
    renderWorkspace();
    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    fireEvent.click(await screen.findByRole("button", { name: "Open overview evidence" }));
    await waitFor(() => expect(video.currentTime).toBe(90));
    expect(screen.getByTestId("selected-time-status")).toHaveTextContent("1:30.000");
  });

  it("removes prior revision evidence while the newly selected revision is loading", async () => {
    let finishTimeline: ((response: Response) => void) | undefined;
    let finishPlayers: ((response: Response) => void) | undefined;
    let finishBalls: ((response: Response) => void) | undefined;
    const pendingTimeline = new Promise<Response>((resolve) => { finishTimeline = resolve; });
    const pendingPlayers = new Promise<Response>((resolve) => { finishPlayers = resolve; });
    const pendingBalls = new Promise<Response>((resolve) => { finishBalls = resolve; });
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    const oldEvent = {
      id: "same-shot-id",
      kind: "shot",
      timestampUs: 1_000_000,
      evidenceIds: ["old-revision-evidence"],
      observationLinks: { ball: "old-ball" },
      summary: { hitter: "near", shot_type: "drive", outcome: "in_play" },
    };
    const oldPlayer = {
      ambiguityReason: null,
      ambiguous: false,
      associationConfidence: 0.9,
      box: [100, 50, 180, 230],
      calibrationProvenance: "active",
      calibrationRevision: "3",
      detectionConfidence: 0.95,
      evidence: "observed",
      evidenceEndFrameIndex: 0,
      evidenceEndTimestampUs: 0,
      evidenceStartFrameIndex: 0,
      evidenceStartTimestampUs: 0,
      feet: [140, 230],
      keypoints: [],
      skeletonEdges: [],
      feetUncertaintyPx: 3,
      floor: [2, 4],
      floorUncertaintyM: 0.1,
      modelManifestId: "players-v4",
      playerId: "near",
      sourceFrameIndex: 0,
      sourceManifestId: "proxy-v4",
      sourceTimestampUs: 0,
      timestampUs: 0,
    };
    const oldBall = {
      ambiguityReason: null,
      ambiguous: false,
      candidateCount: 1,
      candidates: [{ x: 600, y: 320, probability: 0.9, covariance: [[16, 0], [0, 9]] }],
      covariance: [[16, 0], [0, 9]],
      device: "mps",
      deviceFallback: false,
      evidence: "observed",
      evidenceEndFrameIndex: 0,
      evidenceEndTimestampUs: 0,
      evidenceStartFrameIndex: 0,
      evidenceStartTimestampUs: 0,
      modelManifestId: "ball-v4",
      probability: 0.9,
      segmentId: "segment-v4",
      sourceFrameIndex: 0,
      sourceHeight: 1080,
      sourceManifestId: "proxy-v4",
      sourceTimestampUs: 0,
      sourceWidth: 1920,
      timestampUs: 0,
      visible: true,
      x: 600,
      y: 320,
    };
    installFetch(
      requests,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      (url) => queryNumber(url, "revision") === 4
        ? jsonResponse({ predictionRevision: 7, nextCursor: null, items: [oldEvent] })
        : pendingTimeline,
      (url) => queryNumber(url, "revision") === 4
        ? jsonResponse({ artifact: { availability: "available", jobId: "job-1", modelManifestIds: ["players-v4"], sourceManifestIds: ["proxy-v4"], stage: "players", warnings: [] }, startUs: queryNumber(url, "startUs"), endUs: queryNumber(url, "endUs"), nextCursor: null, items: [oldPlayer] })
        : pendingPlayers,
      (url) => queryNumber(url, "revision") === 4
        ? jsonResponse({ artifact: { availability: "available", jobId: "job-1", modelManifestIds: ["ball-v4"], sourceManifestIds: ["proxy-v4"], stage: "ball", warnings: [] }, startUs: queryNumber(url, "startUs"), endUs: queryNumber(url, "endUs"), nextCursor: null, items: [oldBall] })
        : pendingBalls,
    );
    const { router } = renderWorkspace();
    expect(await screen.findByText(/Player A observed.*Ball observed/i)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Shot.*drive/i }));

    await act(async () => { await router.navigate("/matches/match-1/analysis?revision=3"); });

    expect(await screen.findByText("Loading evidence for report revision 3…")).toHaveAttribute("role", "status");
    expect(screen.queryByRole("button", { name: /Shot.*drive/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Player A unavailable.*Ball unavailable/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No event selected" })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "]" });
    expect(requests.filter(({ url }) => url.includes("/evidence/"))).toHaveLength(0);

    finishTimeline?.(jsonResponse({ predictionRevision: 7, nextCursor: null, items: [{ ...oldEvent, evidenceIds: ["new-revision-evidence"], summary: { hitter: "near", shot_type: "drop", outcome: "winner" } }] }));
    finishPlayers?.(jsonResponse({ artifact: { availability: "available", jobId: "job-1", modelManifestIds: ["players-v3"], sourceManifestIds: ["proxy-v3"], stage: "players", warnings: [] }, startUs: 0, endUs: 120_000_000, nextCursor: null, items: [] }));
    finishBalls?.(jsonResponse({ artifact: { availability: "available", jobId: "job-1", modelManifestIds: ["ball-v3"], sourceManifestIds: ["proxy-v3"], stage: "ball", warnings: [] }, startUs: 0, endUs: 120_000_000, nextCursor: null, items: [] }));
    expect(await screen.findByRole("button", { name: /Shot.*drop/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No event selected" })).toBeInTheDocument();
  });


});
