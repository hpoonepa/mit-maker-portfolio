// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CorrectionEditor } from "./CorrectionEditor";
import type { ReviewItem } from "./review-model";

const item: ReviewItem = {
  id: "shot-1",
  targetType: "shot",
  kind: "shot",
  timestampUs: 12_340_000,
  endUs: 12_380_000,
  confidence: 0.41,
  issue: "hitter",
  evidenceIds: ["ev-1", "ev-2"],
  provenance: "observed",
  probabilities: { near: 0.41, far: 0.38 },
  reasons: ["players overlap at contact"],
  evidenceStartTimestampUs: 12_300_000,
  evidenceEndTimestampUs: 12_380_000,
  evidenceStartFrameIndex: 369,
  evidenceEndFrameIndex: 372,
  invalidatedSections: ["overview", "shots", "movement"],
  invalidatedStats: ["player_shot_counts"],
  summary: { hitter: "near", shot_type: "drive", outcome: "continuation", source_timestamp_us: 12_345_000 },
  commandTargets: Object.fromEntries(["accept", "reject", "change_hitter", "change_shot_type", "change_outcome", "ball_control_point"].map((command) => { const reviewCommand = command === "accept" || command === "reject"; return [command, { targetType: reviewCommand ? "error_candidate" : "shot", targetId: reviewCommand ? "error-1" : "shot-1", sourceTimestampUs: reviewCommand ? 12_345_000 : 12_340_000, sourceEvidenceIds: reviewCommand ? ["ev-1", "ev-2"] : ["shot-ev"], evidenceStartTimestampUs: reviewCommand ? 12_300_000 : 12_340_000, evidenceEndTimestampUs: reviewCommand ? 12_380_000 : 12_340_000, evidenceStartFrameIndex: reviewCommand ? 369 : 370, evidenceEndFrameIndex: reviewCommand ? 372 : 370 }] })),
  commandImpacts: Object.fromEntries(["accept", "reject", "change_hitter", "change_shot_type", "change_outcome", "ball_control_point"].map((command) => [command, { invalidatedSections: ["overview", "shots"], invalidatedStats: [`${command}_stats`] }])),
  reviewEntityType: "error_candidate",
  reviewEntityId: "error-1",
  reviewStatus: "pending",
};

afterEach(cleanup);

describe("correction editor", () => {
  it("submits a generated correction command with the exact revision and source anchors", () => {
    const submit = vi.fn();
    render(<CorrectionEditor matchId="match-1" item={item} reportRevision={4} pending={false} onSubmit={submit} />);
    fireEvent.change(screen.getByLabelText("Correction"), { target: { value: "change_hitter" } });
    fireEvent.change(screen.getByLabelText("Hitter"), { target: { value: "far" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Player identity verified from preceding frame" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(submit).toHaveBeenCalledWith({
      commandType: "change_hitter",
      expectedReportRevision: 4,
      matchId: "match-1",
      payload: { hitter: "far" },
      reason: "Player identity verified from preceding frame",
      sourceEvidenceIds: ["shot-ev"],
      sourceTimestampUs: 12_340_000,
      targetId: "shot-1",
      reviewEntityType: "error_candidate",
      reviewEntityId: "error-1",
      targetType: "shot",
    });
  });
  it("uses the review candidate anchor for accept and the underlying shot anchor for edits", () => {
    const submit = vi.fn();
    render(<CorrectionEditor matchId="match-1" item={item} reportRevision={4} pending={false} onSubmit={submit} />);
    fireEvent.change(screen.getByLabelText("Correction"), { target: { value: "accept" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Accept the candidate itself" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ commandType: "accept", targetType: "error_candidate", targetId: "error-1", sourceTimestampUs: 12_345_000, sourceEvidenceIds: ["ev-1", "ev-2"] }));
    fireEvent.change(screen.getByLabelText("Correction"), { target: { value: "change_outcome" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Edit the underlying shot" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(submit).toHaveBeenLastCalledWith(expect.objectContaining({ commandType: "change_outcome", targetType: "shot", targetId: "shot-1", sourceTimestampUs: 12_340_000, sourceEvidenceIds: ["shot-ev"] }));
  });


  it("keeps the local draft on 409 and offers explicit rebase or discard", () => {
    const rebase = vi.fn();
    const discard = vi.fn();
    render(<CorrectionEditor matchId="match-1" item={item} reportRevision={4} pending={false} conflictRevision={5} onSubmit={vi.fn()} onRebase={rebase} onDiscard={discard} />);
    const reason = screen.getByLabelText("Reason");
    fireEvent.change(reason, { target: { value: "Keep this exact draft" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Revision 5");
    expect(reason).toHaveValue("Keep this exact draft");
    fireEvent.click(screen.getByRole("button", { name: "Rebase onto revision 5" }));
    expect(rebase).toHaveBeenCalled();
    expect(reason).toHaveValue("Keep this exact draft");
    fireEvent.click(screen.getByRole("button", { name: "Discard local draft" }));
    expect(discard).toHaveBeenCalled();
  });

  it("disables only save while pending and labels the optimistic state honestly", () => {
    render(<CorrectionEditor matchId="match-1" item={item} reportRevision={4} pending onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Saving correction…" })).toBeDisabled();
    expect(screen.getByLabelText("Reason")).toBeEnabled();
    expect(screen.getByText("Saving a new revision. The current report stays unchanged until saving finishes.")).toBeInTheDocument();
  });
  it("maps every server issue to one centralized applicable command", () => {
    const view = render(<CorrectionEditor matchId="match-1" item={{ ...item, id: "type", issue: "shot_type" }} reportRevision={5} pending={false} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("Correction")).toHaveValue("change_shot_type");
    view.rerender(<CorrectionEditor matchId="match-1" item={{ ...item, id: "identity", issue: "identity" }} reportRevision={5} pending={false} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("Correction")).toHaveValue("change_hitter");
    view.rerender(<CorrectionEditor matchId="match-1" item={{ ...item, id: "seam", issue: "ball_seam" }} reportRevision={5} pending={false} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("Correction")).toHaveValue("ball_control_point");
  });

  it("offers only server canonical shot and outcome values and submits real payloads", () => {
    const submit = vi.fn();
    const view = render(
      <CorrectionEditor
        matchId="match-1"
        item={{ ...item, id: "taxonomy-shot", issue: "shot_type" }}
        reportRevision={5}
        pending={false}
        onSubmit={submit}
      />,
    );
    const shotSelect = screen.getByLabelText("Primary shot") as HTMLSelectElement;
    expect(Array.from(shotSelect.options, (option) => option.value)).toEqual([
      "unknown",
      "serve",
      "drive",
      "boast",
      "drop",
      "lob",
      "kill",
    ]);
    fireEvent.change(shotSelect, { target: { value: "kill" } });
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Verified kill" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        commandType: "change_shot_type",
        payload: { shot_type: "kill" },
      }),
    );

    view.rerender(
      <CorrectionEditor
        matchId="match-1"
        item={{
          ...item,
          id: "taxonomy-outcome",
          issue: "outcome",
          summary: { ...item.summary, outcome: "continuation" },
        }}
        reportRevision={5}
        pending={false}
        onSubmit={submit}
      />,
    );
    const outcomeSelect = screen.getByLabelText("Outcome") as HTMLSelectElement;
    expect(Array.from(outcomeSelect.options, (option) => option.value)).toEqual([
      "unknown",
      "in_play",
      "winner",
      "error",
      "let",
      "stroke",
    ]);
    expect(outcomeSelect).toHaveValue("in_play");
    fireEvent.change(screen.getByLabelText("Reason"), {
      target: { value: "Rally continued" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    expect(submit).toHaveBeenLastCalledWith(
      expect.objectContaining({
        commandType: "change_outcome",
        payload: { outcome: "in_play" },
      }),
    );
  });

  it("requires an explicit candidate selection or rejection for reapplication conflicts", () => {
    const resolve = vi.fn();
    const seekConflict = vi.fn();
    render(<CorrectionEditor matchId="match-1" item={item} reportRevision={5} pending={false} onSubmit={vi.fn()} reapplicationConflicts={[{ correctionId: "correction-1", reason: "Evidence anchors changed", candidateIds: ["shot-7", "shot-8"], candidates: [{ candidateId: "shot-7", timestampUs: 14_000_000, evidenceStartTimestampUs: 13_950_000, evidenceEndTimestampUs: 14_050_000, evidenceStartFrameIndex: 418, evidenceEndFrameIndex: 421, evidenceIds: ["ev-7"], label: "drive at 14 seconds" }, { candidateId: "shot-8", timestampUs: 15_000_000, evidenceStartTimestampUs: 14_950_000, evidenceEndTimestampUs: 15_050_000, evidenceStartFrameIndex: 448, evidenceEndFrameIndex: 451, evidenceIds: ["ev-8"], label: "drop at 15 seconds" }] }]} onResolveConflict={resolve} onSeekConflictEvidence={seekConflict} />);
    const select = screen.getByRole("button", { name: "Select candidate" });
    expect(select).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: /drop at 15 seconds/i }));
    fireEvent.click(select);
    expect(resolve).toHaveBeenCalledWith("correction-1", "shot-8", "select");
    fireEvent.click(screen.getAllByRole("button", { name: "Seek candidate evidence" })[1]);
    expect(seekConflict).toHaveBeenCalledWith(15_000_000, "ev-8");
    fireEvent.click(screen.getByRole("button", { name: "Reject reapplication" }));
    expect(resolve).toHaveBeenCalledWith("correction-1", null, "reject");
  });

});
