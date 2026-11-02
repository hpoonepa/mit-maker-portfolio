import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import type { components } from "../../api/types.generated";
import { EventTimeline } from "./EventTimeline";
import { formatMatchTime } from "./analysis-model";
import { VideoOverlay } from "./VideoOverlay";

type PlayerObservation = components["schemas"]["PlayerObservationDetail"];
type BallObservation = components["schemas"]["BallObservationDetail"];
type TimelineItem = components["schemas"]["TimelineItem"];

const SPEEDS = [0.25, 0.5, 1, 1.5, 2] as const;

function boundedTimeUs(timeUs: number, durationUs: number): number {
  // The proxy frame map ends before a container's trailing audio can end.
  return Math.max(0, durationUs > 0 ? Math.min(timeUs, durationUs - 1) : timeUs);
}

export interface PlaybackImpactMarker {
  imagePosition: [number, number];
  sourceWidth: number;
  sourceHeight: number;
  kind: string;
  /** Exact playback/proxy timestamp, not source-video time. */
  timestampUs: number;
}

interface EvidenceWorkspaceProps {
  matchId: string;
  reportRevision: number;
  evidenceLoading: boolean;
  currentTimeUs: number;
  durationUs: number;
  playing: boolean;
  playbackError: string | null;
  playbackRate: number;
  nearestStep: boolean;
  videoSize: { width?: number; height?: number };
  videoRef: RefObject<HTMLVideoElement | null>;
  selectedStatusRef: RefObject<HTMLOutputElement | null>;
  players: PlayerObservation[];
  balls: BallObservation[];
  events: TimelineItem[];
  windowRange: { startUs: number; endUs: number };
  selectedEvent: TimelineItem | null;
  selectedEventId: string | null;
  inspector: ReactNode;
  statsSidecar?: ReactNode;
  impactMarker?: PlaybackImpactMarker | null;
  overlayControlsElement: HTMLDivElement | null;
  setOverlayControlsElement: (node: HTMLDivElement | null) => void;
  onLoadedMetadata: (width: number, height: number) => void;
  onTimeUpdate: (timeUs: number) => void;
  onRateChange: (rate: number) => void;
  onPlayingChange: (playing: boolean) => void;
  onPlaybackError: (message: string | null) => void;
  onTogglePlayback: () => void;
  onStepEvidence: (direction: -1 | 1) => void;
  onSeekTimeline: (timestampUs: number, eventId: string | null) => void;
  onScrub: (timestampUs: number) => void;
}

export function EvidenceWorkspace({
  matchId,
  reportRevision,
  evidenceLoading,
  currentTimeUs,
  durationUs,
  playing,
  playbackError,
  playbackRate,
  nearestStep,
  videoSize,
  videoRef,
  selectedStatusRef,
  players,
  balls,
  events,
  windowRange,
  selectedEvent,
  selectedEventId,
  overlayControlsElement,
  inspector,
  statsSidecar,
  impactMarker,
  setOverlayControlsElement,
  onLoadedMetadata,
  onTimeUpdate,
  onRateChange,
  onPlayingChange,
  onPlaybackError,
  onTogglePlayback,
  onStepEvidence,
  onSeekTimeline,
  onScrub,
}: EvidenceWorkspaceProps) {
  const instrumentRef = useRef<HTMLElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [fullscreenError, setFullscreenError] = useState<string | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (video === null || typeof video.requestVideoFrameCallback !== "function") return;
    let callbackId = 0;
    let active = true;
    const presented = (_now: number, frame: VideoFrameCallbackMetadata): void => {
      if (!active) return;
      onTimeUpdate(boundedTimeUs(Math.round(frame.mediaTime * 1_000_000), durationUs));
      callbackId = video.requestVideoFrameCallback(presented);
    };
    callbackId = video.requestVideoFrameCallback(presented);
    return () => { active = false; video.cancelVideoFrameCallback(callbackId); };
  }, [videoRef, onTimeUpdate, durationUs]);

  useEffect(() => {
    const updateFullscreen = (): void => setIsFullscreen(document.fullscreenElement === instrumentRef.current);
    document.addEventListener("fullscreenchange", updateFullscreen);
    return () => document.removeEventListener("fullscreenchange", updateFullscreen);
  }, []);

  const setRate = (rate: number): void => {
    const video = videoRef.current;
    if (video === null) return;
    video.playbackRate = rate;
    onRateChange(rate);
  };
  const fullscreen = async (): Promise<void> => {
    setFullscreenError(null);
    try {
      if (document.fullscreenElement === instrumentRef.current) {
        await document.exitFullscreen();
      } else if (instrumentRef.current?.requestFullscreen !== undefined) {
        await instrumentRef.current.requestFullscreen();
      } else {
        setFullscreenError("Fullscreen is not available in this browser.");
      }
    } catch {
      setFullscreenError("Fullscreen could not open. Try again, or continue watching here.");
    }
  };

  return (
    <section className="evidence-workstation" role="region" aria-label="Video evidence workstation">
      <div className="analysis-grid">
        <section ref={instrumentRef} className="video-instrument" aria-label="Video evidence instrument">
          {evidenceLoading ? <div className="status-neutral evidence-loading" role="status">Loading evidence for report revision {reportRevision}…</div> : null}
          <div className="video-stage analysis-video-stage">
            <video
              ref={videoRef}
              src={`/api/v1/matches/${encodeURIComponent(matchId)}/media/proxy`}
              preload="metadata"
              playsInline
              aria-label="Match video evidence"
              onLoadedMetadata={(event) => {
                if (event.currentTarget.videoWidth > 0 && event.currentTarget.videoHeight > 0) {
                  onLoadedMetadata(event.currentTarget.videoWidth, event.currentTarget.videoHeight);
                }
              }}
              onTimeUpdate={(event) => onTimeUpdate(boundedTimeUs(Math.round(event.currentTarget.currentTime * 1_000_000), durationUs))}
              onRateChange={(event) => onRateChange(event.currentTarget.playbackRate)}
              onPlay={() => { onPlaybackError(null); onPlayingChange(true); }}
              onPause={() => onPlayingChange(false)}
              onEnded={(event) => {
                onTimeUpdate(boundedTimeUs(Math.round(event.currentTarget.currentTime * 1_000_000), durationUs));
                onPlayingChange(false);
              }}
              onError={() => { onPlayingChange(false); onPlaybackError("The match video could not be loaded. Reload the video to try again."); }}
            />
            <VideoOverlay
              matchId={matchId}
              currentTimeUs={currentTimeUs}
              playing={playing}
              videoRef={videoRef}
              players={players}
              balls={balls}
              controlsContainer={overlayControlsElement}
              sourceWidth={videoSize.width}
              sourceHeight={videoSize.height}
              selectedEvent={selectedEvent}
            />
            {impactMarker && currentTimeUs >= impactMarker.timestampUs && currentTimeUs < impactMarker.timestampUs + 250_000 ? (
              <svg className="playback-impact-marker" viewBox={`0 0 ${impactMarker.sourceWidth} ${impactMarker.sourceHeight}`} preserveAspectRatio="xMidYMid meet" aria-hidden="true" data-kind={impactMarker.kind} data-timestamp-us={impactMarker.timestampUs}>
                <circle cx={impactMarker.imagePosition[0]} cy={impactMarker.imagePosition[1]} r="10" vectorEffect="non-scaling-stroke" />
              </svg>
            ) : null}
          </div>
          <label className="match-scrubber">
            <span>Match position</span>
            <input
              type="range"
              aria-label="Match playback position"
              aria-valuetext={`${formatMatchTime(currentTimeUs)} of ${formatMatchTime(durationUs)}`}
              min={0}
              max={durationUs / 1_000_000}
              step={0.01}
              value={Math.min(durationUs, Math.max(0, currentTimeUs)) / 1_000_000}
              disabled={durationUs <= 0}
              onChange={(event) => onScrub(boundedTimeUs(Math.round(Number(event.currentTarget.value) * 1_000_000), durationUs))}
            />
            <span className="mono">{formatMatchTime(currentTimeUs)} / {formatMatchTime(durationUs)}</span>
          </label>
          <div className="playback-controls">
            <div className="transport-group" role="group" aria-label="Playback transport">
              <button type="button" aria-label={playing ? "Pause" : "Play"} onClick={onTogglePlayback}><span aria-hidden="true">{playing ? "Ⅱ" : "▶"}</span><span>{playing ? "Pause" : "Play"}</span></button>
            </div>
            <div className="transport-group" role="group" aria-label="Evidence frame navigation">
              <button type="button" aria-label="Previous evidence frame" onClick={() => onStepEvidence(-1)}><span aria-hidden="true">←</span><span>Prev frame</span></button>
              <button type="button" aria-label="Next evidence frame" onClick={() => onStepEvidence(1)}><span>Next frame</span><span aria-hidden="true">→</span></button>
            </div>
            <div className="transport-group" role="group" aria-label="Evidence view">
              <button type="button" aria-label={isFullscreen ? "Exit fullscreen evidence" : "Fullscreen evidence"} aria-pressed={isFullscreen} onClick={() => void fullscreen()}><span aria-hidden="true">⛶</span><span>{isFullscreen ? "Exit fullscreen" : "Fullscreen"}</span></button>
            </div>
            <div className="speed-controls" role="group" aria-label="Playback speed">
              {SPEEDS.map((speed) => <button key={speed} type="button" aria-pressed={playbackRate === speed} onClick={() => setRate(speed)}>{speed}×</button>)}
            </div>
            <output ref={selectedStatusRef} tabIndex={-1} data-testid="selected-time-status" className="sr-only" aria-live={playing ? "off" : "polite"}>
              {formatMatchTime(currentTimeUs, true)} / {formatMatchTime(durationUs)}{nearestStep ? " · nearest evidence timestamp" : ""}
            </output>
          </div>
          {playbackError === null ? null : <div className="status-error playback-error" role="alert"><p>{playbackError}</p><button type="button" onClick={() => { onPlaybackError(null); videoRef.current?.load(); }}>Reload video</button></div>}
          {fullscreenError === null ? null : <div className="status-error playback-error" role="alert"><p>{fullscreenError}</p></div>}
          <div ref={setOverlayControlsElement} className="overlay-controls-host" />
        </section>
        {statsSidecar === undefined ? null : <aside className="analysis-sidecar" aria-label="Live match stats">{statsSidecar}</aside>}
      </div>
      <details className="review-tools">
        <summary>Review tools</summary>
        <EventTimeline events={events} startUs={windowRange.startUs} endUs={windowRange.endUs} currentTimeUs={currentTimeUs} selectedEventId={selectedEventId} onSeek={onSeekTimeline} />
        <section className="analysis-inspector" aria-label="Selected evidence inspector">{inspector}</section>
      </details>
    </section>
  );
}
