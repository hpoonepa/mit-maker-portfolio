import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, request } from "../../api/client";
import {
  decodeCalibration,
  decodeHealth,
  decodeJob,
  decodeMatchDetail,
  decodeModels,
  decodeProposal,
} from "../../api/decoders";
import type {
  CalibrationKeypoint,
  CalibrationProposal,
  CalibrationSize,
  ProcessingProfile,
} from "../../api/decoders";
import type { components } from "../../api/types.generated";
import { AppShell } from "../../components/AppShell";
import { CourtOverlayEditor } from "./CourtOverlayEditor";
import { PlayingAreaSetup } from "./PlayingAreaSetup";

const setupKeys = {
  match: (matchId: string) => ["matches", matchId] as const,
  calibration: (matchId: string) => ["matches", matchId, "calibration"] as const,
  health: ["health"] as const,
  models: ["models"] as const,
};

export function recommendedProfile(platform: string, architecture: string): ProcessingProfile {
  const machine = `${platform} ${architecture}`.toLowerCase();
  return machine.includes("arm64") || machine.includes("aarch64")
    ? "maximum"
    : "balanced";
}

function equalPoints(left: CalibrationKeypoint[], right: CalibrationKeypoint[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((point, index) => {
    const other = right[index];
    return other !== undefined && point.label === other.label && point.image.x === other.image.x && point.image.y === other.image.y;
  });
}

const PROFILE_COPY: Record<ProcessingProfile, string> = {
  fast: "Fast · pose and ball sampling for a quicker directional result",
  balanced: "Balanced · full player tracks with standard ball sampling",
  maximum: "Maximum · dense player and ball passes with full event classification",
};

export function MatchSetup() {
  const { matchId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [keypoints, setKeypoints] = useState<CalibrationKeypoint[]>([]);
  const [proposal, setProposal] = useState<CalibrationProposal | null>(null);
  const [draftFrameSize, setDraftFrameSize] = useState<CalibrationSize | null>(null);
  const [conflict, setConflict] = useState(false);
  const [profile, setProfile] = useState<ProcessingProfile>("balanced");
  const [ballInputMode, setBallInputMode] = useState<components["schemas"]["BallInputMode"]>("original");
  const profileChosen = useRef(false);
  const [proposalTimestampSeconds, setProposalTimestampSeconds] = useState(0);
  const [imageTrackingReady, setImageTrackingReady] = useState(false);

  const match = useQuery({
    queryKey: setupKeys.match(matchId),
    enabled: matchId !== "",
    queryFn: ({ signal }) => request("/api/v1/matches/{match_id}", "get", {
      path: { match_id: matchId }, signal, decode: decodeMatchDetail,
    }),
  });
  const shouldFetchCalibration = match.data?.calibrationRevision !== null
    && match.data?.calibrationRevision !== undefined;
  const calibration = useQuery({
    queryKey: setupKeys.calibration(matchId),
    enabled: matchId !== "" && shouldFetchCalibration,
    retry: false,
    queryFn: ({ signal }) => request("/api/v1/matches/{match_id}/calibration", "get", {
      path: { match_id: matchId }, signal, decode: decodeCalibration,
    }),
  });
  const health = useQuery({
    queryKey: setupKeys.health,
    queryFn: ({ signal }) => request("/api/v1/health", "get", {
      signal,
      decode: decodeHealth,
    }),
  });
  const models = useQuery({
    queryKey: setupKeys.models,
    queryFn: ({ signal }) => request("/api/v1/models", "get", { signal, decode: decodeModels }),
  });
  const selectedProfile: ProcessingProfile = (
    !profileChosen.current && health.data?.worker.nativeAppleSilicon === true
  ) ? "maximum" : profile;


  useEffect(() => {
    if (calibration.data !== undefined) {
      setKeypoints(calibration.data.keypoints);
      setProposal((current) => current ?? {
        confidence: calibration.data.result.confidence,
        intersectionCount: calibration.data.keypoints.length,
        lineCount: calibration.data.keypoints.length,
        visibleSurfaces: [],
        warnings: calibration.data.result.warnings,
        keypoints: calibration.data.keypoints,
      });
    }
  }, [calibration.data]);


  const propose = useMutation({
    mutationFn: () => {
      const timestampSeconds = videoRef.current?.currentTime ?? 0;
      setProposalTimestampSeconds(timestampSeconds);
      return request("/api/v1/matches/{match_id}/calibration/propose", "post", {
        path: { match_id: matchId },
        body: { timestampSeconds },
        decode: decodeProposal,
      });
    },
    onSuccess: (nextProposal) => {
      setProposal(nextProposal);
      setKeypoints(nextProposal.keypoints);
      setConflict(false);
    },
  });

  const save = useMutation({
    mutationFn: () => {
      const frameSize = calibration.data?.frameSize ?? draftFrameSize;
      if (frameSize === null) {
        throw new ApiError(409, "calibration_frame_unavailable", "The video frame size is unavailable", null, "client");
      }
      const savedKeypoints = calibration.data?.keypoints ?? [];
      const activeKeypoints = keypoints.length === 0 ? savedKeypoints : keypoints;
      return request("/api/v1/matches/{match_id}/calibration", "put", {
        path: { match_id: matchId },
        body: {
          expectedRevision: calibration.data?.revision ?? 0,
          frameSize,
          keypoints: activeKeypoints,
        },
        decode: decodeCalibration,
      });
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(setupKeys.calibration(matchId), saved);
      void queryClient.invalidateQueries({ queryKey: ["matches", matchId, "tracking-stats"] });
      void queryClient.invalidateQueries({ queryKey: ["matches", matchId, "tracking-timeline"] });
      setKeypoints(saved.keypoints);
      setConflict(false);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) setConflict(true);
    },
  });

  const start = useMutation({
    mutationFn: (mode: "calibrated" | "image" = "calibrated") => {
      const requiredMissing = models.data?.some((model) => model.required && model.state !== "ready") ?? true;
      if (requiredMissing) {
        throw new ApiError(503, "required_models_unavailable", "Required models are not ready", null, "client");
      }
      const activeKeypoints = keypoints.length === 0 ? calibration.data?.keypoints ?? [] : keypoints;
      if (mode === "image" && !imageTrackingReady) {
        throw new ApiError(409, "playing_area_unsaved", "Save the playing area before tracking", null, "client");
      }
      if (mode === "calibrated" && (calibration.data?.result.calibrated !== true || !equalPoints(activeKeypoints, calibration.data.keypoints))) {
        throw new ApiError(409, "calibration_unsaved", "Save a valid calibration before analysis", null, "client");
      }
      return request("/api/v1/matches/{match_id}/jobs", "post", {
        path: { match_id: matchId },
        body: { profile: selectedProfile, ballInputMode },
        decode: decodeJob,
      });
    },
    onSuccess: async (job) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: setupKeys.match(matchId) }),
        queryClient.invalidateQueries({ queryKey: ["jobs", job.id] }),
      ]);
      navigate(`/matches/${matchId}/processing`);
    },
  });

  const profilePicker = <><fieldset className="profile-picker">
    <legend>Processing profile</legend>
    {(Object.keys(PROFILE_COPY) as ProcessingProfile[]).map((option) => <label key={option}>
      <input type="radio" name="profile" value={option} checked={selectedProfile === option} disabled={option === "fast" && ballInputMode === "inverted"} onChange={() => { profileChosen.current = true; setProfile(option); }} />
      <span>{PROFILE_COPY[option]}{option === "maximum" ? " · Recommended on Apple silicon" : ""}</span>
    </label>)}
  </fieldset>
  <fieldset className="profile-picker" disabled={start.isPending}>
    <legend>Ball contrast</legend>
    <label>
      <input type="radio" name="ball-contrast" value="original" checked={ballInputMode === "original"} onChange={() => setBallInputMode("original")} />
      <span>Standard</span>
    </label>
    <label>
      <input type="radio" name="ball-contrast" value="inverted" checked={ballInputMode === "inverted"} onChange={() => {
        if (selectedProfile === "fast") { profileChosen.current = true; setProfile("balanced"); }
        setBallInputMode("inverted");
      }} />
      <span>Dark ball on light court</span>
    </label>
    {ballInputMode === "inverted" ? <p>Dark-ball tracking requires Balanced or Maximum.</p> : null}
  </fieldset></>;

  if (match.isPending || (shouldFetchCalibration && calibration.isPending) || models.isPending || health.isPending) {
    return <AppShell matchId={matchId} active="setup"><div className="setup-skeleton" aria-label="Loading setup"><header><span /><span /></header><div className="setup-skeleton-workspace"><div className="setup-skeleton-frame" /><aside><span /><span /><span /><span /></aside></div><p className="sr-only">Loading court instruments…</p></div></AppShell>;
  }
  if (match.isError) {
    return <AppShell matchId={matchId} active="setup"><div className="action-state" role="alert"><h1>Match setup unavailable</h1><button type="button" onClick={() => void match.refetch()}>Retry match</button></div></AppShell>;
  }
  if (models.isError || models.data === undefined) {
    return (
      <AppShell matchId={matchId} active="setup">
        <div className="action-state" role="alert">
          <h1>Model readiness unavailable</h1>
          <p>Analysis cannot start until the required local model manifest is known.</p>
          <button type="button" onClick={() => void models.refetch()}>Retry model readiness</button>
          <Link className="button-secondary" to="/">Install local models from the match ledger</Link>
          <button type="button" className="button-primary" disabled>Start analysis</button>
        </div>
      </AppShell>
    );
  }
  const calibrationMissing = (calibration.data === undefined && match.data.calibrationRevision === null)
    || (calibration.isError && calibration.error instanceof ApiError && calibration.error.status === 404);
  const playingAreaPanel = <PlayingAreaSetup key={matchId} matchId={matchId}
    modelsReady={!models.data.some((model) => model.required && model.state !== "ready")}
    starting={start.isPending} startError={start.isError && start.variables === "image" ? start.error instanceof ApiError ? start.error.message : "Tracking could not start. Try again." : null}
    profilePicker={calibrationMissing ? profilePicker : undefined}
    onReadinessChange={setImageTrackingReady} onStart={() => start.mutate("image")} />;
  if ((calibration.isError && !calibrationMissing) || (calibration.data === undefined && !calibrationMissing)) {
    return (
      <AppShell matchId={matchId} active="setup">
        <div className="action-state" role="alert">
          <h1>Calibration unavailable</h1>
          <p>The saved calibration response could not be used.</p>
          <button type="button" onClick={() => void calibration.refetch()}>Retry calibration</button>
        </div>
      </AppShell>
    );
  }
  if (calibrationMissing) {
    const draftReady = proposal !== null && draftFrameSize !== null;
    return (
      <AppShell matchId={matchId} active="setup">
        <header className="page-heading setup-heading"><h1>{match.data.title} setup</h1></header>
        {playingAreaPanel}
        <details className="setup-calibration-details">
          <summary>Court calibration (optional)</summary>
        <header className="page-heading setup-heading">
          <h2>Court measurements</h2>
          <p>Scrub to a clear full-court frame, ask for a proposal, then drag each signal point onto the court corner before saving.</p>
          <ol className="setup-steps" aria-label="Court setup steps">
            <li data-state={proposal === null ? "current" : "complete"}>Choose a frame</li>
            <li data-state={proposal === null ? "upcoming" : "current"}>Adjust the points</li>
            <li data-state="upcoming">Save the court</li>
          </ol>
        </header>
        <div className="setup-layout">
          <section className="setup-video" aria-label="Video and court overlay">
            {draftReady ? (
              <div ref={(node) => {
                videoRef.current = node?.querySelector("video") ?? null;
              }}>
                <CourtOverlayEditor
                  frameSize={draftFrameSize}
                  keypoints={keypoints}
                  proposalKeypoints={proposal.keypoints}
                  onChange={setKeypoints}
                  videoSrc={`/api/v1/matches/${encodeURIComponent(matchId)}/media/proxy`}
                  selectedTimestampSeconds={proposalTimestampSeconds}
                />
              </div>
            ) : (
              <div className="video-stage">
                <video
                  ref={videoRef}
                  src={`/api/v1/matches/${encodeURIComponent(matchId)}/media/proxy`}
                  controls
                  preload="metadata"
                  aria-label="Match calibration video"
                  onLoadedMetadata={(event) => {
                    const video = event.currentTarget;
                    if (video.videoWidth > 0 && video.videoHeight > 0) {
                      setDraftFrameSize({ width: video.videoWidth, height: video.videoHeight });
                    }
                  }}
                />
              </div>
            )}
            <div className="calibration-actions">
              <button type="button" className="button-secondary" disabled={propose.isPending || draftFrameSize === null} onClick={() => propose.mutate()}>
                {propose.isPending ? "Detecting court…" : "Propose at current frame"}
              </button>
              {draftReady ? (
                <button type="button" className="button-primary" disabled={save.isPending} onClick={() => save.mutate()}>
                  {save.isPending ? "Saving court…" : "Save court"}
                </button>
              ) : null}
            </div>
            {propose.isError ? <p role="alert" className="status-error">No reliable proposal at this frame. Seek to a clear full-court view and try again.</p> : null}
            {save.isError ? <p role="alert" className="status-error">Calibration could not be saved. Check the point layout and try again.</p> : null}
          </section>
          <aside className="instrument-panel" aria-label="Calibration instruments">
            <h2>Start with the picture</h2>
            {proposal === null ? <p>Pause on a clear full-court view, then ask SquashVision to find the lines.</p> : (
              <>
                <p>Proposal confidence {Math.round(proposal.confidence * 100)}%</p>
                <p>{proposal.intersectionCount} court intersections · {proposal.lineCount} detected lines</p>
                <p>Save the inspected point layout before choosing a processing profile.</p>
              </>
            )}
          </aside>
        </div>
        </details>
      </AppShell>
    );
  }
  const savedCalibration = calibration.data;
  if (savedCalibration === undefined) {
    return (
      <AppShell matchId={matchId} active="setup">
        <div className="action-state" role="alert">
          <h1>Calibration response invalid</h1>
          <button type="button" onClick={() => void calibration.refetch()}>Reload calibration</button>
        </div>
      </AppShell>
    );
  }
  if (savedCalibration.frameSize === null) {
    return (
      <AppShell matchId={matchId} active="setup">
        <div className="action-state" role="alert">
          <h1>Video dimensions unavailable</h1>
          <p>The proxy metadata has no intrinsic frame size. Re-ingest the source video before calibration.</p>
          <button type="button" onClick={() => void match.refetch()}>Reload video metadata</button>
        </div>
      </AppShell>
    );
  }


  const result = savedCalibration.result;
  const frameSize = savedCalibration.frameSize;
  const proxy = match.data.assets.find((asset) => asset.kind === "proxy");
  const timestampMapAvailable = proxy?.timestampIndexAvailable === true;
  const activeKeypoints = keypoints.length === 0 ? savedCalibration.keypoints : keypoints;
  const dirty = !equalPoints(activeKeypoints, savedCalibration.keypoints);

  return (
    <AppShell matchId={matchId} active="setup">
      <header className="page-heading setup-heading">
        <p className="kicker">Court setup for {match.data.title}</p>
        <h1>Calibrate the court</h1>
        <p>Scrub to a clear frame, then drag each signal point onto the court corner. Save once; every distance in the journal depends on this careful step.</p>
        <ol className="setup-steps" aria-label="Court setup steps">
          <li data-state="complete">Choose a frame</li>
          <li data-state="complete">Adjust the points</li>
          <li data-state={dirty ? "current" : "complete"}>Save the court</li>
        </ol>
      </header>
      <details className="playing-area-disclosure"><summary>Playing area · exclude spectators</summary>{playingAreaPanel}</details>
      <div className="setup-layout">
        <section className="setup-video" aria-label="Video and court overlay">
          <div ref={(node) => {
            videoRef.current = node?.querySelector("video") ?? null;
          }}>
            <CourtOverlayEditor
              frameSize={frameSize}
              keypoints={activeKeypoints}
              proposalKeypoints={proposal?.keypoints ?? savedCalibration.keypoints}
              onChange={setKeypoints}
              videoSrc={`/api/v1/matches/${encodeURIComponent(matchId)}/media/proxy`}
              selectedTimestampSeconds={proposalTimestampSeconds}
            />
          </div>
          <div className="calibration-actions">
            <button type="button" className="button-secondary" disabled={propose.isPending} onClick={() => propose.mutate()}>
              {propose.isPending ? "Detecting court…" : "Propose at current frame"}
            </button>
            <button type="button" className="button-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? "Saving court…" : "Save court"}
            </button>
            <span className={`court-save-status${dirty ? " is-dirty" : ""}`} role="status">{dirty ? "Court edits not saved" : "Court saved"}</span>
          </div>
          {propose.isError ? <p role="alert" className="status-error">No reliable proposal at this frame. Seek to a clear full-court view and try again.</p> : null}
          {save.isError && !conflict ? <p role="alert" className="status-error">Calibration could not be saved. Check the point layout and try again.</p> : null}
          {conflict ? (
            <div role="alert" className="conflict-state">
              <h2>A newer calibration was saved</h2>
              <p>Unsaved manual edits retained. Reload only when you are ready to replace them.</p>
              <button type="button" className="button-secondary" onClick={() => {
                setConflict(false);
                void calibration.refetch();
              }}>Reload saved calibration</button>
            </div>
          ) : null}
        </section>
        <aside className="instrument-panel" aria-label="Calibration instruments">
          <h2>Finish the setup</h2>
          <p>Review the court, choose how deeply to analyse, then begin.</p>
          <details className="technical-details">
            <summary>Calibration quality and available measurements</summary>
            <dl className="instrument-readout">
              <div><dt>Confidence</dt><dd>{Math.round(result.confidence * 100)}%</dd></div>
              <div><dt>RMS error</dt><dd>RMS {result.rmsErrorPx?.toFixed(1) ?? "—"} px</dd></div>
              <div><dt>Max error</dt><dd>{result.maxErrorPx?.toFixed(1) ?? "—"} px</dd></div>
              <div><dt>Inliers</dt><dd>{result.inlierMask.filter(Boolean).length} of {result.inlierMask.length} inliers</dd></div>
            </dl>
            {result.warnings.length > 0 ? <ul className="warning-list">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
            <ul className="capability-list">
              <li>{result.capabilities.imageSpace ? "Image position available" : "Image position unavailable"}</li>
              <li>{result.capabilities.floorPosition ? "Floor position available" : "Floor position unavailable until court geometry validates"}</li>
              <li>{result.capabilities.movementDistance ? "Movement distance available" : "Movement distance unavailable until floor position validates"}</li>
              <li>{result.capabilities.speed && timestampMapAvailable
                ? "Speed available"
                : !timestampMapAvailable
                  ? "Speed unavailable because this proxy has no verified timestamp map."
                  : "Speed unavailable because calibration did not validate speed; adjust court points and save again."}</li>
            </ul>
          </details>
          {profilePicker}
          <div className="start-analysis-row">
            <div
              className={`calibration-verdict${result.calibrated ? " is-ready" : ""}`}
              role="status"
              aria-label="Court quality"
            >
              <strong>{result.calibrated ? "Ready to analyse" : "Review court placement"}</strong>
              <span>{Math.round(result.confidence * 100)}% confidence</span>
            </div>
            <button
              type="button"
              className="button-primary start-analysis"
              disabled={start.isPending || models.data.some((model) => model.required && model.state !== "ready")}
              onClick={() => start.mutate("calibrated")}
            >
              {start.isPending ? "Starting analysis…" : "Start analysis"}
            </button>
          </div>
          {start.isError ? <p role="alert" className="status-error">{start.error instanceof ApiError && start.error.code === "required_models_unavailable" ? "Install required local models before analysis." : "Save a valid calibration before analysis."}</p> : null}
        </aside>
      </div>
    </AppShell>
  );
}
