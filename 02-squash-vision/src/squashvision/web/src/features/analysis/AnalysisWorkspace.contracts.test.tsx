// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { jsonResponse } from "../../test-utils";
import { installFetch, queryNumber, renderWorkspace, report, reviewPage, setupAnalysisTestEnvironment, teardownAnalysisTestEnvironment, timeline } from "./AnalysisWorkspace.test-utils";

beforeEach(setupAnalysisTestEnvironment);
afterEach(teardownAnalysisTestEnvironment);

describe("analysis correction and export contracts", () => {
  it("updates pre-save invalidation impact from the selected server command", async () => {
    installFetch([]);
    renderWorkspace();
    expect(await screen.findByText("Winner Count, Shot Outcomes")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Correction"), { target: { value: "accept" } });
    await waitFor(() => expect(screen.getByText("Review Counts")).toBeInTheDocument());
    expect(screen.queryByText("Winner Count, Shot Outcomes")).not.toBeInTheDocument();
  });
  it("retains a non-conflict correction draft and provides an actionable retry", async () => {
    let attempts = 0;
    installFetch([], () => {
      attempts += 1;
      return attempts === 1
        ? jsonResponse({ code: "correction_write_failed", message: "Local correction store is temporarily unavailable", requestId: "test", details: null }, 500)
        : jsonResponse(report(5));
    });
    const { router } = renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: /Review error/i }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Retain this retry draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Correction was not saved");
    expect(screen.getByLabelText("Reason")).toHaveValue("Retain this retry draft");
    fireEvent.click(screen.getByRole("button", { name: "Retry correction" }));
    await waitFor(() => expect(router.state.location.search).toBe("?revision=5"));
    expect(attempts).toBe(2);
  });


  it("removes the resolved review entity exactly once after the server revision", async () => {
    const resolved = report(5);
    resolved.sections.review = { ...resolved.sections.review, payload: { candidate_count: 1, reviewed_count: 1, pending_ids: [] } };
    installFetch([], () => jsonResponse(resolved), (url) => jsonResponse({ reportRevision: queryNumber(url, "revision"), nextCursor: null, items: queryNumber(url, "revision") >= 5 ? [] : reviewPage(4).items }), () => jsonResponse(resolved));
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: /Review error/i }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Resolve this review entity" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(screen.getByText("Queue clear")).toBeInTheDocument());
    expect(screen.getByText("1 of 1 reviewed")).toBeInTheDocument();
    expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument();
  });


  it("pins a successful correction revision without losing video time and retains drafts across 409 rebase", async () => {
    let conflict = false;
    installFetch([], () => conflict ? jsonResponse({ code: "report_revision_conflict", message: "expected report revision 4, current revision is 5", requestId: "test", details: { currentRevision: 5 } }, 409) : jsonResponse(report(5)));
    const { router } = renderWorkspace();
    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", { value: 15, writable: true });
    fireEvent.click(await screen.findByRole("button", { name: /Review error/i }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Outcome verified from wall contact" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(router.state.location.search).toBe("?revision=5"));
    expect(video.currentTime).toBe(15);

    conflict = true;
    await waitFor(() => expect(screen.getByRole("button", { name: "Save correction" })).toBeEnabled());
    fireEvent.change(await screen.findByLabelText("Reason"), { target: { value: "Keep this draft through conflict" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Revision 5");
    expect(screen.getByLabelText("Reason")).toHaveValue("Keep this draft through conflict");
    expect(video.currentTime).toBe(15);
  });
  it("loads authoritative reapplication conflicts on normal open without losing draft or video time", async () => {
    let finishConflicts: ((response: Response) => void) | undefined;
    const pendingConflicts = new Promise<Response>((resolve) => { finishConflicts = resolve; });
    const resolutionBodies: Array<Record<string, unknown>> = [];
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    installFetch(
      requests,
      undefined,
      undefined,
      undefined,
      () => pendingConflicts,
      (_url, init) => {
        resolutionBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return jsonResponse(report(5));
      },
    );
    const { router } = renderWorkspace();

    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", { value: 15, writable: true });
    fireEvent.change(await screen.findByLabelText("Reason"), { target: { value: "Keep this draft while conflicts load" } });
    expect(screen.getByText("Loading conflict candidates…")).toHaveAttribute("role", "status");
    expect(screen.queryByText(/No reapplication conflicts/)).not.toBeInTheDocument();
    expect(requests.filter(({ url }) => url.endsWith("/correction-conflicts"))).toHaveLength(1);
    finishConflicts?.(jsonResponse({ conflicts: [{ correctionId: "correction-1", reason: "target changed after reanalysis", candidateIds: ["candidate-a"], candidates: [{ candidateId: "candidate-a", timestampUs: 15_000_000, evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455, evidenceIds: ["error-1"], label: "Remapped shot candidate" }] }] }));
    expect(await screen.findByRole("radio", { name: /Remapped shot candidate/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Reason")).toHaveValue("Keep this draft while conflicts load");
    expect(video.currentTime).toBe(15);
    fireEvent.click(screen.getByRole("radio", { name: /Remapped shot candidate/ }));
    fireEvent.click(screen.getByRole("button", { name: "Select candidate" }));

    await waitFor(() => expect(router.state.location.search).toBe("?revision=5"));
    expect(resolutionBodies[0].expectedReportRevision).toBe(4);
    expect(video.currentTime).toBe(15);
  });

  it("retries an authoritative conflict-list failure and announces empty only after success", async () => {
    let conflictAttempts = 0;
    installFetch([], undefined, undefined, undefined, () => {
      conflictAttempts += 1;
      return conflictAttempts === 1
        ? jsonResponse({ code: "conflicts_failed", message: "conflicts unavailable", requestId: "test", details: null }, 500)
        : jsonResponse({ conflicts: [] });
    });
    renderWorkspace();

    expect(await screen.findByRole("alert")).toHaveTextContent("Conflict candidates unavailable");
    expect(screen.queryByText(/No reapplication conflicts/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry conflict candidates" }));
    expect(await screen.findByText("No reapplication conflicts for current revision 4.")).toHaveClass("sr-only");
    expect(conflictAttempts).toBe(2);
  });

  it("keeps loaded conflict candidates visible as partial when the current revision cannot load", async () => {
    installFetch(
      [],
      undefined,
      undefined,
      (revision) => revision === 4
        ? jsonResponse({ code: "revision_failed", message: "current revision unavailable", requestId: "test", details: null }, 500)
        : jsonResponse(report(revision)),
      () => jsonResponse({ conflicts: [{ correctionId: "correction-1", reason: "target changed after reanalysis", candidateIds: ["candidate-a"], candidates: [{ candidateId: "candidate-a", timestampUs: 15_000_000, evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455, evidenceIds: ["error-1"], label: "Loaded candidate" }] }] }),
    );
    renderWorkspace(3);

    expect(await screen.findByRole("alert")).toHaveTextContent("Conflict review partially loaded");
    expect(screen.getByText(/1 conflict loaded/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select candidate" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry current revision" })).toBeEnabled();
  });

  it("exposes reapplication conflict controls when the normal review queue is empty", async () => {
    installFetch(
      [],
      undefined,
      (url) => jsonResponse({ reportRevision: queryNumber(url, "revision"), nextCursor: null, items: [] }),
      undefined,
      () => jsonResponse({ conflicts: [{ correctionId: "correction-1", reason: "accepted correction needs remapping", candidateIds: ["candidate-a"], candidates: [{ candidateId: "candidate-a", timestampUs: 15_000_000, evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455, evidenceIds: ["error-1"], label: "Independent remap candidate" }] }] }),
      undefined,
      undefined,
      () => jsonResponse({ ...timeline, items: [] }),
    );
    renderWorkspace();

    expect(await screen.findByRole("radio", { name: /Independent remap candidate/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select candidate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject reapplication" })).toBeEnabled();
    expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument();
  });

  it("offers rebase for conflicts on a newer current revision while retaining local context", async () => {
    installFetch(
      [],
      undefined,
      undefined,
      (revision) => jsonResponse(report(revision)),
      () => jsonResponse({ conflicts: [{ correctionId: "correction-1", reason: "target changed after reanalysis", candidateIds: ["candidate-a"], candidates: [{ candidateId: "candidate-a", timestampUs: 15_000_000, evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455, evidenceIds: ["error-1"], label: "Current candidate" }] }] }),
    );
    const { router } = renderWorkspace(3);

    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", { value: 15, writable: true });
    fireEvent.change(await screen.findByLabelText("Reason"), { target: { value: "Keep this historical draft" } });
    expect(screen.getByLabelText("Reason")).toHaveValue("Keep this historical draft");
    expect(video.currentTime).toBe(15);
    fireEvent.click(await screen.findByRole("button", { name: "Rebase conflict review onto revision 4" }));

    await waitFor(() => expect(router.state.location.search).toBe("?revision=4"));
    const selectCandidate = await screen.findByRole("button", { name: "Select candidate" });
    expect(selectCandidate).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: /Current candidate/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Select candidate" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Reject reapplication" })).toBeEnabled();
  });

  it("uses the loaded current revision for conflict resolution and retries without losing draft or time", async () => {
    const resolutionBodies: Array<Record<string, unknown>> = [];
    const requests: Array<{ url: string; signal?: AbortSignal | null }> = [];
    let resolutionAttempts = 0;
    let finishResolution: ((response: Response) => void) | undefined;
    installFetch(
      requests,
      () => jsonResponse({ code: "report_revision_conflict", message: "revision changed", requestId: "test", details: { currentRevision: 5 } }, 409),
      undefined,
      (revision) => jsonResponse(report(revision)),
      () => jsonResponse({ conflicts: [{ correctionId: "correction-1", reason: "target changed", candidateIds: ["candidate-a"], candidates: [{ candidateId: "candidate-a", timestampUs: 15_000_000, evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455, evidenceIds: ["error-1"], label: "Current shot candidate" }] }] }),
      (_url, init) => {
        resolutionAttempts += 1;
        resolutionBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        if (resolutionAttempts === 1) return new Promise<Response>((resolve) => { finishResolution = resolve; });
        return jsonResponse(report(6));
      },
    );
    const { router } = renderWorkspace();
    const video = await screen.findByLabelText("Match video evidence") as HTMLVideoElement;
    Object.defineProperty(video, "currentTime", { value: 15, writable: true });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save correction" })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Keep this conflict draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(requests.some(({ url }) => url.endsWith("/corrections"))).toBe(true));
    expect(await screen.findByText("A newer report is available")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("radio", { name: /Current shot candidate/ }));
    fireEvent.click(screen.getByRole("button", { name: "Select candidate" }));

    expect(await screen.findByText("Saving conflict resolution…")).toHaveAttribute("role", "status");
    expect(resolutionBodies[0].expectedReportRevision).toBe(5);
    finishResolution?.(jsonResponse({ code: "resolution_failed", message: "resolution unavailable", requestId: "test", details: null }, 500));
    expect(await screen.findByText("Conflict resolution was not saved")).toBeInTheDocument();
    expect(screen.getByLabelText("Reason")).toHaveValue("Keep this conflict draft");
    expect(video.currentTime).toBe(15);

    fireEvent.click(screen.getByRole("button", { name: "Retry conflict resolution" }));
    await waitFor(() => expect(router.state.location.search).toBe("?revision=6"));
    expect(resolutionBodies.map((body) => body.expectedReportRevision)).toEqual([5, 5]);
    expect(video.currentTime).toBe(15);
  });
  it("shows conflict candidate loading and retries a failed conflict list", async () => {
    let conflictAttempts = 0;
    let finishConflicts: ((response: Response) => void) | undefined;
    const candidateList = { conflicts: [{ correctionId: "correction-1", reason: "target changed", candidateIds: ["candidate-a"], candidates: [{ candidateId: "candidate-a", timestampUs: 15_000_000, evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_200_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 455, evidenceIds: ["error-1"], label: "Retried candidate" }] }] };
    installFetch(
      [],
      () => jsonResponse({ code: "report_revision_conflict", message: "revision changed", requestId: "test", details: { currentRevision: 5 } }, 409),
      undefined,
      (revision) => jsonResponse(report(revision)),
      () => {
        conflictAttempts += 1;
        if (conflictAttempts === 1) return jsonResponse({ conflicts: [] });
        if (conflictAttempts === 2) return new Promise<Response>((resolve) => { finishConflicts = resolve; });
        return jsonResponse(candidateList);
      },
    );
    renderWorkspace();
    await screen.findByLabelText("Reason");
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Retain while candidates load" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));

    expect(await screen.findByText("Loading conflict candidates…")).toHaveAttribute("role", "status");
    finishConflicts?.(jsonResponse({ code: "conflicts_failed", message: "conflicts unavailable", requestId: "test", details: null }, 500));
    expect(await screen.findByText("Conflict candidates unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select candidate" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry conflict candidates" }));
    expect(await screen.findByRole("radio", { name: /Retried candidate/ })).toBeInTheDocument();
    expect(conflictAttempts).toBe(3);
  });

  it("exports the pinned revision only after a completed server bundle is confirmed", async () => {
    installFetch([]);
    renderWorkspace();
    await screen.findByRole("heading", { name: "League night" });
    fireEvent.click(screen.getByText("Export options"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Include evidence clips" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Include original video/i }));
    fireEvent.click(screen.getByRole("button", { name: "Build local export" }));
    await waitFor(() => expect(screen.getByRole("link", { name: "Download completed export" })).toBeInTheDocument());

    const calls = vi.mocked(fetch).mock.calls;
    const exportCall = calls.find(([input, init]) => String(input).endsWith("/exports") && init?.method === "POST");
    expect(exportCall).toBeDefined();
    expect(JSON.parse(String(exportCall?.[1]?.body))).toEqual({
      revision: 4,
      selection: {
        formats: ["html", "json", "csv"],
        evidenceIds: ["report-off-window"],
        evidenceDurationSeconds: 6,
        includeOriginal: true,
      },
    });
    expect(screen.getByRole("link", { name: "Download completed export" })).toHaveAttribute(
      "href",
      "/api/v1/matches/match-1/exports/export-1/download",
    );
    expect(screen.getByText("Download the report with optional video clips.")).toBeInTheDocument();
  });

});
