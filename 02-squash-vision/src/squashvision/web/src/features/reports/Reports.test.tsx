// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../api/types.generated";
import { jsonResponse, renderApp } from "../../test-utils";
import { CoachingReport } from "./CoachingReport";
import { ErrorsReport } from "./ErrorsReport";
import { HeadToHeadReport } from "./HeadToHeadReport";
import { MovementReport } from "./MovementReport";
import { OverviewReport } from "./OverviewReport";
import { RalliesReport } from "./RalliesReport";
import { ShotsReport } from "./ShotsReport";
import { TrajectoryReport } from "./TrajectoryReport";

type MatchReport = components["schemas"]["MatchReport"];

const report = makeReport({
  overview: {
    rally_count: 2, timed_rally_count: 2, shot_count: 5, winner_count: 1, reviewed_error_count: 1,
    active_duration_s: 18, rest_duration_s: 12, work_rest_ratio: { available: true, value: 1.5 },
    average_rally_s: 9, longest_rally_s: 11,
    review_completion: { available: true, value: 0.5 }, evidence_quality: { available: true, value: 0.8 },
  },
  shots: { total_count: 5, aggregate_contract: "complete", players: {
    near: { count: 3, types: { drive: { count: 2, share: 2 / 3 }, volley: { count: 1, share: 1 / 3 } }, outcomes: { winner: 1 }, sides: { left: 2, right: 1 }, volleys: 1 },
    far: { count: 2, types: { drive: { count: 2, share: 1 } }, outcomes: { error: 1 }, sides: { right: 2 }, volleys: 0 },
    unknown: { count: 0, types: {}, outcomes: {}, sides: {}, volleys: 0 },
  }, items: [
    { prediction_id: "shot-1", timestamp_us: 3_000_000, player: "near", primary_type: "drive", is_volley: false, side: "left", outcome: "winner", evidence_ids: ["shot-1"] },
    { prediction_id: "shot-2", timestamp_us: 5_000_000, player: "near", primary_type: "drive", is_volley: false, side: "left", outcome: "in_play", evidence_ids: ["shot-2"] },
    { prediction_id: "shot-3", timestamp_us: 7_000_000, player: "near", primary_type: "volley", is_volley: true, side: "right", outcome: "in_play", evidence_ids: ["shot-3"] },
    { prediction_id: "shot-4", timestamp_us: 9_000_000, player: "far", primary_type: "drive", is_volley: false, side: "right", outcome: "in_play", evidence_ids: ["shot-4"] },
    { prediction_id: "shot-5", timestamp_us: 11_000_000, player: "far", primary_type: "drive", is_volley: false, side: "right", outcome: "error", evidence_ids: ["shot-5"] },
  ] },
  rallies: { timing_unavailable_count: 0, items: [
    { prediction_id: "rally-1", ordinal: 1, start_timestamp_us: 2_000_000, end_timestamp_us: 12_000_000, timing_available: true, shot_ids: ["shot-1", "shot-2"], outcome: "winner", representative_event_id: "shot-2", representative_timestamp_us: 12_000_000, source_evidence_ids: ["rally-1"] },
  ] },
  movement: { active_calibration_revision: 3, heatmap: { court_width_m: 6.4, court_length_m: 9.75, columns: 4, rows: 6, counts: [[1, 2, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0], [0, 0, 2, 0], [0, 0, 0, 1], [0, 0, 0, 0]], excluded: { stale_calibration: 2 } }, distance_m: { available: true, value: 42.4 }, t_recovery: { sample_count: 2, median_seconds: { available: true, value: 1.4 }, samples: [] } },
  errors: { objective_count: 2, objective_event_ids: ["shot-2", "shot-5"], reviewed_subjective_count: 1, reviewed_subjective_ids: ["error-1"], unreviewed_candidate_count: 1, unreviewed_candidate_ids: ["error-2"], items: [{ id: "shot-5", category: "objective", status: "accepted", counted: true, side: "right", rally_id: "rally-1", timestamp_us: 11_000_000, evidence_ids: ["shot-5"] }, { id: "error-1", category: "subjective", status: "accepted", counted: true, side: "left", rally_id: "rally-1", timestamp_us: 9_000_000, evidence_ids: ["error-1"] }, { id: "error-rejected", category: "subjective", status: "rejected", counted: false, side: "right", rally_id: "rally-1", timestamp_us: 10_000_000, evidence_ids: ["error-rejected"] }] },
  trajectory: { average_speed_m_s: { available: false, reason: "floor_only_calibration" }, measured_shot_count: 0, unavailable_reasons: { floor_only_calibration: 5 }, image_trajectory: { availability: { available: false, reason: "image_space_provenance_not_published" }, items: [] }, court_trajectory: { availability: { available: true, reason: null }, calibration_revision: 3, items: [{ shot_id: "shot-1", timestamp_us: 3_000_000, x_m: 2, y_m: 5, provenance: "canonical_court_contact", uncertainty_m: null, evidence_ids: ["shot-1"] }] }, control_point_exclusions: { reconstructed: 1 } },
  head_to_head: { near: { shots: 3, volleys: 1, winners: 1, errors: 0, movement: { distance_m: { available: true, value: 21.2 }, sample_count: 4 } }, far: { shots: 2, volleys: 0, winners: 0, errors: 1, movement: { distance_m: { available: true, value: 18.5 }, sample_count: 3 } } },
  coaching: { findings: [{ rule: "boast_overuse", subject: "near", sample_count: 10, measured: 0.4, baseline: 0.3, comparator: "greater_than", supporting_event_ids: ["shot-1", "shot-3"], evidence: "near used boasts on 40.0% of 10 shots, above the 30.0% threshold." }] },
});

const seek = vi.fn();
afterEach(() => { cleanup(); seek.mockClear(); vi.unstubAllGlobals(); });

describe("evidence-linked report views", () => {
  it("renders one compact overview with one contextual evidence action", () => {
    const view = render(<OverviewReport report={report} onSeekEvidence={seek} />);
    expect(screen.getByRole("region", { name: "Results" })).toHaveTextContent("Rallies");
    expect(screen.getByRole("region", { name: "Rally timing" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Analysis quality" })).toHaveTextContent("Evidence quality");
    const actions = screen.getAllByRole("button", { name: "Open overview evidence" });
    expect(actions).toHaveLength(1);
    fireEvent.click(actions[0]);
    expect(seek).toHaveBeenCalledWith("overview-evidence");
    const overview = report.sections.overview;
    if (overview === undefined) throw new Error("overview fixture missing");
    view.rerender(<OverviewReport report={{ ...report, sections: { ...report.sections, overview: { ...overview, evidenceIds: [] } } }} onSeekEvidence={seek} />);
    expect(screen.queryByRole("button", { name: "Open overview evidence" })).not.toBeInTheDocument();
  });
  it("does not draw an active/rest pulse when either duration is missing", () => {
    const partial = makeReport({ overview: { rally_count: 1, timed_rally_count: null, shot_count: 2, active_duration_s: 8, rest_duration_s: null, work_rest_ratio: { available: false, reason: "no_rest_duration" }, review_completion: { available: false, reason: "no_candidates" }, evidence_quality: { available: true, value: 1 } } });
    render(<OverviewReport report={partial} onSeekEvidence={seek} />);
    expect(screen.queryByLabelText(/Rally timing:/i)).not.toBeInTheDocument();
    expect(screen.getByText("Rally timing unavailable")).toBeInTheDocument();
    expect(screen.getAllByText(/sample unavailable/i).length).toBeGreaterThan(0);
  });


  it("keeps primary shot types separate from independent volley counts and filters published sides", () => {
    render(<ShotsReport report={report} onSeekEvidence={seek} />);
    expect(screen.getAllByText("Volley count")).toHaveLength(2);
    expect(screen.getByRole("row", { name: /Player A.*drive.*2/i })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Player A.*volley.*1/i })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: "Independent volley flag count 0 for far" })).toHaveTextContent("0");
    fireEvent.change(within(screen.getByRole("group", { name: "Shot filters" })).getByRole("combobox", { name: "Side" }), { target: { value: "left" } });
    expect(screen.queryByRole("row", { name: /Player B/i })).not.toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Player A.*Side: left.*2/i })).toBeInTheDocument();
  });
  it("separates shot dimensions and exposes measured classification coverage", () => {
    render(<ShotsReport report={report} onSeekEvidence={seek} />);
    expect(screen.getByRole("region", { name: "Primary type" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Outcome" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Side" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Volley flag" })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Shot classification coverage" })).toHaveTextContent("0 unknown");
    expect(screen.getByLabelText("Player A drive share")).toHaveAttribute("value", String(2 / 3));
  });

  it("does not coerce missing shot counts or volley fields to zero", () => {
    const partial = makeReport({ shots: { players: { near: { types: { drive: { share: 1 } }, outcomes: {} } } } });
    render(<ShotsReport report={partial} onSeekEvidence={seek} />);
    expect(screen.getByRole("row", { name: /Player A.*drive.*Unavailable/i })).toBeInTheDocument();
    expect(screen.queryByText("Volley count")).not.toBeInTheDocument();
  });

  it("binds every signed shot page to the selected historical report revision and preserves canonical shot-id order", async () => {
    const complete = makeReport({});
    complete.sections.rallies = {
      ...report.sections.rallies,
      payload: {
        items: [
          { prediction_id: "rally-1", ordinal: 1, start_timestamp_us: 2_000_000, end_timestamp_us: 12_000_000, timing_available: true, shot_ids: ["shot-1", "shot-2"], outcome: "winner", representative_event_id: "shot-2", source_evidence_ids: ["rally-1"] },
          { prediction_id: "rally-2", ordinal: 2, start_timestamp_us: 14_000_000, end_timestamp_us: 20_000_000, timing_available: true, shot_ids: ["shot-3", "missing-shot"], outcome: "error", representative_event_id: "shot-3", source_evidence_ids: ["rally-2"] },
        ],
      },
    };
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      requests.push(url);
      const query = new URL(url, "http://local").searchParams;
      if (query.get("reportRevision") !== "4") {
        return Promise.resolve(jsonResponse({
          predictionRevision: 8,
          nextCursor: null,
          items: [{ ...shot("current-shot", "rally-1", 4_000_000, [2, 3], "near", "drive"), predictionRevision: 8 }],
        }));
      }
      const cursor = query.get("cursor");
      return Promise.resolve(jsonResponse({
        predictionRevision: 7,
        nextCursor: cursor === null ? "signed-page-2" : null,
        items: cursor === null
          ? [shot("shot-2", "rally-1", 3_000_000, null, "far", "drop")]
          : [shot("shot-1", "rally-1", 9_000_000, [1, 2], "near", "drive"), shot("shot-3", "rally-2", 15_000_000, [5, 8], "near", "kill")],
      }));
    }));

    renderApp(<RalliesReport report={complete} matchId="match-1" durationUs={30_000_000} onSeekEvidence={seek} />);

    expect(await screen.findByRole("tablist", { name: "Rally index" })).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: /Rally 1.*winner/i })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests.every((url) => new URL(url, "http://local").searchParams.get("reportRevision") === "4")).toBe(true);
    await screen.findByRole("button", { name: /^Shot 2, Player B, DROP/ });
    const detail = screen.getByRole("article");
    expect(within(detail).getAllByRole("button", { name: /Shot [12],/ }).slice(-2).map((item) => item.getAttribute("aria-label"))).toEqual([
      expect.stringMatching(/^Shot 1, Player A, DRIVE/),
      expect.stringMatching(/^Shot 2, Player B, DROP/),
    ]);
    fireEvent.click(screen.getByRole("tab", { name: /Rally 2.*error/i }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText(/1 shot unavailable for Rally 2/i)).toBeInTheDocument();
  });

  it("retains partial shot pages and exposes a repeated signed cursor", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse({
      predictionRevision: 7,
      nextCursor: "signed-repeat",
      items: [shot("shot-1", "rally-1", 3_000_000, [1, 2], "near", "drive")],
    }))));
    renderApp(<RalliesReport report={report} matchId="match-1" durationUs={30_000_000} onSeekEvidence={seek} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Shot evidence incomplete");
    expect(screen.getByRole("article")).toBeInTheDocument();
    expect(screen.getByText(/Some shots could not be loaded/i)).toBeInTheDocument();
  });

  it("gates the movement heatmap on an active calibration", () => {
    const unavailable = makeReport({ movement: { availability: { available: false, reason: "missing_calibration" } } });
    const view = render(<MovementReport report={unavailable} onSeekEvidence={seek} />);
    expect(screen.queryByRole("img", { name: /court movement heatmap/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Calibrate the court/i)).toBeInTheDocument();
    view.rerender(<MovementReport report={report} onSeekEvidence={seek} />);
    expect(screen.getByRole("img", { name: /court movement heatmap/i })).toBeInTheDocument();
    expect(screen.getByText(/2 excluded.*stale calibration/i)).toBeInTheDocument();
  });
  it("does not draw a finished heatmap when measured occupancy is empty", () => {
    const emptyMovement = makeReport({ movement: {
      active_calibration_revision: 3,
      heatmap: { rows: 2, columns: 2, counts: [[0, 0], [0, 0]], excluded: { stale_calibration: 4 } },
      distance_m: { available: false, reason: "insufficient_sample" },
      t_recovery: { sample_count: 0, median_seconds: { available: false, reason: "no_recovery_samples" } },
    } });
    render(<MovementReport report={emptyMovement} onSeekEvidence={seek} />);
    expect(screen.queryByRole("img", { name: /court movement heatmap/i })).not.toBeInTheDocument();
    expect(screen.getByText("0 measured positions")).toBeInTheDocument();
    expect(screen.getByText(/4 excluded.*stale calibration/i)).toBeInTheDocument();
    expect(screen.getByText(/no recovery samples/i)).toBeInTheDocument();
  });

  it("groups confirmed, review, and rejected errors without counting rejected rows", () => {
    const grouped = makeReport({ errors: {
      objective_count: 2,
      reviewed_subjective_count: 1,
      unreviewed_candidate_count: 1,
      items: [
        { id: "error-confirmed", category: "objective", status: "accepted", counted: true, side: "left", rally_id: "rally-1", evidence_ids: ["confirmed-evidence"] },
        { id: "error-2", category: "subjective", status: "pending", counted: false, side: "right", rally_id: "rally-2", evidence_ids: ["review-evidence"] },
        { id: "error-rejected", category: "subjective", status: "rejected", counted: false, side: "right", rally_id: "rally-1", evidence_ids: ["rejected-evidence"] },
      ],
    } });
    render(<ErrorsReport report={grouped} onSeekEvidence={seek} />);
    expect(screen.getByRole("region", { name: "Confirmed errors" })).toHaveTextContent("3");
    expect(screen.getByRole("region", { name: "Needs review" })).toHaveTextContent("1");
    expect(screen.getByRole("region", { name: "Rejected errors" })).toHaveTextContent("1");
    expect(screen.getByText("error-rejected").closest("li")).toHaveTextContent("Not counted");
    expect(screen.getByRole("button", { name: /Review evidence error-2/i })).toBeEnabled();
  });

  it("states why metric speed is unavailable instead of plotting zero", () => {
    render(<TrajectoryReport report={report} onSeekEvidence={seek} />);
    expect(screen.getByText(/Metric ball speed unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/floor only calibration/i)).toBeInTheDocument();
    expect(screen.queryByText("0 m\/s")).not.toBeInTheDocument();
    expect(screen.getByText(/Image trajectory unavailable/i)).toBeInTheDocument();
  });
  it("plots only image-space points with explicit provenance and covariance", () => {
    const imageReport = makeReport({ trajectory: { average_speed_m_s: { available: true, value: 31.5 }, measured_shot_count: 1, image_trajectory: { availability: { available: true, reason: null }, items: [{ shot_id: "shot-image", x_px: 640, y_px: 360, source_width: 1280, source_height: 720, provenance: "observed", covariance: [[4, 0], [0, 9]], evidence_ids: ["ball-image"] }] }, court_trajectory: { availability: { available: false, reason: "missing_calibration" }, calibration_revision: null, items: [] }, control_point_exclusions: {} } });
    render(<TrajectoryReport report={imageReport} onSeekEvidence={seek} />);
    expect(screen.getByRole("img", { name: "Image-space ball trajectory" })).toBeInTheDocument();
    expect(screen.getAllByText(/covariance uncertainty/i).length).toBeGreaterThan(0);
  });

  it("marks image trajectories unavailable when published source dimensions are missing", () => {
    const missingDimensions = makeReport({ trajectory: {
      image_trajectory: {
        availability: { available: true, reason: null },
        items: [{ shot_id: "shot-image", x_px: 640, y_px: 360, provenance: "observed", covariance: [[4, 0], [0, 9]], evidence_ids: ["ball-image"] }],
      },
      court_trajectory: { availability: { available: false, reason: "missing_calibration" }, calibration_revision: null, items: [] },
    } });
    render(<TrajectoryReport report={missingDimensions} onSeekEvidence={seek} />);

    expect(screen.queryByRole("img", { name: "Image-space ball trajectory" })).not.toBeInTheDocument();
    expect(screen.getAllByText(/source dimensions missing or invalid/i)).toHaveLength(2);
  });

  it("marks image trajectories unavailable when published source dimensions disagree", () => {
    const inconsistentDimensions = makeReport({ trajectory: {
      image_trajectory: {
        availability: { available: true, reason: null },
        items: [
          { shot_id: "shot-image-1", x_px: 640, y_px: 360, source_width: 1280, source_height: 720, provenance: "observed", covariance: [[4, 0], [0, 9]], evidence_ids: ["ball-image-1"] },
          { shot_id: "shot-image-2", x_px: 650, y_px: 370, source_width: 1920, source_height: 1080, provenance: "observed", covariance: [[4, 0], [0, 9]], evidence_ids: ["ball-image-2"] },
        ],
      },
      court_trajectory: { availability: { available: false, reason: "missing_calibration" }, calibration_revision: null, items: [] },
    } });
    render(<TrajectoryReport report={inconsistentDimensions} onSeekEvidence={seek} />);

    expect(screen.queryByRole("img", { name: "Image-space ball trajectory" })).not.toBeInTheDocument();
    expect(screen.getAllByText(/source dimensions inconsistent/i)).toHaveLength(2);
  });


  it("aligns labeled players with measured deltas without declaring a winner", () => {
    render(<HeadToHeadReport report={report} onSeekEvidence={seek} />);
    expect(screen.getByRole("columnheader", { name: /A.*Player A/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /B.*Player B/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Measured delta A−B" })).toBeInTheDocument();
    expect(screen.queryByText(/wins match/i)).not.toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Volleys.*1.*\+1.*0/i })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Movement.*21\.2 m.*\+2\.7 m.*18\.5 m/i })).toBeInTheDocument();
  });

  it("renders only backend coaching findings with measured evidence and every public link", () => {
    render(<CoachingReport report={report} onSeekEvidence={seek} />);
    expect(screen.getByText("Measured value").parentElement).toHaveTextContent("40.0%");
    expect(screen.getByText("Comparator").parentElement).toHaveTextContent("greater than");
    expect(screen.getByText("Baseline").parentElement).toHaveTextContent("30.0%");
    expect(screen.getByText("Threshold").parentElement).toHaveTextContent("Unavailable");
    expect(screen.getByText(/sample.*10/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Seek.*shot/i })).toHaveLength(2);
    expect(screen.queryByText(/try to/i)).not.toBeInTheDocument();
  });

  it("renders measured value, baseline, and threshold as independent coaching facts", () => {
    const differingValues = makeReport({ coaching: { findings: [{
      rule: "boast_overuse",
      subject: "near",
      sample_count: 10,
      measured: 0.4,
      baseline: 0.3,
      threshold: 0.25,
      comparator: "greater_than",
      supporting_event_ids: [],
    }] } });
    render(<CoachingReport report={differingValues} onSeekEvidence={seek} />);

    expect(screen.getByText("Measured value").parentElement).toHaveTextContent("40.0%");
    expect(screen.getByText("Baseline").parentElement).toHaveTextContent("30.0%");
    expect(screen.getByText("Threshold").parentElement).toHaveTextContent("25.0%");
    expect(screen.getByText("Comparator").parentElement).toHaveTextContent("greater than");
  });

  it("uses a precise unavailable state when a coaching finding lacks measured support", () => {
    const unavailableValues = makeReport({ coaching: { findings: [{
      rule: "boast_overuse",
      subject: "near",
      comparator: null,
      supporting_event_ids: [],
    }] } });
    render(<CoachingReport report={unavailableValues} onSeekEvidence={seek} />);
    expect(screen.getByText("Finding incomplete")).toBeInTheDocument();
    expect(screen.getByText(/measured value, comparison, sample count, and threshold or baseline/i)).toBeInTheDocument();
    expect(screen.queryByText("Measured finding")).not.toBeInTheDocument();
  });

  it("gives every unavailable section an exact prerequisite and action", () => {
    const unavailable = makeReport({ shots: { availability: { available: false, reason: "processing_incomplete" } } });
    render(<ShotsReport report={unavailable} onSeekEvidence={seek} />);
    expect(screen.getByText(/Finish processing/i)).toBeInTheDocument();
  });
  it("keeps every report section unavailable when processing has not published evidence", () => {
    const unavailable = makeReport({});
    const views = [
      ["Overview", OverviewReport],
      ["Shots", ShotsReport],
      ["Movement", MovementReport],
      ["Errors", ErrorsReport],
      ["Trajectory", TrajectoryReport],
      ["Head-to-head", HeadToHeadReport],
      ["Coaching", CoachingReport],
    ] as const;
    for (const [title, View] of views) {
      const view = render(<View report={unavailable} onSeekEvidence={seek} />);
      expect(screen.getByRole("heading", { name: `${title} unavailable` })).toBeInTheDocument();
      expect(screen.getByText(/No sufficient sample/i)).toBeInTheDocument();
      view.unmount();
    }
    const rallyView = renderApp(<RalliesReport report={unavailable} matchId="match-1" durationUs={30_000_000} onSeekEvidence={seek} />);
    expect(screen.getByRole("heading", { name: "Rallies unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/No sufficient sample/i)).toBeInTheDocument();
    rallyView.unmount();
  });

});

function makeReport(payloads: Record<string, Record<string, unknown>>): MatchReport {
  const names = ["overview", "shots", "rallies", "movement", "errors", "trajectory", "head_to_head", "coaching", "review"];
  const sections: MatchReport["sections"] = {};
  for (const name of names) {
    sections[name] = { schemaVersion: 1, payload: payloads[name] ?? { availability: { available: false, reason: "insufficient_sample" } }, evidenceIds: [`${name}-evidence`], hash: `${name}-hash`, dependencyHash: `${name}-dependency` };
  }
  return { matchId: "match-1", revision: 4, predictionRevision: 7, calibrationRevision: 3, sections };
}

function shot(id: string, rallyId: string, timestampUs: number, contact: [number, number] | null, hitter: "near" | "far", shotKind: "drive" | "drop" | "kill") {
  return {
    id,
    timestampUs,
    predictionRevision: 7,
    rallyId,
    hitter,
    shotKind,
    isVolley: false,
    outcome: shotKind === "kill" ? "winner" : "in_play",
    contact,
    speedMS: null,
    speedUnavailableReason: null,
    sourceEvidenceIds: [`evidence-${id}`],
  };
}
